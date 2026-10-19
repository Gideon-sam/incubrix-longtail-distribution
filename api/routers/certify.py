"""
Certify router — POST /api/v1/certify
Runs full certification loop for a connector + destination:
  1. validate
  2. publish test post
  3. confirm live URL (get_status)
  4. fetch_metrics (if supported -> L4, else L3)
  5. delete (guaranteed cleanup in finally + pending_cleanups fallback)
  6. save evidence manifest in MinIO

Handles schema drift, demotion, alerts, and Dev.to honest draft unpublishing.
"""
from __future__ import annotations
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, BackgroundTasks, Header
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from api.database import get_db
from api.services import job_manager
from api.schemas.job import JobResponse
from api.schemas.connector import Connection, DestinationRef, Rendition
from api.middleware.logging_mw import get_logger

log = get_logger("routers.certify")
router = APIRouter(prefix="/api/v1", tags=["Certification"])

CERT_TITLE = "[IncuBrix Certification Test] Please ignore — will be deleted"
CERT_BODY = (
    "This is an automated certification test post from IncuBrix. "
    "It will be deleted within 10 minutes. Please ignore.\n\n"
    "Connector certification run — verifying: publish, status check, delete."
)


class CertifyRequest(BaseModel):
    destination_id: str
    connection: Connection
    callback_url: Optional[str] = None


