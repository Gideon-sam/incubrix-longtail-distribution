"""
Shared test fixtures — no API keys required.

SIMULATION_MODE=true and LLM_PROVIDER=mock so all tests run
offline. The TestClient uses FastAPI's async test client.
"""
import os
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# Force simulation + mock AI before importing the app
os.environ.setdefault("SIMULATION_MODE", "true")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/99")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")


@pytest.fixture(scope="session", autouse=True)
def _setup_env():
    """Ensure test env vars are set before any module imports the app."""
    pass


@pytest_asyncio.fixture
async def client():
    """Async HTTP client for testing the FastAPI app."""
    from api.main import app
    from api.database import init_db
    from connectors.registry import discover_connectors

    await init_db()
    discover_connectors()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
