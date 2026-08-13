"""Runtime configuration for ephemeral demo sessions.

The superadmin can toggle the demo mode and adjust the session lifetime in the
admin panel; the values are stored in system_settings and take priority over
the DEMO_ENABLED / DEMO_SESSION_HOURS env vars (same pattern as the GitHub
token).
"""

import ipaddress
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.demo_ip_allowlist import DemoIpAllowlistEntry
from app.models.demo_origin import DemoOrigin
from app.models.organization import Organization
from app.models.settings import SystemSetting

DEMO_ENABLED_KEY = "demo.enabled"
DEMO_SESSION_HOURS_KEY = "demo.session_hours"
DEMO_IP_COOLDOWN_HOURS_KEY = "demo.ip_cooldown_hours"

# Bounds for the admin-configurable session lifetime (1 hour … 30 days).
MIN_SESSION_HOURS = 1
MAX_SESSION_HOURS = 720

# Bounds for the per-IP cooldown. 0 disables it entirely.
MIN_IP_COOLDOWN_HOURS = 0
MAX_IP_COOLDOWN_HOURS = 720


async def _get_setting(db: AsyncSession, key: str) -> str | None:
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
    setting = result.scalar_one_or_none()
    return setting.value if setting else None


async def _upsert_setting(db: AsyncSession, key: str, value: str) -> None:
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = value
    else:
        db.add(SystemSetting(key=key, value=value))


async def get_demo_enabled_setting(db: AsyncSession) -> str | None:
    """Return the raw DB value ("true"/"false") or None when unset."""
    value = await _get_setting(db, DEMO_ENABLED_KEY)
    return value if value in ("true", "false") else None


async def is_demo_enabled(db: AsyncSession) -> bool:
    """Effective demo state: DB setting wins, env var DEMO_ENABLED is the fallback."""
    db_value = await get_demo_enabled_setting(db)
    if db_value is not None:
        return db_value == "true"
    return settings.demo_enabled


async def set_demo_enabled(db: AsyncSession, enabled: bool) -> None:
    """Persist the demo toggle in system_settings."""
    await _upsert_setting(db, DEMO_ENABLED_KEY, "true" if enabled else "false")
    await db.commit()


async def get_demo_session_hours_setting(db: AsyncSession) -> int | None:
    """Return the DB-configured session lifetime, or None when unset/invalid."""
    value = await _get_setting(db, DEMO_SESSION_HOURS_KEY)
    if value is None:
        return None
    try:
        hours = int(value)
    except ValueError:
        return None
    return hours if MIN_SESSION_HOURS <= hours <= MAX_SESSION_HOURS else None


async def get_demo_session_hours(db: AsyncSession) -> int:
    """Effective session lifetime: DB setting wins, DEMO_SESSION_HOURS is the fallback."""
    db_value = await get_demo_session_hours_setting(db)
    return db_value if db_value is not None else settings.demo_session_hours


async def set_demo_session_hours(db: AsyncSession, hours: int) -> None:
    """Persist the session lifetime in system_settings (caller validates bounds)."""
    await _upsert_setting(db, DEMO_SESSION_HOURS_KEY, str(hours))
    await db.commit()


async def get_demo_ip_cooldown_hours_setting(db: AsyncSession) -> int | None:
    """Return the DB-configured per-IP cooldown, or None when unset/invalid."""
    value = await _get_setting(db, DEMO_IP_COOLDOWN_HOURS_KEY)
    if value is None:
        return None
    try:
        hours = int(value)
    except ValueError:
        return None
    return hours if MIN_IP_COOLDOWN_HOURS <= hours <= MAX_IP_COOLDOWN_HOURS else None


async def get_demo_ip_cooldown_hours(db: AsyncSession) -> int:
    """Effective per-IP cooldown: DB setting wins, DEMO_IP_COOLDOWN_HOURS is the fallback."""
    db_value = await get_demo_ip_cooldown_hours_setting(db)
    return db_value if db_value is not None else settings.demo_ip_cooldown_hours


async def set_demo_ip_cooldown_hours(db: AsyncSession, hours: int) -> None:
    """Persist the per-IP cooldown in system_settings (caller validates bounds)."""
    await _upsert_setting(db, DEMO_IP_COOLDOWN_HOURS_KEY, str(hours))
    await db.commit()


