"""
Catalogue import router — Advanced level.

POST /api/v1/catalogue/import
Accepts a CSV file upload. Validates, deduplicates, checks reachability,
enriches with AI relevance scores. 1000 rows in under 5 minutes.
Returns 202 + job_id.

Also includes the AI rules capture endpoint:
POST /api/v1/rules/capture   → AI reads rules page, proposes rules (not active until confirmed)
POST /api/v1/rules/{id}/confirm → Human confirms proposed rule (fix 2f)
"""
from __future__ import annotations
import io
import time
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, UploadFile, File, BackgroundTasks, Header, HTTPException, Body
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models.destination import Destination
from api.models.rule import RuleProposal, DestinationRule
from api.services import job_manager
from api.services.ai_adapter import get_ai_adapter
from api.schemas.job import JobResponse
from api.schemas.error import make_error
from api.middleware.logging_mw import get_logger

log = get_logger("routers.catalogue")
router = APIRouter(prefix="/api/v1", tags=["Catalogue & Rules"])

# Columns required in the CSV
REQUIRED_COLS = {"name", "url", "platform_key", "connector_key", "surface"}


async def _run_catalogue_import(job_id: str, csv_bytes: bytes, db_url: str):
    """Background task: parse CSV, validate, dedup, check reachability, score relevance."""
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    import httpx

    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    ai = get_ai_adapter()

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

            # Process row by row
            async with httpx.AsyncClient(timeout=10) as http:
                for idx, row in df.iterrows():
                    pct = 15 + int(70 * (idx + 1) / total)
                    if idx % 50 == 0:
                        await job_manager.update_job(db, job_id, progress=pct)
                        await db.commit()

                    # Validate row
                    row_errors = []
                    for col in REQUIRED_COLS:
                        if pd.isna(row.get(col, None)) or not str(row[col]).strip():
                            row_errors.append(f"Missing required field: {col}")

                    if row_errors:
                        errors.append({"row": idx + 2, "url": str(row.get("url", "")), "errors": row_errors})
                        continue

                    # Normalize URL
                    url = str(row["url"]).strip().rstrip("/")

                    # Deduplication check: normalized URL + platform_key
                    existing = await db.execute(
                        select(Destination).where(
                            Destination.url == url,
                            Destination.platform_key == str(row["platform_key"]),
                        )
                    )
                    if existing.scalar_one_or_none():
                        duplicates += 1
                        continue

                    # Reachability check (non-blocking, best effort)
                    reachable = True
                    try:
                        resp = await http.head(url, follow_redirects=True)
                        reachable = resp.status_code < 400
                    except Exception:
                        reachable = False

                    if not reachable:
                        errors.append({"row": idx + 2, "url": url, "errors": ["URL not reachable"]})
                        # Still import — just flag it

                    # AI relevance scoring
                    score_data = {"score": 3, "reason": "Not scored yet"}
                    try:
                        desc = str(row.get("description", ""))
                        score_data = await ai.score_relevance(str(row["name"]), desc)
                    except Exception as e:
                        log.warning("relevance_score_error", row=idx, error=str(e))

                    # Create destination
                    dest = Destination(
                        name=str(row["name"]).strip(),
                        url=url,
                        platform_key=str(row["platform_key"]).strip(),
                        connector_key=str(row["connector_key"]).strip(),
                        surface=str(row.get("surface", "topic")).strip(),
                        category=str(row["category"]) if not pd.isna(row.get("category")) else None,
                        language=str(row.get("language", "en")),
                        geo=str(row["geo"]) if not pd.isna(row.get("geo")) else None,
                        est_audience=int(row["est_audience"]) if not pd.isna(row.get("est_audience")) else None,
                        rules_url=str(row["rules_url"]) if not pd.isna(row.get("rules_url")) else None,
                        frequency_cap=str(row["frequency_cap"]) if not pd.isna(row.get("frequency_cap")) else None,
                        self_promo_allowed=bool(row.get("self_promo_allowed", True)),
                        link_policy=str(row.get("link_policy", "allowed")),
                        disclosure_required=bool(row.get("disclosure_required", False)),
                        automation_allowed=bool(row.get("automation_allowed", True)),
                        relevance_score=float(score_data.get("score", 3)),
                        relevance_reason=str(score_data.get("reason", "")),
                        level="L0",
                        instance_config={},
                    )
                    db.add(dest)
                    imported += 1

            await db.flush()

            # Save import report to MinIO
            from api.services.storage import upload_json, get_download_url
            elapsed = time.monotonic() - start
            report = {
                "job_id": job_id,
                "total_rows": total,
                "imported": imported,
                "duplicates": duplicates,
                "errors": len(errors),
                "error_details": errors,
                "elapsed_seconds": elapsed,
                "rows_per_minute": int(total / (elapsed / 60)) if elapsed > 0 else 0,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
            report_path = f"jobs/{job_id}/import_report.json"
            upload_json(report_path, report)

            await job_manager.update_job(
                db, job_id, status="succeeded", progress=100,
                result_url=get_download_url(report_path),
                result_data=report,
            )
            await db.commit()
            log.info("catalogue_import_done", imported=imported, errors=len(errors))

        except Exception as exc:
            log.error("catalogue_import_error", job_id=job_id, error=str(exc))
            await job_manager.update_job(
                db, job_id, status="failed",
                error_code="PLATFORM_UNAVAILABLE", error_message=str(exc),
            )
            await db.commit()
        finally:
            await engine.dispose()


@router.post(
    "/catalogue/import",
    status_code=202,
    response_model=JobResponse,
    summary="Import destinations from CSV",
)
async def import_catalogue(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
):
    """
    Upload a CSV of destinations. Validates, deduplicates, checks reachability,
    scores relevance with AI. 1000 rows in <5 min.
    Returns 202 + job_id.
    """
    if not file.filename.endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail=make_error("DEST_SPEC_VIOLATION", "File must be a CSV.", retryable=False),
        )
    csv_bytes = await file.read()
    job = await job_manager.create_job(db, "catalogue_import")
    await db.commit()

    from api.config import settings
    background_tasks.add_task(_run_catalogue_import, job.id, csv_bytes, settings.DATABASE_URL)
    return JobResponse(job_id=job.id)


