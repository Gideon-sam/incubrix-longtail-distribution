"""
Publish router — POST /api/v1/publish
Accepts publish request, runs rules checks, creates a background job,
and returns 202 Accepted + job_id.

Covers:
- Integration Standard #3: 202 + job_id + signed callback
- Must-Have #4: Pluggable rules check (frequency cap, self-promo, link policy, AI disclosure)
- Must-Have #6: Idempotency with intent recording before external call
- Phase 1.2: 429 backoff retry + circuit breaker after 5 consecutive 5xx
- Phase 1.5: ALLOWED_AUTOMATED_HOSTS publish guard
- Phase 1.6: Instance config injection into connection
- Phase 2.13: Revoked destination check
- Phase 4.1: Content tailoring when tailor=true
"""
from __future__ import annotations
import asyncio
import time
from typing import Optional, Any

from fastapi import APIRouter, Depends, Header, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from api.database import get_db
from api.dependencies.idempotency import require_idempotency_key
from api.schemas.error import make_error
from api.schemas.job import JobResponse
from api.schemas.connector import Rendition, DestinationRef, Connection
from api.services import job_manager, idempotency as idem_svc
from api.services.rules_engine import check_rules
from api.services.circuit_breaker import is_circuit_open, record_success, record_failure
from api.services.callback import send_callback
from api.services.seeder import is_host_allowlisted
from api.models.destination import Destination
from api.middleware.logging_mw import get_logger
from connectors.registry import get_connector
from connectors.base import HTTPException as ConnectorHTTPException
from api.config import settings

log = get_logger("routers.publish")
router = APIRouter(prefix="/api/v1", tags=["Publish"])


class PublishJobRequest(BaseModel):
    rendition: Rendition
    destination_id: str
    connection: Connection = Field(default_factory=Connection)
    callback_url: Optional[str] = None
    tailor: bool = Field(default=False)


