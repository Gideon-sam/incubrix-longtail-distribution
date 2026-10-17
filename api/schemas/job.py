"""
Job schemas — request/response for background job polling.
Integration Standard #3: anything slower than 2s returns 202 + job_id.
"""
from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel


class JobResponse(BaseModel):
    """Returned on 202 Accepted — client polls this job_id."""
    job_id: str


class JobStatusResponse(BaseModel):
    """GET /api/v1/jobs/{job_id} — status + progress + result."""
    job_id: str
    status: str      # queued | running | succeeded | failed
    progress: int    # 0–100
    result_url: Optional[str] = None
    result_data: Optional[dict[str, Any]] = None
    error: Optional[dict[str, Any]] = None
