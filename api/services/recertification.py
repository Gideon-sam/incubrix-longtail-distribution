"""
Recertification scheduler — Phase 4.5 (Outstanding level).

- Runs before 30 days (RECERT_INTERVAL_DAYS=25, env-configurable)
- Postgres advisory lock prevents multiple workers from executing simultaneously
- Re-runs mini-certification (publish -> status -> delete) on owned destinations; validate-only for assisted/feed
- On failure: demotes destination to L0, writes Alert model row, and excludes from recommendations until re-certified.
"""
from __future__ import annotations
import asyncio
import time
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from api.config import settings
from api.middleware.logging_mw import get_logger
from api.models.alert import Alert
from api.models.destination import Destination
from connectors.registry import get_connector
from api.schemas.connector import Rendition, DestinationRef, Connection

log = get_logger("services.recertification")
_scheduler_running = False


async def check_and_recertify(db: AsyncSession) -> dict:
    """Find destinations due for recertification (<25 days) and re-certify with advisory lock."""
    # Try Postgres advisory lock to ensure single runner
    has_lock = False
    try:
        if db.bind and db.bind.dialect.name == "postgresql":
            lock_res = await db.execute(text("SELECT pg_try_advisory_lock(987654)"))
            has_lock = bool(lock_res.scalar())
            if not has_lock:
                log.info("recertification_cycle_skipped_lock_held_by_another_worker")
                return {"message": "Lock held by another worker.", "skipped": True}
    except Exception as e:
        log.warning("recertification_advisory_lock_error", error=str(e))

    try:
        interval_days = settings.RECERT_INTERVAL_DAYS
        cutoff = datetime.now(timezone.utc) - timedelta(days=interval_days)

        # Find L3/L4 destinations due for recertification
        result = await db.execute(
            select(Destination).where(
                Destination.level.in_(["L3", "L4"]),
                Destination.status != "revoked",
            )
        )
        destinations = result.scalars().all()

        due = []
        for dest in destinations:
            last = dest.last_certified_at
            if last is None:
                due.append(dest)
            elif last.tzinfo is None and last < cutoff.replace(tzinfo=None):
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
                log.warning("recert_failed_demoting", destination_id=dest.id, error=str(e))
                old_level = dest.level
                dest.level = "L0"
                dest.last_certified_at = None

                alert = Alert(
                    destination_id=dest.id,
                    connector_key=dest.connector_key,
                    alert_type="RECERT_FAILURE",
                    message=f"Recertification failed for {dest.name}: {str(e)}",
                    details={"old_level": old_level, "new_level": "L0", "error": str(e)},
                )
                db.add(alert)
                summary["demoted"] += 1
                summary["alerts"].append({
                    "destination_id": dest.id,
                    "name": dest.name,
                    "old_level": old_level,
                    "new_level": "L0",
                    "reason": str(e),
                })

        await db.commit()
        log.info("recert_cycle_complete", **{k: v for k, v in summary.items() if k != "alerts"})
        return summary

    finally:
        if has_lock:
            try:
                await db.execute(text("SELECT pg_advisory_unlock(987654)"))
            except Exception:
                pass


async def _recertify_destination(dest: Destination, db: AsyncSession):
    """Run real mini-certification (publish -> status -> delete) on owned destinations; validate only for assisted/feed."""
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
        title="[IncuBrix Recert] Automated verification — will be deleted",
        body="This is an automated recertification test post from IncuBrix. Verifying connection and schema.",
        is_ai_generated=False,
    )

    connection = Connection()
    if dest.instance_config:
        connection.extra["instance"] = dest.instance_config

    # Validate step
    val_res = await connector.validate(rendition, dest_ref, connection)
    if not val_res.ok:
        raise ValueError(f"Validation failed: {val_res.violations}")

    # If assisted or feed connector, validate is sufficient
    if dest.connector_key in ("assisted", "mrss"):
        dest.last_certified_at = datetime.now(timezone.utc)
        return

    # For native connectors: full publish -> status -> delete cycle
    idem_key = f"recert-{dest.id[:8]}-{int(time.time())}"
    pub_res = await connector.publish(rendition, dest_ref, connection, idem_key)
    post_id = pub_res.platform_post_id

    try:
        status_res = await connector.get_status(post_id, connection)
        if status_res.status not in ("published", "draft"):
            raise ValueError(f"Recert status returned: {status_res.status}")
    finally:
        # Always delete
        await connector.delete(post_id, connection)

    dest.last_certified_at = datetime.now(timezone.utc)
    log.info("recert_passed", destination_id=dest.id)


async def run_scheduler(db_url: str):
    """Background scheduler loop."""
    global _scheduler_running
    if _scheduler_running:
        return
    _scheduler_running = True

    try:
        engine = create_async_engine(db_url)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
    except Exception as e:
        log.error("recert_scheduler_engine_error", error=str(e))
        _scheduler_running = False
        return

    log.info("recert_scheduler_started", interval_hours=6)

    while True:
        try:
            async with session_factory() as db:
                summary = await check_and_recertify(db)
                if not summary.get("skipped"):
                    log.info("recert_scheduler_cycle", **{k: v for k, v in summary.items() if k != "alerts"})
        except Exception as e:
            log.error("recert_scheduler_error", error=str(e))

        await asyncio.sleep(6 * 3600)