def effective_expiry(org: Organization, fallback_hours: int) -> datetime:
    """Expiry of a demo org: explicit demo_expires_at, or the legacy implicit TTL."""
    return org.demo_expires_at or (org.created_at + timedelta(hours=fallback_hours))


# ── Dauerhafte Ausnahmen (Allowlist) ──────────────────────────────────────────

class DuplicateAllowlistEntry(Exception):
    """Diese Adresse bzw. dieses Netz steht bereits auf der Liste."""


def normalize_ip_pattern(value: str) -> str:
    """Eingabe des Superadmins in die gespeicherte Schreibweise bringen.

    Einzeladressen bleiben wie sie sind (`203.0.113.7`), Netze werden auf ihre
    Netzadresse zurückgeführt (`203.0.113.7/24` → `203.0.113.0/24`) — sonst
    stünde in der Liste ein Eintrag, der etwas anderes bedeutet als das, was da
    steht. Wirft ValueError bei allem, was weder Adresse noch Netz ist.
    """
    network = ipaddress.ip_network(value.strip(), strict=False)
    if network.prefixlen == 0:
        # `0.0.0.0/0` bzw. `::/0` würde die Karenzzeit stillschweigend für alle
        # abschalten — dafür gibt es die Einstellung „Karenzzeit 0".
        raise ValueError("Ein Netz ohne Präfixlänge stellt alle Adressen frei")
    if network.prefixlen == network.max_prefixlen:
        return str(network.network_address)
    return str(network)


def _matches(pattern: str, ip: str) -> bool:
    """Ob *ip* von *pattern* (Einzeladresse oder Netz) abgedeckt ist."""
    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network(pattern, strict=False)
    except (TypeError, ValueError):
        # Unpassende Adressfamilie (IPv4 gegen IPv6-Netz) oder ein Eintrag, der
        # sich nicht mehr parsen lässt: deckt die Adresse nicht ab. Ein
        # kaputter Eintrag darf den Demo-Start nicht zum Fehler machen.
        return False


async def list_ip_allowlist(db: AsyncSession) -> list[DemoIpAllowlistEntry]:
    """Alle dauerhaften Ausnahmen, zuletzt angelegte zuerst."""
    result = await db.execute(
        select(DemoIpAllowlistEntry).order_by(DemoIpAllowlistEntry.created_at.desc())
    )
    return list(result.scalars().all())


async def is_ip_allowlisted(db: AsyncSession, ip: str) -> bool:
    """Ob *ip* dauerhaft von der Karenzzeit ausgenommen ist."""
    patterns = (await db.execute(select(DemoIpAllowlistEntry.pattern))).scalars().all()
    return any(_matches(pattern, ip) for pattern in patterns)


async def _release_matching_origins(db: AsyncSession, pattern: str) -> int:
    """Laufende Sperren löschen, die *pattern* abdeckt.

    Die IP steht als Text in der Tabelle, ein CIDR-Vergleich in SQL wäre also
    datenbankspezifisch (Postgres `inet`) — bei einer Zeile je gesperrter
    Adresse innerhalb der Karenzzeit ist der Abgleich in Python billiger als
    diese Bindung.
    """
    ips = (await db.execute(select(DemoOrigin.ip))).scalars().all()
    hits = [ip for ip in ips if _matches(pattern, ip)]
    if not hits:
        return 0
    await db.execute(delete(DemoOrigin).where(DemoOrigin.ip.in_(hits)))
    return len(hits)


async def add_ip_allowlist_entry(
    db: AsyncSession, pattern: str, *, note: str | None = None, created_by: str | None = None,
) -> tuple[DemoIpAllowlistEntry, int]:
    """Ausnahme anlegen und eine bereits laufende Sperre dafür sofort aufheben.

    Wer einen Anschluss freistellt, will ihn jetzt freigeschaltet haben und
    nicht erst nach Ablauf der laufenden Karenzzeit — deshalb der zweite
    Schritt. Gibt den Eintrag und die Zahl der dabei gelösten Sperren zurück.

    Wirft ValueError bei ungültiger Eingabe und DuplicateAllowlistEntry, wenn
    die Adresse bereits auf der Liste steht.
    """
    normalized = normalize_ip_pattern(pattern)
    entry = DemoIpAllowlistEntry(
        id=uuid.uuid4(), pattern=normalized, note=(note or None), created_by=created_by,
    )
    db.add(entry)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise DuplicateAllowlistEntry(normalized) from None
    released = await _release_matching_origins(db, normalized)
    await db.commit()
    return entry, released


