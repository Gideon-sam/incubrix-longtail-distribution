"""
Regression tests - real DB session (SQLite via test.db), no external services.

Step 3:
  - FrequencyCapRule counts simulated posts toward the cap (rules_engine fix)
  - normalize_url canonical transforms and error cases (catalogue step 2)
"""
from __future__ import annotations
import os
import uuid
import pytest
import pytest_asyncio

os.environ.setdefault("SIMULATION_MODE", "true")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/99")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")

from api.database import async_session, init_db
from api.models.destination import Destination
from api.models.job import Job
from api.services.rules_engine import FrequencyCapRule
from api.routers.catalogue import normalize_url
from api.schemas.connector import Rendition


@pytest_asyncio.fixture(autouse=True, scope="module")
async def _init_schema():
    await init_db()


def _r(**kw) -> Rendition:
    d = dict(title="T", body="B", tags=[], canonical_url=None,
             is_ai_generated=False, metadata={})
    d.update(kw)
    return Rendition(**d)


def _d(**kw) -> Destination:
    d = dict(
        id=str(uuid.uuid4()), name="Test", url="http://example.com",
        platform_key="discourse", connector_key="discourse", surface="topic",
        frequency_cap="1/week", self_promo_allowed=True, link_policy="allowed",
        disclosure_required=False, automation_allowed=True, status="active",
    )
    d.update(kw)
    return Destination(**d)


# ------------------------------------------------------------------ freq-cap

@pytest.mark.asyncio
async def test_freq_cap_sim_post_counts():
    """sim-tagged platform_post_id must count toward cap after step-1 fix."""
    async with async_session() as db:
        dest = _d(frequency_cap="1/week")
        job = Job(
            job_type="publish",
            status="succeeded",
            result_data={
                "destination_id": dest.id,
                "platform_post_id": "discourse-sim-abcd1234",
            },
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)

        res = await FrequencyCapRule().check(_r(), dest, db)

        assert res is not None, "cap must fire even for sim posts"
        assert res["code"] == "DEST_RULE_FREQUENCY_CAP"
        assert "reschedule_at" in res["details"]

        await db.delete(job)
        await db.commit()


@pytest.mark.asyncio
async def test_freq_cap_under_limit_returns_none():
    """No prior jobs -> cap rule returns None."""
    async with async_session() as db:
        assert await FrequencyCapRule().check(_r(), _d(frequency_cap="2/week"), db) is None


@pytest.mark.asyncio
async def test_freq_cap_ignores_other_destination():
    """Job for dest B must not count against dest A."""
    async with async_session() as db:
        a = _d(frequency_cap="1/week")
        b = _d(frequency_cap="1/week")
        job = Job(
            job_type="publish",
            status="succeeded",
            result_data={
                "destination_id": b.id,
                "platform_post_id": "discourse-sim-99999999",
            },
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)

        assert await FrequencyCapRule().check(_r(), a, db) is None

        await db.delete(job)
        await db.commit()


# ------------------------------------------------------------------ normalize_url

@pytest.mark.parametrize("a,b", [
    ("https://Example.com/",          "https://example.com"),
    ("HTTPS://EXAMPLE.COM",           "https://example.com"),
    ("https://www.example.com/forum/","https://example.com/forum"),
])
def test_normalize_url_equivalences(a, b):
    assert normalize_url(a) == normalize_url(b) or normalize_url(a) == b


@pytest.mark.parametrize("url,expected", [
    ("https://example.com:443/path",         "https://example.com/path"),
    ("http://example.com:80/path",           "http://example.com/path"),
    ("https://example.com:8080/path",        "https://example.com:8080/path"),
    ("https://example.com/page#top",         "https://example.com/page"),
    ("https://example.com/search?q=test",    "https://example.com/search?q=test"),
])
def test_normalize_url_transforms(url, expected):
    assert normalize_url(url) == expected


@pytest.mark.parametrize("a,b", [
    ("https://example.com/forum",       "https://example.com/blog"),
    ("http://example.com/path",         "https://example.com/path"),
    ("https://example.com:8443/path",   "https://example.com/path"),
])
def test_normalize_url_differences(a, b):
    assert normalize_url(a) != normalize_url(b)


@pytest.mark.parametrize("bad_url", [
    "https://",
    "https:///path",
    "http://host:notaport/path",
])
def test_normalize_url_raises(bad_url):
    with pytest.raises(ValueError):
        normalize_url(bad_url)
