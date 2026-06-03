"""Automatic data-retention purges (ISO 27001 A.8.15 / DSGVO Art. 5(1)(e)).

Pure, side-effect-light functions plus a `run_all` orchestrator. Triggered by
the `retention` cron container via `python -m app.jobs.retention`.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.audit_log import AuditLog
from app.models.share_link import ConvoyShareLink
from app.models.vehicle_position import VehiclePosition
from app.services import audit

logger = logging.getLogger(__name__)


def _cutoff(*, hours: int = 0, days: int = 0) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=hours, days=days)


async def purge_stale_positions(db: AsyncSession, max_age_hours: int) -> int:
    """Delete live positions older than the retention window."""
    result = await db.execute(
        delete(VehiclePosition).where(VehiclePosition.recorded_at < _cutoff(hours=max_age_hours))
    )
    return result.rowcount or 0


async def purge_old_audit_logs(db: AsyncSession, max_age_days: int) -> int:
    """Delete audit-log entries older than the retention window."""
    result = await db.execute(
        delete(AuditLog).where(AuditLog.created_at < _cutoff(days=max_age_days))
    )
    return result.rowcount or 0


async def purge_expired_share_links(db: AsyncSession, grace_days: int) -> int:
    """Delete revoked share links past the grace period."""
    result = await db.execute(
        delete(ConvoyShareLink).where(
            ConvoyShareLink.revoked.is_(True),
            ConvoyShareLink.created_at < _cutoff(days=grace_days),
        )
    )
    return result.rowcount or 0


async def run_all(db: AsyncSession) -> dict[str, int]:
    """Run every retention purge, commit, and record an audit entry if anything
    was deleted. Returns the per-category deletion counts."""
    counts = {
        "positions": await purge_stale_positions(db, settings.retention_positions_hours),
        "audit_logs": await purge_old_audit_logs(db, settings.retention_audit_days),
        "share_links": await purge_expired_share_links(db, settings.retention_share_links_days),
    }
    await db.commit()
    if any(counts.values()):
        await audit.record(db, "retention.purge", detail=counts)
    logger.info("Retention purge complete: %s", counts)
    return counts
