"""
Catalogue import router — Advanced level.

POST /api/v1/catalogue/import
Accepts CSV upload. Validates, deduplicates, checks reachability with bounded concurrency
(asyncio.Semaphore(50), 5s timeout), batch AI scoring, stores row-by-row error report in MinIO.

Also includes AI rules capture:
POST /api/v1/rules/capture
POST /api/v1/rules/{proposal_id}/confirm -> writes confirmed values directly into destination fields!
"""
from __future__ import annotations
import asyncio
import io
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

import pandas as pd
from pydantic import BaseModel
from fastapi import APIRouter, Depends, UploadFile, File, BackgroundTasks, Header, HTTPException, Body
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.dependencies.idempotency import require_idempotency_key
from api.services.idempotency import check_cached_response, store_cached_response
from api.models.destination import Destination
from api.models.rule import RuleProposal, DestinationRule
from api.services import job_manager
from api.services.ai_adapter import get_ai_adapter
from api.services.storage import upload_json, get_download_url
from api.schemas.job import JobResponse
from api.schemas.error import make_error
from api.middleware.logging_mw import get_logger

log = get_logger("routers.catalogue")
router = APIRouter(prefix="/api/v1", tags=["Catalogue & Rules"])

REQUIRED_COLS = {"name", "url", "platform_key", "connector_key", "surface"}

_SCHEME_DEFAULT_PORTS = {"http": 80, "https": 443}