async def remove_ip_allowlist_entry(db: AsyncSession, entry_id: uuid.UUID) -> str | None:
    """Ausnahme wieder entfernen. Gibt das entfernte Muster zurück (für das
    Audit-Log) oder None, wenn es den Eintrag nicht gibt."""
    entry = await db.get(DemoIpAllowlistEntry, entry_id)
    if entry is None:
        return None
    pattern = entry.pattern
    await db.delete(entry)
    await db.commit()
    return pattern


# ── Per-IP cooldown ───────────────────────────────────────────────────────────

def _as_utc(value: datetime) -> datetime:
    """DB values are UTC; SQLite (tests) hands them back naive."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


async def claim_ip(db: AsyncSession, ip: str | None, cooldown_hours: int) -> int | None:
    """Reserve the demo slot for *ip* — the gate in front of a new session.

    Returns the number of seconds left on the cooldown when the IP already
    started a session inside the window (caller answers 429), or None when the
    session may be created — in which case the attempt is recorded.

    The row is written before the demo org exists and stays behind after the
    org has been purged, so the cooldown holds for its full length no matter how
    short the session lifetime is. Without a resolvable client IP there is
    nothing to key on; those requests fall back to the in-process limiter.
    """
    if not ip or cooldown_hours <= 0:
        return None

    if await is_ip_allowlisted(db, ip):
        # Dauerhaft freigestellt (Firmenanschluss, Messe-WLAN): keine Sperre —
        # und auch kein Eintrag in demo_origins, damit die Adresse in der
        # Sperrliste des Admin-Portals gar nicht erst auftaucht.
        return None

    now = datetime.now(timezone.utc)
    existing = (
        await db.execute(select(DemoOrigin).where(DemoOrigin.ip == ip))
    ).scalar_one_or_none()

    if existing is not None:
        elapsed = (now - _as_utc(existing.last_created_at)).total_seconds()
        remaining = cooldown_hours * 3600 - elapsed
        if remaining > 0:
            return max(int(remaining) + 1, 1)
        existing.last_created_at = now
        existing.sessions = (existing.sessions or 0) + 1
        return None

    db.add(DemoOrigin(ip=ip, first_created_at=now, last_created_at=now, sessions=1))
    try:
        await db.flush()
    except IntegrityError:
        # Two requests from the same IP raced past the SELECT — the loser of the
        # insert is exactly the request the cooldown is meant to stop.
        await db.rollback()
        return cooldown_hours * 3600
    return None


async def release_ip(db: AsyncSession, ip: str) -> bool:
    """Lift the cooldown for a single IP (superadmin action). True when a row was
    removed — used when a legitimate visitor is blocked, e.g. a shared office
    address the whole team sits behind."""
    result = await db.execute(delete(DemoOrigin).where(DemoOrigin.ip == ip))
    await db.commit()
    return bool(result.rowcount)


async def list_ip_locks(db: AsyncSession, cooldown_hours: int) -> list[dict]:
    """Currently blocking IPs with the time left, newest first."""
    if cooldown_hours <= 0:
        return []
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=cooldown_hours)
    rows = (
        await db.execute(
            select(DemoOrigin)
            .where(DemoOrigin.last_created_at >= cutoff)
            .order_by(DemoOrigin.last_created_at.desc())
        )
    ).scalars().all()
    return [
        {
            "ip": row.ip,
            "last_created_at": _as_utc(row.last_created_at),
            "sessions": row.sessions or 0,
            "blocked_until": _as_utc(row.last_created_at) + timedelta(hours=cooldown_hours),
        }
        for row in rows
    ]


async def purge_expired_origins(db: AsyncSession, cooldown_hours: int) -> int:
    """Delete origin rows whose cooldown has run out — they carry no further
    meaning and the IP should not be kept longer than needed."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(cooldown_hours, 0))
    result = await db.execute(delete(DemoOrigin).where(DemoOrigin.last_created_at < cutoff))
    return result.rowcount or 0