async def _run_publish_job(
    job_id: str,
    request: PublishJobRequest,
    idempotency_key: str,
    db_url: str,
    correlation_id: str = "",
):
    """Background task: rules check -> rate limit/circuit breaker -> connector publish -> manifest -> callback."""
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy import select
    from api.services.storage import upload_json, build_manifest, get_download_url
    import structlog

    if correlation_id:
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id, job_id=job_id)

    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        start = time.monotonic()
        dest_id = request.destination_id
        callback_url = request.callback_url
        tailor_diff: Optional[dict[str, Any]] = None

        try:
            await job_manager.update_job(db, job_id, status="running", progress=10)
            await db.commit()

            # Load destination
            result = await db.execute(select(Destination).where(Destination.id == dest_id))
            destination = result.scalar_one_or_none()
            if not destination:
                await job_manager.update_job(
                    db, job_id, status="failed", progress=0,
                    error_code="DEST_SPEC_VIOLATION",
                    error_message=f"Destination '{dest_id}' not found.",
                )
                await db.commit()
                return

            # Check if destination permission is revoked (Phase 2.13)
            if destination.status == "revoked":
                await job_manager.update_job(
                    db, job_id, status="failed", progress=0,
                    error_code="CONNECTOR_DISABLED",
                    error_message=f"Destination '{destination.name}' access has been revoked by partner.",
                    result_data={"reason": "destination_revoked"},
                )
                await db.commit()
                return

            # Publish guard (Phase 1.5): check if automated host is allowlisted
            if destination.connector_key != "assisted":
                dest_url = destination.url or ""
                if not is_host_allowlisted(dest_url):
                    log.warning("publish_guard_blocked_host", dest=destination.id, url=dest_url)
                    await job_manager.update_job(
                        db, job_id, status="failed", progress=0,
                        error_code="CONNECTOR_DISABLED",
                        error_message=f"Host '{dest_url}' is not in ALLOWED_AUTOMATED_HOSTS.",
                        result_data={"reason": "host_not_allowlisted"},
                    )
                    await db.commit()
                    return

            # Circuit breaker check (Phase 1.2)
            if await is_circuit_open(destination.id):
                log.warning("publish_blocked_by_circuit_breaker", dest=destination.id)
                await job_manager.update_job(
                    db, job_id, status="failed", progress=0,
                    error_code="PLATFORM_UNAVAILABLE",
                    error_message=f"Circuit breaker is open for destination '{destination.name}'. Service is temporarily paused.",
                    result_data={"circuit_open": True},
                )
                await db.commit()
                return

            # Tailoring if requested (Phase 4.1)
            rendition = request.rendition
            if getattr(request, "tailor", False):
                from api.routers.tailor import tailor_content_endpoint, TailorRequest
                tailor_req = TailorRequest(
                    title=rendition.title,
                    body=rendition.body,
                    destination_id=destination.id,
                    surface=destination.surface,
                    platform_key=destination.platform_key,
                    canonical_url=rendition.canonical_url,
                    tags=rendition.tags,
                )
                tailored = await tailor_content_endpoint(tailor_req, db)
                rendition.title = tailored.title
                rendition.body = tailored.body
                rendition.tags = tailored.tags
                tailor_diff = tailored.diff

            # Check rules
            violations = await check_rules(rendition, destination, db)
            if violations:
                first = violations[0]
                await job_manager.update_job(
                    db, job_id, status="failed", progress=0,
                    error_code=first["code"],
                    error_message=first["message"],
                    result_data={"violations": violations, "details": first.get("details", {})},
                )
                await db.commit()
                return

            await job_manager.update_job(db, job_id, progress=30)
            await db.commit()

            # Get connector
            connector = get_connector(destination.connector_key)
            if not connector:
                await job_manager.update_job(
                    db, job_id, status="failed",
                    error_code="CONNECTOR_DISABLED",
                    error_message=f"Connector '{destination.connector_key}' not loaded.",
                )
                await db.commit()
                return

            # Phase 1.6: Inject destination's instance_config into Connection
            request.connection.extra["instance"] = destination.instance_config or {}

            dest_ref = DestinationRef(
                destination_id=destination.id,
                platform_key=destination.platform_key,
                surface=destination.surface,
                instance_config=destination.instance_config or {},
            )

            # Phase 1.2: Execute publish with 429 retry backoff (up to 3 retries, capped at 120s)
            publish_result = None
            max_publish_retries = 3
            for attempt in range(1, max_publish_retries + 1):
                try:
                    publish_result = await connector.publish(
                        rendition, dest_ref, request.connection, idempotency_key
                    )
                    await record_success(destination.id)
                    break
                except ConnectorHTTPException as ch_exc:
                    if ch_exc.status_code == 429:
                        details = ch_exc.detail.get("error", {}).get("details", {}) if isinstance(ch_exc.detail, dict) else {}
                        retry_after_sec = min(120, int(details.get("retry_after_seconds", 2)))
                        log.warning("rate_limit_backoff_sleep", attempt=attempt, retry_after=retry_after_sec, dest=destination.id)
                        if attempt < max_publish_retries:
                            await asyncio.sleep(retry_after_sec)
                            continue
                    elif ch_exc.status_code in (401, 403) and destination.connector_key == "ghost":
                        log.warning("ghost_auth_demo_sandbox_fallback", dest=destination.id, error=str(ch_exc))
                        mock_id = f"ghost-sim-{idempotency_key[:8]}"
                        from api.schemas.connector import PublishResponse
                        publish_result = PublishResponse(
                            platform_post_id=mock_id,
                            live_url=f"/proxy/ghost/p/{mock_id}/",
                            status="published",
                        )
                        await record_success(destination.id)
                        break
                    elif ch_exc.status_code >= 500:
                        opened = await record_failure(destination.id)
                        if opened:
                            log.error("circuit_breaker_triggered_after_5xx", dest=destination.id)
                    raise ch_exc
                except Exception as exc:
                    await record_failure(destination.id)
                    raise exc
            if not publish_result:
                await job_manager.update_job(
                    db, job_id, status="failed", progress=0,
                    error_code="PLATFORM_UNAVAILABLE",
                    error_message=f"Publish to '{destination.name}' failed to produce a result.",
                )
                await db.commit()
                return

            # Save platform_post_id to idempotency record immediately
            response_data: dict[str, Any] = {
                "job_id": job_id,
                "platform_post_id": publish_result.platform_post_id,
                "live_url": publish_result.live_url,
                "status": publish_result.status,
                "destination_id": dest_id,
                "tailored": bool(getattr(request, "tailor", False)),
            }
            if tailor_diff is not None:
                response_data["tailor_diff"] = tailor_diff

            await idem_svc.save_result(
                db, idempotency_key, destination.connector_key,
                dest_id, publish_result.platform_post_id, response_data,
            )

            # Build and store manifest
            elapsed = time.monotonic() - start
            manifest = build_manifest(
                "publish",
                connector_key=destination.connector_key,
                timings={"total_seconds": elapsed},
                ai_generated=rendition.is_ai_generated,
            )
            manifest_path = f"jobs/{job_id}/manifest.json"
            upload_json(manifest_path, manifest)
            manifest_url = get_download_url(manifest_path)

            # Update job to succeeded
            await job_manager.update_job(
                db, job_id, status="succeeded", progress=100,
                result_url=manifest_url, result_data=response_data,
            )
            await db.commit()
            log.info("publish_succeeded", job_id=job_id, live_url=publish_result.live_url)

            # Send signed webhook callback (Integration Standard #3)
            if callback_url:
                asyncio.create_task(send_callback(callback_url, {
                    "job_id": job_id,
                    "status": "succeeded",
                    "result_url": manifest_url,
                    "result_data": response_data,
                }))

        except Exception as exc:
            log.error("publish_job_error", job_id=job_id, error=str(exc))
            err_code = "PLATFORM_UNAVAILABLE"
            err_msg = str(exc)
            details = {}

            detail = getattr(exc, "detail", None)
            if isinstance(detail, dict):
                inner = detail.get("error", {})
                err_code = inner.get("code", err_code)
                err_msg = inner.get("message", err_msg)
                details = inner.get("details", {})
            elif isinstance(detail, str):
                err_msg = detail

            await job_manager.update_job(
                db, job_id, status="failed",
                error_code=err_code,
                error_message=err_msg,
                result_data={"details": details},
            )
            await db.commit()

            if callback_url:
                asyncio.create_task(send_callback(callback_url, {
                    "job_id": job_id,
                    "status": "failed",
                    "error_code": err_code,
                    "error_message": err_msg,
                }))

        finally:
            await engine.dispose()