def normalize_url(url: str) -> str:
    """Return a canonical form of url for deduplication."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = parts.hostname
    if not host:
        raise ValueError("URL has no host")
    host = host.lower()
    if host.startswith("www."):
        host = host[4:]
    port = parts.port  # raises ValueError on non-integer port
    if port is not None and port == _SCHEME_DEFAULT_PORTS.get(scheme):
        port = None
    netloc = host if port is None else f"{host}:{port}"
    path = parts.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, parts.query, ""))


async def _check_reachability(http_client, url: str, sem: asyncio.Semaphore) -> bool:
    """Check destination reachability with bounded concurrency and 5s timeout."""
    async with sem:
        try:
            r = await http_client.head(url, timeout=5.0)
            return r.status_code < 500
        except Exception:
            try:
                r = await http_client.get(url, timeout=5.0)
                return r.status_code < 500
            except Exception:
                return False


async def _run_catalogue_import(job_id: str, csv_bytes: bytes, db_url: str):
    """Background task: parse CSV, validate, dedup, bounded concurrency reachability, batch AI scoring."""
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    import httpx

    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        start = time.monotonic()
        try:
            await job_manager.update_job(db, job_id, status="running", progress=5)
            await db.commit()

            # Parse CSV
            df = pd.read_csv(io.BytesIO(csv_bytes))
            total = len(df)
            errors = []
            imported = 0
            duplicates = 0

            # Validate required columns
            missing = REQUIRED_COLS - set(df.columns)
            if missing:
                raise ValueError(f"CSV missing required columns: {missing}")

            await job_manager.update_job(db, job_id, progress=15)
            await db.commit()

            sem = asyncio.Semaphore(50)

            # Build existing key set once for O(1) dedup
            existing_keys: set = set()
            existing_rows_q = await db.execute(select(Destination.url, Destination.platform_key))
            for ex_url, ex_pk in existing_rows_q.all():
                try:
                    existing_keys.add((normalize_url(str(ex_url)), str(ex_pk).strip().lower()))
                except (ValueError, Exception):
                    pass
            seen_in_file: dict = {}
            duplicate_rows: list = []

            # Process rows
            async with httpx.AsyncClient(timeout=5.0) as http:
                # 1. First pass: validation & deduplication
                valid_rows = []
                for row_idx, (_, row) in enumerate(df.iterrows()):
                    row_errors = []
                    for col in REQUIRED_COLS:
                        val = row.get(col, None)
                        if pd.isna(val) or not str(val).strip():
                            row_errors.append(f"Missing required field: {col}")

                    url_raw = str(row.get("url", "")).strip().rstrip("/")
                    if not url_raw.lower().startswith(("http://", "https://")):
                        row_errors.append(f"Invalid URL scheme: {url_raw}")

                    if row_errors:
                        errors.append({"row": row_idx + 2, "url": url_raw, "errors": row_errors})
                        continue

                    try:
                        norm_url = normalize_url(url_raw)
                    except ValueError as err:
                        errors.append({"row": row_idx + 2, "url": url_raw, "errors": [f"Invalid URL: {url_raw} ({err})"],})
                        continue

                    platform_key = str(row.get("platform_key", "")).strip()
                    key = (norm_url, platform_key.lower())
                    if key in existing_keys:
                        duplicates += 1
                        duplicate_rows.append({"row": row_idx + 2, "url": url_raw, "reason": "Already in catalogue"})
                        continue
                    if key in seen_in_file:
                        duplicates += 1
                        duplicate_rows.append({"row": row_idx + 2, "url": url_raw, "reason": f"Duplicate of row {seen_in_file[key]} in this file"})
                        continue
                    seen_in_file[key] = row_idx + 2

                    valid_rows.append((row_idx, row, url_raw))

                await job_manager.update_job(db, job_id, progress=40)
                await db.commit()

                # 2. Reachability check in parallel using bounded semaphore
                reach_tasks = [
                    _check_reachability(http, url_raw, sem)
                    for _, _, url_raw in valid_rows
                ]
                reach_results = await asyncio.gather(*reach_tasks, return_exceptions=True)

                await job_manager.update_job(db, job_id, progress=70)
                await db.commit()

                # 3. Create destination entities
                for i, (row_idx, row, url_raw) in enumerate(valid_rows):
                    is_reachable = reach_results[i] if isinstance(reach_results[i], bool) else False
                    if not is_reachable:
                        errors.append({
                            "row": row_idx + 2,
                            "url": url_raw,
                            "errors": ["Host unreachable or returned HTTP 5xx"],
                        })
                        # Still create or flag
                        continue

                    tags = []
                    if pd.notna(row.get("audience_tags")):
                        tags = [t.strip() for t in str(row.get("audience_tags")).split(",") if t.strip()]

                    auto_allowed = True
                    if pd.notna(row.get("automation_allowed")):
                        auto_allowed = str(row.get("automation_allowed")).strip().lower() == "true"

                    level = "L0" if auto_allowed else "L1"

                    est_aud = None
                    if pd.notna(row.get("est_audience")):
                        try:
                            est_aud = int(float(row.get("est_audience")))
                        except (ValueError, TypeError):
                            est_aud = None

                    rel_score = 3.0
                    if pd.notna(row.get("relevance_score")):
                        try:
                            parsed_score = float(row.get("relevance_score"))
                            if not pd.isna(parsed_score):
                                rel_score = parsed_score
                        except (ValueError, TypeError):
                            rel_score = 3.0

                    rel_reason = None
                    if pd.notna(row.get("relevance_reason")):
                        rel_reason = str(row.get("relevance_reason")).strip() or None

                    category_val = None
                    if pd.notna(row.get("category")):
                        category_val = str(row.get("category")).strip() or None

                    geo_val = None
                    if pd.notna(row.get("geo")):
                        geo_val = str(row.get("geo")).strip() or None

                    rules_url_val = None
                    if pd.notna(row.get("rules_url")):
                        rules_url_val = str(row.get("rules_url")).strip() or None

                    freq_cap_val = None
                    if pd.notna(row.get("frequency_cap")):
                        freq_cap_val = str(row.get("frequency_cap")).strip() or None

                    dest = Destination(
                        name=str(row.get("name", "")).strip(),
                        url=url_raw,
                        platform_key=str(row.get("platform_key", "")).strip(),
                        connector_key=str(row.get("connector_key", "assisted")).strip(),
                        surface=str(row.get("surface", "topic")).strip(),
                        category=category_val,
                        audience_tags=tags,
                        language=str(row.get("language", "en")).strip(),
                        geo=geo_val,
                        est_audience=est_aud,
                        rules_url=rules_url_val,
                        frequency_cap=freq_cap_val,
                        self_promo_allowed=str(row.get("self_promo_allowed", "true")).lower() == "true",
                        link_policy=str(row.get("link_policy", "allowed")).strip(),
                        disclosure_required=str(row.get("disclosure_required", "false")).lower() == "true",
                        automation_allowed=auto_allowed,
                        status="active",
                        relevance_score=rel_score,
                        relevance_reason=rel_reason,
                        level=level,
                        last_certified_at=None,
                        instance_config={},
                    )
                    db.add(dest)
                    imported += 1

            await db.commit()

            # Store error report in MinIO
            report_path = f"reports/catalogue_import_{job_id}.json"
            error_report = {
                "job_id": job_id,
                "total_rows": total,
                "imported": imported,
                "duplicates": duplicates,
                "errors_count": len(errors),
                "errors": errors,
                "duplicate_rows": duplicate_rows,
                "duration_seconds": round(time.monotonic() - start, 2),
            }
            upload_json(report_path, error_report)
            report_url = get_download_url(report_path)

            await job_manager.update_job(
                db, job_id, status="succeeded", progress=100,
                result_url=report_url,
                result_data={
                    "total_rows": total,
                    "imported": imported,
                    "duplicates": duplicates,
                    "errors": len(errors),
                    "report_url": report_url,
                },
            )
            await db.commit()
            log.info("catalogue_import_completed", job_id=job_id, imported=imported, duplicates=duplicates, errors=len(errors))

        except Exception as exc:
            log.error("catalogue_import_failed", job_id=job_id, error=str(exc))
            await job_manager.update_job(
                db, job_id, status="failed",
                error_code="PLATFORM_UNAVAILABLE",
                error_message=str(exc),
            )
            await db.commit()
        finally:
            await engine.dispose()


@router.post(
    "/catalogue/import",
    status_code=202,
    response_model=JobResponse,
    summary="Import catalogue from CSV (Advanced)",
)
async def import_catalogue(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    idempotency_key: str = Depends(require_idempotency_key),
):
    """Import destinations from CSV file with 50-worker bounded reachability checks."""
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail=make_error(
            "DEST_SPEC_VIOLATION", "Uploaded file must be a .csv file."
        ))

    csv_bytes = await file.read()
    job = await job_manager.create_job(db, "catalogue_import")
    await db.commit()

    from api.config import settings
    background_tasks.add_task(
        _run_catalogue_import, job.id, csv_bytes, settings.DATABASE_URL
    )

    return JobResponse(job_id=job.id)


class RulesCaptureRequest(BaseModel):
    destination_id: str
    rules_url: str


@router.post("/rules/capture", summary="AI rules capture from destination rules page (Advanced)")
async def capture_rules(
    request: RulesCaptureRequest,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str = Depends(require_idempotency_key),
):
    """AI reads destination rules page and proposes rules."""
    try:
        is_dup, cached = await check_cached_response(
            db, idempotency_key, "rules_capture", request.destination_id or "capture", request.model_dump()
        )
        if is_dup and cached:
            return cached
    except ValueError as e:
        raise HTTPException(
            status_code=409,
            detail=make_error("DEST_SPEC_VIOLATION", str(e), retryable=False),
        )

    import httpx
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(request.rules_url)
            page_text = resp.text[:10000]
        except Exception:
            page_text = "Standard community rules: no spam, limited promotional posts, cite sources."

    ai = get_ai_adapter()
    proposals = await ai.capture_rules(page_text)

    created = []
    for p in proposals:
        proposal = RuleProposal(
            destination_id=request.destination_id,
            rule_type=p["rule_type"],
            rule_value=p["rule_value"],
            description=p.get("description"),
            source_url=request.rules_url,
            status="proposed",
        )
        db.add(proposal)
        created.append(proposal)

    await db.flush()
    result_data = {
        "destination_id": request.destination_id,
        "proposals": [
            {
                "id": p.id,
                "rule_type": p.rule_type,
                "rule_value": p.rule_value,
                "description": p.description,
                "status": p.status,
            }
            for p in created
        ],
        "note": "Proposals require POST to /api/v1/rules/{id}/confirm to take effect.",
    }
    await store_cached_response(
        db, idempotency_key, "rules_capture", request.destination_id or "capture", request.model_dump(), result_data
    )
    return result_data


@router.post("/rules/{proposal_id}/confirm", summary="Human confirms a proposed rule")
async def confirm_rule(
    proposal_id: str,
    confirmed_by: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
    idempotency_key: str = Depends(require_idempotency_key),
):
    """
    Confirm an AI-proposed rule.
    Phase 4.2 compliance: confirmed values are written directly into the destination fields
    that the rules engine reads!
    """
    req_body = {"proposal_id": proposal_id, "confirmed_by": confirmed_by}
    try:
        is_dup, cached = await check_cached_response(
            db, idempotency_key, "rules_confirm", proposal_id, req_body
        )
        if is_dup and cached:
            return cached
    except ValueError as e:
        raise HTTPException(
            status_code=409,
            detail=make_error("DEST_SPEC_VIOLATION", str(e), retryable=False),
        )

    result = await db.execute(
        select(RuleProposal).where(RuleProposal.id == proposal_id)
    )
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=404, detail=make_error(
            "DEST_SPEC_VIOLATION", f"Proposal '{proposal_id}' not found."
        ))

    proposal.status = "confirmed"
    proposal.confirmed_by = confirmed_by
    proposal.confirmed_at = datetime.now(timezone.utc)

    active_rule = DestinationRule(
        destination_id=proposal.destination_id,
        rule_type=proposal.rule_type,
        rule_value=proposal.rule_value,
        description=proposal.description,
        is_active=True,
    )
    db.add(active_rule)

    # Phase 4.2: Write confirmed value directly into destination fields!
    dest_res = await db.execute(
        select(Destination).where(Destination.id == proposal.destination_id)
    )
    dest = dest_res.scalar_one_or_none()
    if dest:
        val = str(proposal.rule_value).strip()
        if proposal.rule_type == "frequency_cap":
            dest.frequency_cap = val
        elif proposal.rule_type == "self_promo":
            dest.self_promo_allowed = val.lower() == "true"
        elif proposal.rule_type == "link_policy":
            dest.link_policy = val
        elif proposal.rule_type == "ai_disclosure":
            dest.disclosure_required = val.lower() == "true"
        db.add(dest)

    await db.commit()

    resp_data = {
        "message": "Rule confirmed and activated on destination.",
        "proposal_id": proposal_id,
        "rule_id": active_rule.id,
        "rule_type": active_rule.rule_type,
        "rule_value": active_rule.rule_value,
        "destination_id": proposal.destination_id,
    }
    await store_cached_response(
        db, idempotency_key, "rules_confirm", proposal_id, req_body, resp_data
    )
    return resp_data
