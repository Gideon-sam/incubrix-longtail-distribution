"""
Recertification scheduler — Outstanding level.

Runs as a background task on startup. Checks all destinations:
  - If last_certified_at is > 30 days ago → run re-certification
  - If certification fails → demote destination level (L3 → L2) and create alert

Runs every 6 hours. Can be triggered manually via POST /api/v1/admin/recertify.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from api.middleware.logging_mw import get_logger

log = get_logger("services.recertification")

RECERT_INTERVAL_DAYS = 30
CHECK_INTERVAL_HOURS = 6
_scheduler_running = False


async def check_and_recertify(db: AsyncSession) -> dict:
    """
    Find destinations due for recertification and run them.
    Returns a summary of what was done.
    """
    from api.models.destination import Destination
    from api.models.certification import CertificationRecord

    cutoff = datetime.now(timezone.utc) - timedelta(days=RECERT_INTERVAL_DAYS)

    # Find destinations certified > 30 days ago or never certified
    result = await db.execute(
        select(Destination).where(
            Destination.level.in_(["L3", "L4"]),
        )
    )
    destinations = result.scalars().all()

    due = []
    for dest in destinations:
        last = dest.last_certified_at
        if last is None or (last.tzinfo is None and last < cutoff.replace(tzinfo=None)):
            due.append(dest)
        elif last.tzinfo is not None and last < cutoff:
            due.append(dest)

    summary = {
        "checked": len(destinations),
        "due_for_recert": len(due),
        "recertified": 0,
        "demoted": 0,
        "alerts": [],
    }

    for dest in due:
        log.info("recert_due", destination_id=dest.id, connector=dest.connector_key)
        try:
            await _recertify_destination(dest, db)
            summary["recertified"] += 1
        except Exception as e:
            # Demotion: L3 → L2
            log.warning("recert_failed_demoting", destination_id=dest.id, error=str(e))
            old_level = dest.level
            dest.level = "L2"
            await db.flush()
            alert = {
                "destination_id": dest.id,
                "name": dest.name,
                "old_level": old_level,
                "new_level": "L2",
                "reason": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            summary["demoted"] += 1
            summary["alerts"].append(alert)
            # Log alert as structured event (replaces ticket system)
            log.error(
                "destination_demoted",
                destination_id=dest.id,
                name=dest.name,
                old_level=old_level,
                new_level="L2",
                reason=str(e),
            )

    await db.commit()
    log.info("recert_cycle_complete", **{k: v for k, v in summary.items() if k != "alerts"})
    return summary


async def _recertify_destination(dest, db: AsyncSession):
    """Run a mini certification check on a destination."""
    from connectors.registry import get_connector
    from api.schemas.connector import (
        Rendition, DestinationRef, Connection
    )

    connector = get_connector(dest.connector_key)
    if not connector:
        raise ValueError(f"Connector '{dest.connector_key}' not found.")

    dest_ref = DestinationRef(
        destination_id=dest.id,
        platform_key=dest.platform_key,
        surface=dest.surface,
        instance_config=dest.instance_config or {},
    )
    rendition = Rendition(
        title="[IncuBrix Recert] Automated health check — will be deleted",
        body="This is an automated recertification test. It will be deleted immediately.",
        is_ai_generated=False,
    )
    connection = Connection()

    # Validate only (no actual post during scheduler to avoid spam)
    validate_result = await connector.validate(rendition, dest_ref, connection)
    if not validate_result.ok:
        raise ValueError(f"Validation failed: {validate_result.violations}")

    # Update last_certified_at to now
    dest.last_certified_at = datetime.now(timezone.utc)
    log.info("recert_passed", destination_id=dest.id)


async def run_scheduler(db_url: str):
    """
    Background scheduler loop — checks every 6 hours.
    Starts automatically when the service starts.
    """
    global _scheduler_running
    if _scheduler_running:
        return
    _scheduler_running = True

    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    log.info("recert_scheduler_started", interval_hours=CHECK_INTERVAL_HOURS)

    while True:
        try:
            async with session_factory() as db:
                summary = await check_and_recertify(db)
                log.info("recert_scheduler_cycle", **{k: v for k, v in summary.items() if k != "alerts"})
        except Exception as e:
            log.error("recert_scheduler_error", error=str(e))

        await asyncio.sleep(CHECK_INTERVAL_HOURS * 3600)
