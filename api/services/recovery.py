"""
Startup recovery and cleanup janitor service — Phase 2.1 & Phase 2.10.

1. recover_stuck_jobs:
   Checks for jobs in 'queued' or 'running' for > 10 minutes.
   If the idempotency record already has a platform_post_id -> mark succeeded.
   If not -> mark failed with PLATFORM_UNAVAILABLE, details.outcome='unknown'.
   NEVER blindly re-post.

2. run_cleanup_janitor:
   Periodically cleans up test posts from pending_cleanups that are > 10 minutes old.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone, timedelta
from sqlalchemy import select

from api.database import async_session
from api.models.job import Job
from api.models.idempotency import IdempotencyRecord
from api.models.cleanup import PendingCleanup
from api.middleware.logging_mw import get_logger
from connectors.registry import get_connector
from api.schemas.connector import Connection

log = get_logger("services.recovery")


async def recover_stuck_jobs():
    """Recover jobs abandoned due to server restarts."""
    log.info("running_startup_job_recovery")
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)

    try:
        async with async_session() as db:
            result = await db.execute(
                select(Job).where(
                    Job.status.in_(["queued", "running"]),
                    Job.created_at <= cutoff,
                )
            )
            stuck_jobs = result.scalars().all()

            for job in stuck_jobs:
                # Find matching idempotency record
                idem_res = await db.execute(
                    select(IdempotencyRecord).where(IdempotencyRecord.job_id == job.id)
                )
                idem = idem_res.scalar_one_or_none()

                if idem and idem.platform_post_id:
                    job.status = "succeeded"
                    job.progress = 100
                    job.result_data = idem.response_data or {"platform_post_id": idem.platform_post_id}
                    log.info("recovered_stuck_job_as_succeeded", job_id=job.id, platform_post_id=idem.platform_post_id)
                else:
                    job.status = "failed"
                    job.error_code = "PLATFORM_UNAVAILABLE"
                    job.error_message = "Server restarted during job execution; state unknown."
                    job.result_data = {"outcome": "unknown", "recovered": True}
                    log.warning("recovered_stuck_job_as_failed", job_id=job.id)

            await db.commit()
    except Exception as exc:
        log.error("startup_job_recovery_error", error=str(exc))


async def run_cleanup_janitor(interval_seconds: int = 60):
    """Background janitor loop that deletes abandoned certification posts older than 10 minutes."""
    log.info("cleanup_janitor_started")
    while True:
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
            async with async_session() as db:
                result = await db.execute(
                    select(PendingCleanup).where(
                        PendingCleanup.status == "pending",
                        PendingCleanup.created_at <= cutoff,
                    )
                )
                pending = result.scalars().all()

                for item in pending:
                    item.attempts += 1
                    connector = get_connector(item.connector_key)
                    if not connector:
                        continue

                    conn = Connection(**(item.connection_data or {}))
                    try:
                        res = await connector.delete(item.platform_post_id, conn)
                        if res.deleted:
                            item.status = "deleted"
                            log.info("janitor_cleaned_post", id=item.id, post_id=item.platform_post_id)
                        elif item.attempts >= 3:
                            item.status = "failed"
                    except Exception as e:
                        log.warning("janitor_delete_error", post_id=item.platform_post_id, error=str(e))
                        if item.attempts >= 3:
                            item.status = "failed"

                await db.commit()
        except Exception as exc:
            log.error("cleanup_janitor_loop_error", error=str(exc))

        await asyncio.sleep(interval_seconds)
