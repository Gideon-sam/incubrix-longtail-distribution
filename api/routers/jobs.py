"""
Jobs router — Integration Standard #3.

GET /api/v1/jobs/{job_id}
Returns: status (queued/running/succeeded/failed), progress 0-100, result links.
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.services.job_manager import get_job
from api.schemas.job import JobStatusResponse

router = APIRouter(prefix="/api/v1/jobs", tags=["Jobs"])


@router.get(
    "/{job_id}",
    response_model=JobStatusResponse,
    summary="Get background job status",
)
async def get_job_status(job_id: str, db: AsyncSession = Depends(get_db)):
    """
    Poll a background job by ID.
    Returns status, progress (0-100), and result links when complete.
    """
    job = await get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    error = None
    if job.status == "failed":
        error = {
            "code": job.error_code or "UNKNOWN_ERROR",
            "message": job.error_message or "Job failed.",
        }

    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        progress=job.progress,
        result_url=job.result_url,
        result_data=job.result_data,
        error=error,
    )
