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
from app.models.demo_lead import DemoLead, new_unsubscribe_token
from app.models.demo_origin import DemoOrigin
from app.models.organization import Organization
from app.models.settings import SystemSetting
from app.models.user import User

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


async def find_resumable_session(
    db: AsyncSession, ip: str | None, fallback_hours: int,
) -> tuple[Organization, User] | None:
    """Die noch laufende Demo-Sitzung dieser Adresse — oder None.

    Gegenstück zur Karenzzeit: wer die Demo gestartet hat und danach den Tab
    schließt, den Rechner wechselt oder den Browserspeicher leert, steht sonst
    vor der Sperre, obwohl *seine eigene* Sitzung noch läuft. Statt einer
    Absage bekommt er sie zurück.

    Die IP ist dabei derselbe Schlüssel, den die Karenzzeit ohnehin verwendet:
    Innerhalb des Fensters gehört genau eine Sitzung zu einer Adresse. Hinter
    einem gemeinsamen Anschluss (Büro-NAT, Mobilfunk-CGNAT) landen mehrere
    Besucher damit in derselben Demo — bislang bekam der zweite gar keine, die
    gemeinsame Wegwerf-Umgebung ist das kleinere Übel. Wer echte Trennung
    braucht, stellt den Anschluss über die Allowlist frei; dann wird ohnehin
    jedes Mal frisch angelegt.

    Gibt die jüngste noch gültige Sitzung samt Demo-Benutzer zurück; abgelaufene
    Organisationen und solche, deren Benutzer die Aufräumroutine bereits gelöscht
    oder ein Superadmin stillgelegt hat, zählen nicht — ein Token darauf wäre
    beim ersten Aufruf wieder ungültig.
    """
    if not ip:
        return None
    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(Organization, User)
            .join(User, User.id == Organization.owner_id)
            .where(
                Organization.is_demo.is_(True),
                Organization.demo_created_ip == ip,
            )
            .order_by(Organization.created_at.desc())
        )
    ).all()
    for org, user in rows:
        if not user.is_demo or not user.is_active:
            continue
        if _as_utc(effective_expiry(org, fallback_hours)) > now:
            return org, user
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


# ── Nachfrage-Mail nach Sitzungsende (an/aus) ─────────────────────────────────

DEMO_FOLLOWUP_ENABLED_KEY = "demo.followup_enabled"


async def get_demo_followup_setting(db: AsyncSession) -> str | None:
    """Rohwert aus der DB ("true"/"false") oder None, wenn nichts gesetzt ist."""
    value = await _get_setting(db, DEMO_FOLLOWUP_ENABLED_KEY)
    return value if value in ("true", "false") else None


async def is_demo_followup_enabled(db: AsyncSession) -> bool:
    """Effektiver Zustand: DB-Einstellung schlägt DEMO_FOLLOWUP_ENABLED."""
    db_value = await get_demo_followup_setting(db)
    if db_value is not None:
        return db_value == "true"
    return settings.demo_followup_enabled


async def set_demo_followup_enabled(db: AsyncSession, enabled: bool) -> None:
    await _upsert_setting(db, DEMO_FOLLOWUP_ENABLED_KEY, "true" if enabled else "false")
    await db.commit()


# ── Kontaktdaten der Interessenten (demo_leads) ───────────────────────────────

# Nach so vielen vergeblichen Versuchen wird die Adresse in Ruhe gelassen. Ohne
# Obergrenze liefe der Retention-Job bei einem dauerhaft unzustellbaren
# Postfach stündlich in denselben Fehler.
MAX_FOLLOWUP_ATTEMPTS = 3


def lead_display_name(lead: DemoLead) -> str:
    """Anrede für die Nachfrage-Mail — leer, wenn kein Name angegeben wurde."""
    return " ".join(p for p in (lead.first_name, lead.last_name) if p)


async def is_email_suppressed(db: AsyncSession, email: str) -> bool:
    """Ob diese Adresse dem Nachfragen widersprochen hat.

    Der Widerspruch hängt an der Adresse, nicht an der einzelnen Sitzung: Wer
    einmal abbestellt hat, bekommt auch nach einer späteren Demo keine Mail
    mehr.
    """
    row = (
        await db.execute(
            select(DemoLead.id)
            .where(DemoLead.email == email, DemoLead.unsubscribed_at.is_not(None))
            .limit(1)
        )
    ).first()
    return row is not None