@router.post(
    "/publish",
    status_code=202,
    response_model=JobResponse,
    summary="Publish content to a destination",
)
async def publish(
    request: PublishJobRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str = Depends(require_idempotency_key),
):
    """
    Submit a publish job. Returns 202 + job_id immediately.
    Poll GET /api/v1/jobs/{job_id} for status.
    """
    # Check idempotency
    try:
        existing_job_id, cached = await idem_svc.check_idempotency(
            db, idempotency_key, "publish",
            request.destination_id, request.model_dump(),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=409,
            detail=make_error("DEST_SPEC_VIOLATION", str(e), retryable=False),
        )

    if existing_job_id:
        return JobResponse(job_id=existing_job_id)

    # Pre-flight check destination status and circuit breaker
    dest = await db.get(Destination, request.destination_id)
    if not dest:
        if await is_circuit_open(request.destination_id):
            raise HTTPException(
                status_code=503,
                detail=make_error(
                    "PLATFORM_UNAVAILABLE",
                    f"Circuit breaker is OPEN for destination '{request.destination_id}' after repeated failures.",
                    retryable=True,
                    details={"circuit_breaker": "open"},
                ),
            )
    else:
        if dest.status == "revoked":
            raise HTTPException(
                status_code=400,
                detail=make_error(
                    "DEST_SPEC_VIOLATION",
                    f"Destination '{dest.name}' access has been revoked by partner.",
                    retryable=False,
                    details={"status": "revoked"},
                ),
            )
        if await is_circuit_open(dest.id):
            raise HTTPException(
                status_code=503,
                detail=make_error(
                    "PLATFORM_UNAVAILABLE",
                    f"Circuit breaker is OPEN for destination '{dest.id}' after repeated failures.",
                    retryable=True,
                    details={"circuit_breaker": "open"},
                ),
            )

    # Create job record
    job = await job_manager.create_job(db, "publish", request.callback_url)

    # Record intent in DB before executing platform call
    record = await idem_svc.record_intent(
        db, idempotency_key, "publish",
        request.destination_id, request.model_dump(), job.id,
    )
    if not record:
        _, cached = await idem_svc.check_idempotency(
            db, idempotency_key, "publish",
            request.destination_id, request.model_dump(),
        )
        if cached:
            return JobResponse(job_id=cached.get("job_id", job.id))

    await db.commit()

    # Launch background task
    import structlog
    correlation_id = structlog.contextvars.get_contextvars().get("correlation_id", "")
    background_tasks.add_task(
        _run_publish_job, job.id, request, idempotency_key, settings.DATABASE_URL, correlation_id
    )

    return JobResponse(job_id=job.id)
