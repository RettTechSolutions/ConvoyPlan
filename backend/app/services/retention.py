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
from app.models.organization import Organization
from app.models.share_link import ConvoyShareLink
from app.models.user import User
from app.models.vehicle_position import VehiclePosition
from app.services import audit
from app.services import demo as demo_svc

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


async def purge_demo_sessions(db: AsyncSession, max_age_hours: int) -> int:
    """Delete ephemeral demo orgs and their owners that have expired.

    A session expires at demo_expires_at (settable/extendable by the superadmin);
    legacy rows without that column value fall back to created_at + TTL.

    Order matters: convoys must be deleted before their org (FK with SET NULL
    would orphan them), org before its owner_user (FK with NO ACTION)."""
    from sqlalchemy import or_, select as _select
    from app.models.convoy import Convoy

    now = datetime.now(timezone.utc)
    cutoff = _cutoff(hours=max_age_hours)
    rows = (await db.execute(
        _select(Organization.id, Organization.owner_id)
        .where(
            Organization.is_demo.is_(True),
            or_(
                Organization.demo_expires_at < now,
                Organization.demo_expires_at.is_(None) & (Organization.created_at < cutoff),
            ),
        )
    )).all()
    if not rows:
        return 0

    org_ids = [r.id for r in rows]
    user_ids = [r.owner_id for r in rows]

    # Convoys have organization_id FK with SET NULL — delete them explicitly so
    # demo data is fully removed instead of becoming orphaned.
    await db.execute(delete(Convoy).where(Convoy.organization_id.in_(org_ids)))
    # Deleting the org cascades UserOrganization memberships.
    await db.execute(delete(Organization).where(Organization.id.in_(org_ids)))
    # Deleting the user cascades their vehicles and any remaining memberships.
    await db.execute(delete(User).where(User.id.in_(user_ids)))

    return len(org_ids)


async def run_all(db: AsyncSession) -> dict[str, int]:
    """Run every retention purge, commit, and record an audit entry if anything
    was deleted. Returns the per-category deletion counts."""
    counts = {
        "positions": await purge_stale_positions(db, settings.retention_positions_hours),
        "audit_logs": await purge_old_audit_logs(db, settings.retention_audit_days),
        "share_links": await purge_expired_share_links(db, settings.retention_share_links_days),
        # Always purge expired demo sessions — the demo mode can be toggled at
        # runtime (admin panel), so gating on the env flag would leave demo orgs
        # behind after the mode is switched off. The hours act only as fallback
        # TTL for legacy rows without demo_expires_at.
        "demo_sessions": await purge_demo_sessions(db, await demo_svc.get_demo_session_hours(db)),
        # Die IP-Sperre der Demo hält nur die Karenzzeit; danach ist die
        # gespeicherte Adresse zwecklos und wird gelöscht.
        "demo_origins": await demo_svc.purge_expired_origins(
            db, await demo_svc.get_demo_ip_cooldown_hours(db)
        ),
    }
    await db.commit()
    if any(counts.values()):
        await audit.record(db, "retention.purge", detail=counts)
    logger.info("Retention purge complete: %s", counts)
    return counts
