"""
Publish router — POST /api/v1/publish

Accepts a publish request, runs rules checks, creates a background job,
and returns 202 Accepted + job_id. The actual publish runs asynchronously.

Must-haves covered: #4 (rules), #6 (idempotency), Integration Standard #3 (202+job).
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.schemas.error import make_error
from api.schemas.job import JobResponse
from api.schemas.connector import Rendition, DestinationRef, Connection
from api.services import job_manager, idempotency as idem_svc
from api.services.rules_engine import check_rules
from api.models.destination import Destination
from api.middleware.logging_mw import get_logger
from connectors.registry import get_connector
from pydantic import BaseModel
from typing import Optional

log = get_logger("routers.publish")
router = APIRouter(prefix="/api/v1", tags=["Publish"])


class PublishJobRequest(BaseModel):
    """Full publish job request body."""
    rendition: Rendition
    destination_id: str
    connection: Connection
    callback_url: Optional[str] = None


async def _run_publish_job(
    job_id: str,
    request: PublishJobRequest,
    idempotency_key: str,
    db_url: str,
):
    """
    Background task: run rules → idempotency → connector publish.
    Runs after the 202 response has been sent.
    """
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy import select
    from api.services.storage import upload_json, build_manifest, get_download_url
    import time

    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        start = time.monotonic()
        try:
            # Mark job as running
            await job_manager.update_job(db, job_id, status="running", progress=10)
            await db.commit()

            # Load destination
            result = await db.execute(
                select(Destination).where(Destination.id == request.destination_id)
            )
            destination = result.scalar_one_or_none()
            if not destination:
                await job_manager.update_job(
                    db, job_id, status="failed", progress=0,
                    error_code="DEST_SPEC_VIOLATION",
                    error_message=f"Destination '{request.destination_id}' not found.",
                )
                await db.commit()
                return

            # Check rules — any violation blocks the publish
            violations = await check_rules(request.rendition, destination, db)
            if violations:
                first = violations[0]
                await job_manager.update_job(
                    db, job_id, status="failed", progress=0,
                    error_code=first["code"],
                    error_message=first["message"],
                    result_data={"violations": violations},
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

            # Build destination ref
            dest_ref = DestinationRef(
                destination_id=destination.id,
                platform_key=destination.platform_key,
                surface=destination.surface,
                instance_config=destination.instance_config or {},
            )

            # Call the connector publish method
            publish_result = await connector.publish(
                request.rendition, dest_ref, request.connection, idempotency_key
            )

            # Save platform_post_id to idempotency record immediately
            response_data = {
                "job_id": job_id,
                "platform_post_id": publish_result.platform_post_id,
                "live_url": publish_result.live_url,
                "status": publish_result.status,
                "destination_id": request.destination_id,
            }
            await idem_svc.save_result(
                db, idempotency_key, destination.connector_key,
                request.destination_id, publish_result.platform_post_id, response_data,
            )

            # Build and store manifest
            elapsed = time.monotonic() - start
            manifest = build_manifest(
                "publish", connector_key=destination.connector_key,
                timings={"total_seconds": elapsed},
                ai_generated=request.rendition.is_ai_generated,
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

        except Exception as exc:
            log.error("publish_job_error", job_id=job_id, error=str(exc))
            err_code = "PLATFORM_UNAVAILABLE"
            err_msg = str(exc)
            detail = getattr(exc, "detail", None)
            if isinstance(detail, dict):
                inner_err = detail.get("error", {})
                err_code = inner_err.get("code", err_code)
                err_msg = inner_err.get("message", err_msg)
            elif isinstance(detail, str):
                err_msg = detail

            await job_manager.update_job(
                db, job_id, status="failed",
                error_code=err_code,
                error_message=err_msg,
            )
            await db.commit()
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
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
):
    """
    Submit a publish job. Returns 202 + job_id immediately.
    Poll GET /api/v1/jobs/{job_id} for status.

    Requires: Idempotency-Key header (same key = same job, no duplicate posts).
    """
    # Check idempotency — returns cached response if duplicate
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
        # Return the original job_id — no duplicate work
        return JobResponse(job_id=existing_job_id)

    # Create the job record
    job = await job_manager.create_job(db, "publish", request.callback_url)

    # Record intent in Postgres BEFORE calling the platform
    record = await idem_svc.record_intent(
        db, idempotency_key, "publish",
        request.destination_id, request.model_dump(), job.id,
    )
    if not record:
        # Concurrent request won the race — look it up
        _, cached = await idem_svc.check_idempotency(
            db, idempotency_key, "publish",
            request.destination_id, request.model_dump(),
        )
        if cached:
            return JobResponse(job_id=cached.get("job_id", job.id))

    await db.commit()

    # Launch background publish task
    from api.config import settings
    background_tasks.add_task(
        _run_publish_job, job.id, request, idempotency_key, settings.DATABASE_URL
    )

    return JobResponse(job_id=job.id)
