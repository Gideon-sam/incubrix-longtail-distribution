"""
Idempotency service — Must-Have #6 and Integration Standard #4.

Postgres is the source of truth (unique constraint).
Redis is an optional fast-path cache.

Rules:
- Same key + same body → return same job_id immediately (no duplicate work)
- Same key + different body → return 409 error
- Intent recorded BEFORE calling the platform
- platform_post_id saved as soon as the platform returns it
- Atomic: unique constraint prevents two concurrent identical requests both proceeding
"""
from __future__ import annotations
import hashlib
import json
from typing import Optional, Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.idempotency import IdempotencyRecord
from api.middleware.logging_mw import get_logger

log = get_logger("services.idempotency")


def _hash_body(body: dict[str, Any]) -> str:
    """Stable SHA-256 hash of a request body for comparison."""
    canonical = json.dumps(body, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


async def check_idempotency(
    db: AsyncSession,
    idempotency_key: str,
    connector_key: str,
    destination_id: str,
    request_body: dict[str, Any],
) -> tuple[Optional[str], Optional[dict]]:
    """
    Check if this request has been seen before.

    Returns:
      (None, None)                → First time, proceed
      (job_id, response_data)     → Duplicate, return cached response
      raises ValueError           → Same key but different body
    """
    body_hash = _hash_body(request_body)

    # Look up existing record in Postgres
    result = await db.execute(
        select(IdempotencyRecord).where(
            IdempotencyRecord.idempotency_key == idempotency_key,
            IdempotencyRecord.connector_key == connector_key,
            IdempotencyRecord.destination_id == destination_id,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        if existing.body_hash != body_hash:
            # Same key, different body — this is an error per spec
            raise ValueError(
                f"Idempotency key '{idempotency_key}' was previously used with "
                "a different request body. Use a new key for a new request."
            )
        # Exact duplicate — return cached response
        log.info(
            "idempotency_duplicate",
            key=idempotency_key,
            job_id=existing.job_id,
        )
        return existing.job_id, existing.response_data

    return None, None


async def record_intent(
    db: AsyncSession,
    idempotency_key: str,
    connector_key: str,
    destination_id: str,
    request_body: dict[str, Any],
    job_id: str,
) -> Optional[IdempotencyRecord]:
    """
    Record intent BEFORE calling the platform.

    Uses the Postgres unique constraint as the atomic lock.
    If a concurrent request with the same key arrives, the second
    INSERT will fail with IntegrityError — handled by the caller.
    """
    body_hash = _hash_body(request_body)

    record = IdempotencyRecord(
        idempotency_key=idempotency_key,
        connector_key=connector_key,
        destination_id=destination_id,
        body_hash=body_hash,
        job_id=job_id,
        status="pending",
    )

    try:
        db.add(record)
        await db.flush()
        log.info(
            "idempotency_intent_recorded",
            key=idempotency_key,
            job_id=job_id,
        )
        return record
    except IntegrityError:
        await db.rollback()
        # Concurrent request won the race — look up the winner
        log.warning("idempotency_race_lost", key=idempotency_key)
        return None


async def save_result(
    db: AsyncSession,
    idempotency_key: str,
    connector_key: str,
    destination_id: str,
    platform_post_id: Optional[str],
    response_data: dict[str, Any],
):
    """Save the platform post ID and result as soon as they are known."""
    result = await db.execute(
        select(IdempotencyRecord).where(
            IdempotencyRecord.idempotency_key == idempotency_key,
            IdempotencyRecord.connector_key == connector_key,
            IdempotencyRecord.destination_id == destination_id,
        )
    )
    record = result.scalar_one_or_none()
    if record:
        record.platform_post_id = platform_post_id
        record.response_data = response_data
        record.status = "completed"
        await db.flush()
        log.info(
            "idempotency_result_saved",
            key=idempotency_key,
            platform_post_id=platform_post_id,
        )


async def check_cached_response(
    db: AsyncSession,
    idempotency_key: str,
    scope: str,
    target_id: str,
    request_body: dict[str, Any],
) -> tuple[bool, Optional[dict]]:
    """
    Check if a response is already cached for this idempotency key.
    Returns (is_duplicate, cached_response_data).
    Raises ValueError if same key was used with a different request body.
    """
    dest_key = target_id[:36] if target_id else "default"
    scope_key = scope[:50]
    body_hash = _hash_body(request_body)

    result = await db.execute(
        select(IdempotencyRecord).where(
            IdempotencyRecord.idempotency_key == idempotency_key,
            IdempotencyRecord.connector_key == scope_key,
            IdempotencyRecord.destination_id == dest_key,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        if existing.body_hash != body_hash:
            raise ValueError(
                f"Idempotency key '{idempotency_key}' was previously used with a different request body."
            )
        return True, existing.response_data
    return False, None


async def store_cached_response(
    db: AsyncSession,
    idempotency_key: str,
    scope: str,
    target_id: str,
    request_body: dict[str, Any],
    response_data: dict[str, Any],
):
    """Store cached response for an idempotent operation."""
    import uuid
    dest_key = target_id[:36] if target_id else "default"
    scope_key = scope[:50]
    body_hash = _hash_body(request_body)

    record = IdempotencyRecord(
        idempotency_key=idempotency_key,
        connector_key=scope_key,
        destination_id=dest_key,
        body_hash=body_hash,
        job_id=str(uuid.uuid4()),
        status="completed",
        response_data=response_data,
    )
    try:
        db.add(record)
        await db.flush()
    except IntegrityError:
        await db.rollback()