async def _run_certification(
    job_id: str,
    request: CertifyRequest,
    db_url: str,
    idempotency_key: str,
):
    """Full certification loop with guaranteed cleanup and schema drift handling."""
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy import select
    from api.services.storage import upload_json, build_manifest, get_download_url
    from api.models.destination import Destination
    from api.models.certification import CertificationRecord
    from api.models.cleanup import PendingCleanup
    from api.models.alert import Alert
    from connectors.registry import get_connector

    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        start = time.monotonic()
        published_post_id = None
        dest_connector_key = ""
        cleanup_record_id = None

        cert = CertificationRecord(
            connector_key="",
            destination_id=request.destination_id,
            status="running",
        )
        db.add(cert)

        try:
            await job_manager.update_job(db, job_id, status="running", progress=5)

            result = await db.execute(
                select(Destination).where(Destination.id == request.destination_id)
            )
            dest = result.scalar_one_or_none()
            if not dest:
                raise ValueError(f"Destination '{request.destination_id}' not found.")

            dest_connector_key = dest.connector_key
            cert.connector_key = dest.connector_key
            connector = get_connector(dest.connector_key)
            if not connector:
                raise ValueError(f"Connector '{dest.connector_key}' not loaded.")

            # Phase 1.6: Inject destination's instance_config into connection
            request.connection.extra["instance"] = dest.instance_config or {}

            dest_ref = DestinationRef(
                destination_id=dest.id,
                platform_key=dest.platform_key,
                surface=dest.surface,
                instance_config=dest.instance_config or {},
            )
            rendition = Rendition(title=CERT_TITLE, body=CERT_BODY, is_ai_generated=False)

            # Step 1: Validate
            await job_manager.update_job(db, job_id, progress=15)
            validate_result = await connector.validate(rendition, dest_ref, request.connection)
            if not validate_result.ok:
                raise ValueError(f"Validation failed: {validate_result.violations}")

            # Step 2: Publish
            await job_manager.update_job(db, job_id, progress=30)
            publish_result = await connector.publish(
                rendition, dest_ref, request.connection, idempotency_key
            )
            published_post_id = publish_result.platform_post_id
            cert.publish_response = {
                "platform_post_id": publish_result.platform_post_id,
                "live_url": publish_result.live_url,
                "status": publish_result.status,
            }
            cert.live_url = publish_result.live_url

            # Record in pending_cleanups in case of abrupt failure
            cleanup = PendingCleanup(
                connector_key=dest.connector_key,
                platform_post_id=published_post_id,
                destination_id=dest.id,
                connection_data=request.connection.model_dump(),
                status="pending",
            )
            db.add(cleanup)
            await db.flush()
            cleanup_record_id = cleanup.id

            # Step 3: Get status (confirm live URL)
            await job_manager.update_job(db, job_id, progress=55)
            status_result = await connector.get_status(
                published_post_id, request.connection
            )
            cert.status_response = {
                "status": status_result.status,
                "live_url": status_result.live_url,
            }
            await db.flush()

            # Step 4: Try fetching metrics to qualify for L4
            metrics_fetched = False
            metrics_data = None
            try:
                metrics_res = await connector.fetch_metrics(published_post_id, request.connection)
                if metrics_res and metrics_res.metrics:
                    metrics_fetched = any(v > 0 for v in metrics_res.metrics.values())
                    metrics_data = metrics_res.metrics
            except Exception:
                metrics_fetched = False

            # Step 5: Delete (cleanup)
            await job_manager.update_job(db, job_id, progress=75)
            delete_result = await connector.delete(
                published_post_id, request.connection
            )
            cert.delete_response = {
                "deleted": delete_result.deleted,
                "deletion_method": "draft_unpublished_no_delete_api" if dest.connector_key == "devto" else "api_delete",
            }
            cert.post_deleted = delete_result.deleted
            if delete_result.deleted and cleanup_record_id:
                cleanup.status = "deleted"
            await db.flush()

            # Step 6: Evidence & Certification Level
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
                "metrics_supported": metrics_fetched,
                "metrics_sample": metrics_data,
                "manifest": manifest,
                "certified_at": datetime.now(timezone.utc).isoformat(),
            }
            evidence_path = f"evidence/{dest.connector_key}/{cert.id}/evidence.json"
            upload_json(evidence_path, evidence)
            cert.evidence_path = evidence_path

            manifest_path = f"jobs/{job_id}/manifest.json"
            upload_json(manifest_path, manifest)

            # Assign Level L4 if metrics fetched, else L3
            dest.level = "L4" if metrics_fetched else "L3"
            dest.last_certified_at = datetime.now(timezone.utc)
            cert.status = "passed"
            cert.completed_at = datetime.now(timezone.utc)

            result_url = get_download_url(evidence_path)
            await job_manager.update_job(
                db, job_id, status="succeeded", progress=100,
                result_url=result_url,
                result_data={
                    "certification_id": cert.id,
                    "level": dest.level,
                    "live_url": cert.live_url,
                    "evidence_url": result_url,
                },
            )
            await db.commit()
            log.info("certification_passed", connector=dest.connector_key, dest=dest.id, level=dest.level)

        except Exception as exc:
            log.error("certification_failed", job_id=job_id, error=str(exc))
            err_code = "PLATFORM_UNAVAILABLE"
            err_msg = str(exc)
            is_schema_drift = False

            detail = getattr(exc, "detail", None)
            if isinstance(detail, dict):
                inner_err = detail.get("error", {})
                err_code = inner_err.get("code", err_code)
                err_msg = inner_err.get("message", err_msg)
                if inner_err.get("details", {}).get("reason") == "SCHEMA_DRIFT":
                    is_schema_drift = True
            elif isinstance(detail, str):
                err_msg = detail

            # Demote destination on failure
            res_d = await db.execute(select(Destination).where(Destination.id == request.destination_id))
            dest = res_d.scalar_one_or_none()
            if dest:
                dest.level = "L0"
                # Write alert row
                alert = Alert(
                    destination_id=dest.id,
                    connector_key=dest.connector_key,
                    alert_type="SCHEMA_DRIFT" if is_schema_drift else "CERTIFICATION_FAILURE",
                    message=f"Destination '{dest.name}' certification failed: {err_msg}",
                    details={"job_id": job_id, "error_code": err_code, "schema_drift": is_schema_drift},
                )
                db.add(alert)

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
            # Phase 2.10: Guaranteed cleanup in finally block
            if published_post_id and (not cert.post_deleted):
                try:
                    conn_instance = get_connector(dest_connector_key)
                    if conn_instance:
                        del_res = await conn_instance.delete(published_post_id, request.connection)
                        if del_res.deleted and cleanup_record_id:
                            async with session_factory() as cleanup_db:
                                cl = await cleanup_db.get(PendingCleanup, cleanup_record_id)
                                if cl:
                                    cl.status = "deleted"
                                    await cleanup_db.commit()
                        log.info("finally_cleanup_success", post_id=published_post_id)
                except Exception as clean_err:
                    log.warning("finally_cleanup_failed", post_id=published_post_id, error=str(clean_err))

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
    """Start a certification run. Returns 202 + job_id."""
    job = await job_manager.create_job(db, "certify", request.callback_url)
    await db.commit()

    from api.config import settings
    background_tasks.add_task(_run_certification, job.id, request, settings.DATABASE_URL, idempotency_key)

    return JobResponse(job_id=job.id)
