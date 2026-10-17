"""
Job manager — creates, updates, and queries background jobs.

Integration Standard #3: POST returns 202 + job_id,
GET /api/v1/jobs/{job_id} returns status/progress/result.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Optional, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.job import Job
from api.middleware.logging_mw import get_logger

log = get_logger("services.job_manager")


async def create_job(
    db: AsyncSession,
    job_type: str,
    callback_url: Optional[str] = None,
) -> Job:
    """Create a new job in 'queued' status. Returns the Job object."""
    job = Job(
        id=str(uuid.uuid4()),
        job_type=job_type,
        status="queued",
        progress=0,
        callback_url=callback_url,
    )
    db.add(job)
    await db.flush()  # Get the ID without committing
    log.info("job_created", job_id=job.id, job_type=job_type)
    return job


async def update_job(
    db: AsyncSession,
    job_id: str,
    status: Optional[str] = None,
    progress: Optional[int] = None,
    result_url: Optional[str] = None,
    result_data: Optional[dict[str, Any]] = None,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
) -> Optional[Job]:
    """Update a job's status, progress, or results."""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        return None

    if status:
        job.status = status
    if progress is not None:
        job.progress = progress
    if result_url:
        job.result_url = result_url
    if result_data:
        job.result_data = result_data
    if error_code:
        job.error_code = error_code
    if error_message:
        job.error_message = error_message

    job.updated_at = datetime.now(timezone.utc)
    await db.flush()
    log.info("job_updated", job_id=job_id, status=status, progress=progress)
    return job


async def get_job(db: AsyncSession, job_id: str) -> Optional[Job]:
    """Fetch a job by ID."""
    result = await db.execute(select(Job).where(Job.id == job_id))
    return result.scalar_one_or_none()
