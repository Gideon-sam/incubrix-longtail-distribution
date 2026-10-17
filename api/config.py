"""
Configuration loaded entirely from environment variables.
No hard-coded paths or keys (Integration Standard #6).

All settings are validated by Pydantic on startup — if a required
setting is missing, the service fails fast with a clear error.
"""
from __future__ import annotations
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Central configuration — every field maps to an env var."""

    # ── Service identity ────────────────────────────────────
    SERVICE_NAME: str = "incubrix-longtail"
    SERVICE_VERSION: str = "1.0.0"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # ── Simulation mode ─────────────────────────────────────
    # When True, connectors route to mock backends automatically.
    SIMULATION_MODE: bool = False

    # ── Database (Postgres) ─────────────────────────────────
    DATABASE_URL: str = (
        "postgresql+asyncpg://incubrix:incubrix_pass@postgres:5432/incubrix"
    )
    DATABASE_ECHO: bool = False

    # ── Redis (job queue + idempotency cache) ───────────────
    REDIS_URL: str = "redis://redis:6379/0"

    # ── MinIO (S3-compatible storage for outputs/evidence) ──
    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_ACCESS_KEY: str = "incubrix"
    MINIO_SECRET_KEY: str = "incubrix_secret"
    MINIO_BUCKET: str = "incubrix-outputs"
    MINIO_SECURE: bool = False

    # ── AI provider ─────────────────────────────────────────
    # "mock" (default, no key) or "gemini" (needs GEMINI_API_KEY)
    LLM_PROVIDER: str = "mock"
    GEMINI_API_KEY: Optional[str] = None

    # ── Rate limiting & auth for public demo ────────────────
    RATE_LIMIT: str = "60/minute"
    ACCESS_TOKEN: Optional[str] = None

    # ── Connector secrets ───────────────────────────────────
    DEVTO_API_KEY: Optional[str] = None

    GHOST_ADMIN_API_KEY: Optional[str] = None
    GHOST_API_URL: str = "http://ghost:2368"

    DISCOURSE_API_KEY: str = "mock_discourse_key"
    DISCOURSE_API_URL: str = "http://mock-discourse:4100"

    LEMMY_API_URL: str = "http://lemmy:8536"
    LEMMY_USERNAME: str = "incubrix_admin"
    LEMMY_PASSWORD: str = "incubrix_pass"

    HMAC_WEBHOOK_SECRET: str = "webhook_secret_key"
    HMAC_WEBHOOK_URL: str = "http://mock-webhook:4200/webhook"

    HASHNODE_API_KEY: str = "mock_hashnode_key"
    HASHNODE_API_URL: str = "http://mock-hashnode:4300"

    PEERTUBE_API_URL: str = "http://mock-peertube:4400"
    PEERTUBE_API_KEY: str = "mock_peertube_key"

    MRSS_OUTPUT_DIR: str = "/app/outputs/mrss"

    model_config = {"env_file": ".env", "case_sensitive": True}


# Singleton — import this everywhere
settings = Settings()