async def record_lead(
    db: AsyncSession,
    *,
    email: str,
    first_name: str | None,
    last_name: str | None,
    org_id: uuid.UUID,
    org_slug: str,
    session_expires_at: datetime,
) -> DemoLead:
    """Kontaktangabe zu einer neu angelegten Demo-Sitzung festhalten.

    Ein bestehender Widerspruch derselben Adresse wird dabei übernommen — sonst
    hebelte ein zweiter Demo-Start die Abmeldung aus.
    """
    lead = DemoLead(
        id=uuid.uuid4(),
        email=email,
        first_name=first_name,
        last_name=last_name,
        org_id=org_id,
        org_slug=org_slug,
        session_expires_at=session_expires_at,
        unsubscribe_token=new_unsubscribe_token(),
    )
    if await is_email_suppressed(db, email):
        lead.unsubscribed_at = datetime.now(timezone.utc)
    db.add(lead)
    await db.flush()
    return lead


async def update_lead_for_org(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    email: str,
    first_name: str | None,
    last_name: str | None,
    session_expires_at: datetime,
) -> DemoLead | None:
    """Kontaktangabe einer fortgesetzten Sitzung auf den neuesten Stand bringen.

    Wer seine Sitzung fortsetzt, füllt das Formular erneut aus — meist mit
    denselben Angaben, manchmal mit der korrigierten Adresse. Die letzte
    Angabe gewinnt; existiert noch keine Zeile (Sitzung von vor dieser
    Funktion), wird eine angelegt.
    """
    lead = (
        await db.execute(
            select(DemoLead).where(DemoLead.org_id == org_id).order_by(DemoLead.created_at.desc())
        )
    ).scalars().first()
    if lead is None:
        return None
    lead.email = email
    lead.first_name = first_name
    lead.last_name = last_name
    lead.session_expires_at = session_expires_at
    if lead.unsubscribed_at is None and await is_email_suppressed(db, email):
        lead.unsubscribed_at = datetime.now(timezone.utc)
    return lead


async def sync_lead_expiry(
    db: AsyncSession, org_id: uuid.UUID, session_expires_at: datetime
) -> None:
    """Den gespiegelten Ablaufzeitpunkt nachziehen.

    Nötig, wenn der Superadmin eine Sitzung verlängert oder vorzeitig beendet:
    Die Nachfrage-Mail hängt an diesem Zeitpunkt, nicht an der Org (die ist
    beim Versand in der Regel schon gelöscht).
    """
    leads = (
        await db.execute(select(DemoLead).where(DemoLead.org_id == org_id))
    ).scalars().all()
    for lead in leads:
        lead.session_expires_at = session_expires_at


async def due_followups(db: AsyncSession, *, limit: int = 50) -> list[DemoLead]:
    """Kontakte, deren Sitzung abgelaufen ist und die noch keine Mail bekamen."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(DemoLead)
        .where(
            DemoLead.followup_sent_at.is_(None),
            DemoLead.unsubscribed_at.is_(None),
            DemoLead.session_expires_at <= now,
            DemoLead.followup_attempts < MAX_FOLLOWUP_ATTEMPTS,
        )
        .order_by(DemoLead.session_expires_at)
        .limit(limit)
    )
    return list(result.scalars().all())


async def unsubscribe_by_token(db: AsyncSession, token: str) -> bool:
    """Widerspruch über den Link aus der Mail. True, wenn das Token passte.

    Vermerkt wird auf allen Zeilen derselben Adresse — der Widerspruch gilt der
    Person, nicht der einzelnen Sitzung.
    """
    lead = (
        await db.execute(select(DemoLead).where(DemoLead.unsubscribe_token == token))
    ).scalar_one_or_none()
    if lead is None:
        return False
    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(select(DemoLead).where(DemoLead.email == lead.email))
    ).scalars().all()
    for row in rows:
        if row.unsubscribed_at is None:
            row.unsubscribed_at = now
    await db.commit()
    return True


async def purge_old_leads(db: AsyncSession, max_age_days: int) -> int:
    """Kontaktangaben löschen, die älter als die Aufbewahrungsfrist sind."""
    if max_age_days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    result = await db.execute(delete(DemoLead).where(DemoLead.created_at < cutoff))
    return result.rowcount or 0
