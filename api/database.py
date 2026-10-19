"""
Async database engine and session factory.

Uses SQLAlchemy 2.0 async API with asyncpg driver (Postgres) or aiosqlite (tests).
Supports Postgres advisory locks during schema initialization for concurrent safety.
"""
from __future__ import annotations
from typing import AsyncGenerator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from api.config import settings

_is_sqlite = settings.DATABASE_URL.startswith("sqlite")

if _is_sqlite:
    from sqlalchemy.pool import StaticPool
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=settings.DATABASE_ECHO,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
else:
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=settings.DATABASE_ECHO,
        pool_size=20,
        max_overflow=10,
    )

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields a DB session, auto-closes on exit."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db():
    """Create all tables with Postgres advisory lock for safe concurrent startup."""
    import api.models  # noqa: F401
    async with engine.begin() as conn:
        if not _is_sqlite and conn.dialect.name == "postgresql":
            try:
                await conn.execute(text("SELECT pg_advisory_xact_lock(123456789)"))
            except Exception:
                pass
        await conn.run_sync(Base.metadata.create_all)


async def close_db():
    """Dispose engine on shutdown."""
    await engine.dispose()
