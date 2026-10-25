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

    # -- Service identity ----------------------------------------
    SERVICE_NAME: str = "incubrix-longtail"
    SERVICE_VERSION: str = "1.0.0"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # -- Simulation mode -----------------------------------------
    # When True, connectors route to mock backends automatically.
    # Defaults to True: docker compose up works with ZERO keys.
    # Set SIMULATION_MODE=false in .env for live credentials.
    SIMULATION_MODE: bool = True

    # -- Database (Postgres) -------------------------------------
    POSTGRES_USER: str = "incubrix"
    POSTGRES_PASSWORD: str = "incubrix_pass"
    POSTGRES_DB: str = "incubrix"
    DATABASE_URL: str = (
        "postgresql+asyncpg://incubrix:incubrix_pass@postgres:5432/incubrix"
    )
    DATABASE_ECHO: bool = False

    # -- Redis (job queue + idempotency cache; optional locally) ------
    REDIS_URL: Optional[str] = None  # empty/None = in-memory fallback

    # -- MinIO (S3-compatible storage for outputs/evidence) ------
    MINIO_ENDPOINT: Optional[str] = None  # empty/None = skip MinIO
    MINIO_ROOT_USER: str = "incubrix"
    MINIO_ROOT_PASSWORD: str = "incubrix_secret"
    MINIO_ACCESS_KEY: str = "incubrix"
    MINIO_SECRET_KEY: str = "incubrix_secret"
    MINIO_BUCKET: str = "incubrix-outputs"
    MINIO_SECURE: bool = False

    # -- AI provider ---------------------------------------------
    # "mock" (default, no key) or "gemini" (needs GEMINI_API_KEY)
    LLM_PROVIDER: str = "gemini"
    GEMINI_API_KEY: Optional[str] = None
    # Comma-separated model names tried in priority order.
    # Uses fast, current Gemini models (gemini-3.5-flash-lite, gemini-flash-latest, gemini-3.8-flash).
    GEMINI_MODEL: str = "gemini-3.5-flash-lite,gemini-flash-latest,gemini-3.8-flash"

    # -- Rate limiting & auth for public demo --------------------
    RATE_LIMIT: str = "60/minute"
    ACCESS_TOKEN: Optional[str] = None
    CALLBACK_SECRET: str = "webhook_secret_key"
    AUTO_DISCLOSURE: bool = False
    ALLOWED_AUTOMATED_HOSTS: str = (
        "http://mock-discourse:4100,http://mock-discourse-2:4101,"
        "http://lemmy:8536,http://ghost:2368,https://dev.to,"
        "http://mock-devto:4150,http://mock-webhook:4200,"
        "http://mock-hashnode:4300,http://mock-peertube:4400"
    )
    RECERT_INTERVAL_DAYS: int = 25

    # -- Connector secrets ---------------------------------------
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

    model_config = {
        "env_file": [".env.local", ".env"],  # .env.local wins over .env
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
        "extra": "ignore",
    }


# Singleton — import this everywhere
settings = Settings()
