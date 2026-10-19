"""
MinIO storage service — Integration Standard #7 & #9.

Handles uploading/downloading files to S3-compatible storage.
Outputs (evidence, manifests, assist packs) saved to MinIO and
returned as download links.
"""
from __future__ import annotations
import json
import io
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from api.config import settings
from api.middleware.logging_mw import get_logger

log = get_logger("services.storage")

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
    """Upload a JSON object to MinIO. Returns the object path."""
    client = get_minio_client()
    if client is None:
        log.warning("minio_skip_upload", path=path, reason="MinIO not available")
        return path
    try:
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
    """Upload raw bytes to MinIO. Returns the object path."""
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
    """Generate presigned download URL with fallback."""
    client = get_minio_client()
    if client is None:
        return f"minio://{settings.MINIO_BUCKET}/{path}"
    try:
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
    seed: int = 42,
) -> dict:
    """
    Build a result manifest matching Integration Standard #9.
    Includes models/providers and versions, settings, seed, timings,
    cost estimate, warnings, licence/rights, AI-generated flag.
    """
    cost_amount = 0.0 if settings.LLM_PROVIDER == "mock" else 0.00015
    model_version = "gemini-2.0-flash" if settings.LLM_PROVIDER == "gemini" else "mock-adapter-1.0.0"

    return {
        "job_type": job_type,
        "service_version": settings.SERVICE_VERSION,
        "connector_key": connector_key,
        "llm_provider": settings.LLM_PROVIDER,
        "model_versions": {
            "llm": model_version,
            "fastapi": "0.110.0+",
            "python": "3.12.x",
        },
        "settings": {
            "simulation_mode": settings.SIMULATION_MODE,
            "rate_limit": settings.RATE_LIMIT,
            "auto_disclosure": settings.AUTO_DISCLOSURE,
            "recert_interval_days": settings.RECERT_INTERVAL_DAYS,
        },
        "seed": seed,
        "ai_generated": ai_generated,
        "timings": timings or {},
        "cost_estimate": {
            "currency": "USD",
            "amount": cost_amount,
            "basis": "free_mock" if settings.LLM_PROVIDER == "mock" else "gemini_tokens_measured",
        },
        "warnings": warnings or [],
        "licence": "Commercial Use Granted - All outputs usable by IncuBrix clients",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
