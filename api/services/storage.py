"""
MinIO storage service — Integration Standard #7.

Handles uploading/downloading files to S3-compatible storage.
Outputs (evidence, manifests, assist packs) saved to MinIO and
returned as download links.

In SIMULATION_MODE or when MinIO is unreachable, operations degrade
gracefully — paths are returned without throwing exceptions.
"""
from __future__ import annotations
import json
import io
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from api.config import settings
from api.middleware.logging_mw import get_logger

log = get_logger("services.storage")

# Lazy-initialized MinIO client
_client: Optional[Any] = None
_minio_available: bool = True


def get_minio_client():
    """Get or create the MinIO client singleton. Returns None if MinIO unavailable."""
    global _client, _minio_available
    if not _minio_available:
        return None
    if _client is not None:
        return _client
    try:
        from minio import Minio
        from minio.error import S3Error
        client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        # Ensure bucket exists
        try:
            if not client.bucket_exists(settings.MINIO_BUCKET):
                client.make_bucket(settings.MINIO_BUCKET)
                log.info("minio_bucket_created", bucket=settings.MINIO_BUCKET)
        except S3Error as e:
            log.error("minio_bucket_error", error=str(e))
        _client = client
    except Exception as e:
        log.warning("minio_unavailable", error=str(e))
        _minio_available = False
        return None
    return _client


def upload_json(path: str, data: dict[str, Any]) -> str:
    """Upload a JSON object to MinIO. Returns the object path. No-op if MinIO is down."""
    client = get_minio_client()
    if client is None:
        log.warning("minio_skip_upload", path=path, reason="MinIO not available")
        return path
    try:
        from minio.error import S3Error
        content = json.dumps(data, indent=2, default=str).encode("utf-8")
        client.put_object(
            settings.MINIO_BUCKET,
            path,
            io.BytesIO(content),
            length=len(content),
            content_type="application/json",
        )
        log.info("file_uploaded", path=path, size=len(content))
    except Exception as e:
        log.warning("minio_upload_failed", path=path, error=str(e))
    return path


def upload_file(path: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """Upload raw bytes to MinIO. Returns the object path. No-op if MinIO is down."""
    client = get_minio_client()
    if client is None:
        log.warning("minio_skip_upload", path=path, reason="MinIO not available")
        return path
    try:
        client.put_object(
            settings.MINIO_BUCKET,
            path,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        log.info("file_uploaded", path=path, size=len(data))
    except Exception as e:
        log.warning("minio_upload_failed", path=path, error=str(e))
    return path


def get_download_url(path: str, expires_hours: int = 24) -> str:
    """Generate a presigned download URL. Returns a fallback path if MinIO is down."""
    client = get_minio_client()
    if client is None:
        return f"minio://{settings.MINIO_BUCKET}/{path}"
    try:
        from minio.error import S3Error
        url = client.presigned_get_object(
            settings.MINIO_BUCKET,
            path,
            expires=timedelta(hours=expires_hours),
        )
        return url
    except Exception as e:
        log.error("presigned_url_error", path=path, error=str(e))
        return f"minio://{settings.MINIO_BUCKET}/{path}"


def build_manifest(
    job_type: str,
    connector_key: str = "",
    timings: dict[str, float] | None = None,
    warnings: list[str] | None = None,
    ai_generated: bool = False,
) -> dict:
    """
    Build a result manifest (Integration Standard #9).

    Every result includes: models/providers used, versions, settings,
    timings, cost estimate, warnings, licence info, AI-generated flag.
    """
    return {
        "job_type": job_type,
        "service_version": settings.SERVICE_VERSION,
        "connector_key": connector_key,
        "llm_provider": settings.LLM_PROVIDER,
        "simulation_mode": settings.SIMULATION_MODE,
        "ai_generated": ai_generated,
        "timings": timings or {},
        "cost_estimate": {"currency": "USD", "amount": 0.0},
        "warnings": warnings or [],
        "licence": "All outputs commercially usable",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
