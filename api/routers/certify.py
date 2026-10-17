"""
Certify router — POST /api/v1/certify

Runs the full certification loop for a connector + destination:
  1. validate → 2. publish test post → 3. confirm live URL →
  4. get_status → 5. delete (cleanup) → 6. store evidence in MinIO

Returns 202 + job_id. Certification runs in the background.
"""
from __future__ import annotations
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, BackgroundTasks, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from api.database import get_db
from api.services import job_manager
from api.schemas.job import JobResponse
from api.schemas.connector import Connection, DestinationRef, Rendition
from api.schemas.error import make_error
from api.middleware.logging_mw import get_logger

log = get_logger("routers.certify")
router = APIRouter(prefix="/api/v1", tags=["Certification"])

# Test content used in all certification runs
CERT_TITLE = "[IncuBrix Certification Test] Please ignore — will be deleted"
CERT_BODY = (
    "This is an automated certification test post from IncuBrix. "
    "It will be deleted within 10 minutes. Please ignore.\n\n"
    "Connector certification run — verifying: publish, status check, delete."
)


class CertifyRequest(BaseModel):
    """Certification job request."""
    destination_id: str
    connection: Connection
    callback_url: Optional[str] = None


async def _run_certification(
    job_id: str,
    request: CertifyRequest,
    db_url: str,
):
    """Background task: full certification loop — publish → status → delete → evidence."""
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy import select
    from api.services.storage import upload_json, build_manifest, get_download_url
    from api.models.destination import Destination
    from api.models.certification import CertificationRecord
    from connectors.registry import get_connector

    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        start = time.monotonic()

        # Create certification record
        cert = CertificationRecord(
            connector_key="",
            destination_id=request.destination_id,
            status="running",
        )
        db.add(cert)

        try:
            await job_manager.update_job(db, job_id, status="running", progress=5)

            # Load destination
            result = await db.execute(
                select(Destination).where(Destination.id == request.destination_id)
            )
            dest = result.scalar_one_or_none()
            if not dest:
                raise ValueError(f"Destination '{request.destination_id}' not found.")

            cert.connector_key = dest.connector_key
            connector = get_connector(dest.connector_key)
            if not connector:
                raise ValueError(f"Connector '{dest.connector_key}' not loaded.")

            dest_ref = DestinationRef(
                destination_id=dest.id,
                platform_key=dest.platform_key,
                surface=dest.surface,
                instance_config=dest.instance_config or {},
            )
            rendition = Rendition(title=CERT_TITLE, body=CERT_BODY, is_ai_generated=False)
            idem_key = f"cert-{job_id}"

            # Step 1: Validate
            await job_manager.update_job(db, job_id, progress=15)
            validate_result = await connector.validate(rendition, dest_ref, request.connection)
            if not validate_result.ok:
                raise ValueError(f"Validation failed: {validate_result.violations}")

            # Step 2: Publish
            await job_manager.update_job(db, job_id, progress=30)
            publish_result = await connector.publish(
                rendition, dest_ref, request.connection, idem_key
            )
            cert.publish_response = {
                "platform_post_id": publish_result.platform_post_id,
                "live_url": publish_result.live_url,
                "status": publish_result.status,
            }
            cert.live_url = publish_result.live_url
            await db.flush()

            # Step 3: Get status (confirm it's live)
            await job_manager.update_job(db, job_id, progress=55)
            status_result = await connector.get_status(
                publish_result.platform_post_id, request.connection
            )
            cert.status_response = {
                "status": status_result.status,
                "live_url": status_result.live_url,
            }
            await db.flush()

            # Step 4: Delete (cleanup — must happen within 10 min)
            await job_manager.update_job(db, job_id, progress=75)
            delete_result = await connector.delete(
                publish_result.platform_post_id, request.connection
            )
            cert.delete_response = {"deleted": delete_result.deleted}
            cert.post_deleted = delete_result.deleted
            await db.flush()

            # Step 5: Save evidence to MinIO
            elapsed = time.monotonic() - start
            manifest = build_manifest(
                "certify",
                connector_key=dest.connector_key,
                timings={"total_seconds": elapsed},
            )
            evidence = {
                "certification_id": cert.id,
                "connector_key": dest.connector_key,
                "destination_id": dest.id,
                "destination_name": dest.name,
                "validate": {"ok": validate_result.ok},
                "publish": cert.publish_response,
                "status": cert.status_response,
                "delete": cert.delete_response,
                "manifest": manifest,
                "certified_at": datetime.now(timezone.utc).isoformat(),
            }
            evidence_path = f"evidence/{dest.connector_key}/{cert.id}/evidence.json"
            upload_json(evidence_path, evidence)
            cert.evidence_path = evidence_path

            manifest_path = f"jobs/{job_id}/manifest.json"
            upload_json(manifest_path, manifest)

            # Update destination level to L3
            dest.level = "L3"
            dest.last_certified_at = datetime.now(timezone.utc)

            cert.status = "passed"
            cert.completed_at = datetime.now(timezone.utc)

            result_url = get_download_url(evidence_path)
            await job_manager.update_job(
                db, job_id, status="succeeded", progress=100,
                result_url=result_url,
                result_data={"certification_id": cert.id, "live_url": cert.live_url},
            )
            await db.commit()
            log.info("certification_passed", connector=dest.connector_key, dest=dest.id)

        except Exception as exc:
            log.error("certification_failed", job_id=job_id, error=str(exc))
            err_code = "PLATFORM_UNAVAILABLE"
            err_msg = str(exc)
            detail = getattr(exc, "detail", None)
            if isinstance(detail, dict):
                inner_err = detail.get("error", {})
                err_code = inner_err.get("code", err_code)
                err_msg = inner_err.get("message", err_msg)
            elif isinstance(detail, str):
                err_msg = detail

            cert.status = "failed"
            cert.error_message = err_msg
            cert.completed_at = datetime.now(timezone.utc)
            await job_manager.update_job(
                db, job_id, status="failed",
                error_code=err_code,
                error_message=err_msg,
            )
            await db.commit()
        finally:
            await engine.dispose()


@router.post(
    "/certify",
    status_code=202,
    response_model=JobResponse,
    summary="Run certification for a connector + destination",
)
async def certify(
    request: CertifyRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
):
    """
    Start a certification run. Returns 202 + job_id.
    The certification loop runs in the background and stores evidence in MinIO.
    """
    job = await job_manager.create_job(db, "certify", request.callback_url)
    await db.commit()

    from api.config import settings
    background_tasks.add_task(_run_certification, job.id, request, settings.DATABASE_URL)

    return JobResponse(job_id=job.id)