# ── Rules capture endpoints ────────────────────────────────

from pydantic import BaseModel


class RulesCaptureRequest(BaseModel):
    destination_id: str
    rules_url: str


@router.post("/rules/capture", summary="AI reads rules page and proposes rules")
async def capture_rules(
    request: RulesCaptureRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Fetch a community's rules page and use AI to propose posting rules.
    Proposals go to 'proposed' status — NOT active until a human confirms them.
    """
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(request.rules_url, follow_redirects=True)
            rules_text = resp.text[:8000]
    except Exception as e:
        raise HTTPException(
            status_code=422,
            detail=make_error("DEST_SPEC_VIOLATION", f"Cannot fetch rules page: {e}"),
        )

    ai = get_ai_adapter()
    proposals = await ai.capture_rules(rules_text)

    # Store as proposals (NOT active rules — human must confirm)
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
    return {
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
        "note": "These are PROPOSALS only. POST to /api/v1/rules/{id}/confirm to activate.",
    }


@router.post("/rules/{proposal_id}/confirm", summary="Human confirms a proposed rule")
async def confirm_rule(
    proposal_id: str,
    confirmed_by: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
):
    """
    Confirm an AI-proposed rule. Only confirmed rules are enforced.
    Fix 2f: unconfirmed rules are NEVER used.
    """
    result = await db.execute(
        select(RuleProposal).where(RuleProposal.id == proposal_id)
    )
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=404, detail=make_error(
            "DEST_SPEC_VIOLATION", f"Proposal '{proposal_id}' not found."
        ))
    if proposal.status == "confirmed":
        return {"message": "Already confirmed.", "proposal_id": proposal_id}

    # Activate the rule
    proposal.status = "confirmed"
    proposal.confirmed_by = confirmed_by
    proposal.confirmed_at = datetime.now(timezone.utc)

    # Create the active DestinationRule
    active_rule = DestinationRule(
        destination_id=proposal.destination_id,
        rule_type=proposal.rule_type,
        rule_value=proposal.rule_value,
        description=proposal.description,
        is_active=True,
    )
    db.add(active_rule)
    await db.flush()

    return {
        "message": "Rule confirmed and activated.",
        "proposal_id": proposal_id,
        "rule_id": active_rule.id,
        "rule_type": active_rule.rule_type,
        "rule_value": active_rule.rule_value,
    }
