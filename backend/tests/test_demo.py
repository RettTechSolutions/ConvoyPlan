"""Tests for the runtime demo-mode toggle (admin panel > env var fallback)
and the superadmin demo-session management endpoints."""

import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError
from unittest.mock import AsyncMock, MagicMock

from app.api.deps import get_db, require_superadmin
from app.config import settings
from app.main import app
from app.models.demo_origin import DemoOrigin
from app.models.organization import Organization
from app.models.user import User
from app.services import demo


def _db_returning(value: str | None) -> AsyncMock:
    """Mock db whose SystemSetting lookup returns a row with *value* (or no row)."""
    db = AsyncMock()
    result = MagicMock()
    if value is None:
        result.scalar_one_or_none.return_value = None
    else:
        setting = MagicMock()
        setting.value = value
        result.scalar_one_or_none.return_value = setting
    db.execute.return_value = result
    return db


@pytest.mark.asyncio
async def test_db_setting_overrides_env(monkeypatch):
    monkeypatch.setattr("app.services.demo.settings.demo_enabled", False)
    assert await demo.is_demo_enabled(_db_returning("true")) is True

    monkeypatch.setattr("app.services.demo.settings.demo_enabled", True)
    assert await demo.is_demo_enabled(_db_returning("false")) is False


@pytest.mark.asyncio
async def test_env_is_fallback_when_db_unset(monkeypatch):
    monkeypatch.setattr("app.services.demo.settings.demo_enabled", True)
    assert await demo.is_demo_enabled(_db_returning(None)) is True

    monkeypatch.setattr("app.services.demo.settings.demo_enabled", False)
    assert await demo.is_demo_enabled(_db_returning(None)) is False


@pytest.mark.asyncio
async def test_garbage_db_value_falls_back_to_env(monkeypatch):
    monkeypatch.setattr("app.services.demo.settings.demo_enabled", False)
    assert await demo.is_demo_enabled(_db_returning("yes please")) is False


@pytest.mark.asyncio
async def test_session_hours_db_overrides_env(monkeypatch):
    monkeypatch.setattr("app.services.demo.settings.demo_session_hours", 24)
    assert await demo.get_demo_session_hours(_db_returning("72")) == 72
    assert await demo.get_demo_session_hours(_db_returning(None)) == 24
    # invalid or out-of-bounds values fall back to env
    assert await demo.get_demo_session_hours(_db_returning("banana")) == 24
    assert await demo.get_demo_session_hours(_db_returning("0")) == 24
    assert await demo.get_demo_session_hours(_db_returning("99999")) == 24


@pytest.mark.asyncio
async def test_set_demo_enabled_upserts():
    db = _db_returning(None)
    await demo.set_demo_enabled(db, True)
    db.add.assert_called_once()
    assert db.add.call_args[0][0].value == "true"
    db.commit.assert_awaited()

    db = _db_returning("true")
    await demo.set_demo_enabled(db, False)
    db.add.assert_not_called()
    db.commit.assert_awaited()


# ── Demo-session management (superadmin) ─────────────────────────────────────


def _superadmin():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.is_superadmin = True
    u.email = "admin@example.com"
    return u


@pytest.mark.asyncio
async def test_terminate_demo_session_404_when_missing():
    app.dependency_overrides[require_superadmin] = _superadmin

    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result

    async def _db():
        yield db
    app.dependency_overrides[get_db] = _db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete(f"/api/admin/demo-sessions/{uuid.uuid4()}")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_demo_sessions_empty():
    app.dependency_overrides[require_superadmin] = _superadmin

    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute.return_value = result

    async def _db():
        yield db
    app.dependency_overrides[get_db] = _db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/admin/demo-sessions")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json() == []


# ── IP-Karenzzeit ─────────────────────────────────────────────────────────────

def _db_with_origin(origin: DemoOrigin | None) -> AsyncMock:
    """Mock-DB, deren DemoOrigin-Abfrage *origin* (oder nichts) liefert.

    Dasselbe Ergebnisobjekt bedient beide Abfragen von `claim_ip`: die
    Allowlist (`scalars().all()` → leer) und den Sperreintrag
    (`scalar_one_or_none()`).
    """
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = origin
    result.scalars.return_value.all.return_value = []
    db.execute.return_value = result
    return db


def _origin(*, hours_ago: float, sessions: int = 1) -> DemoOrigin:
    stamp = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return DemoOrigin(ip="203.0.113.7", first_created_at=stamp, last_created_at=stamp,
                      sessions=sessions)


@pytest.mark.asyncio
async def test_first_demo_from_ip_is_allowed_and_recorded():
    db = _db_with_origin(None)
    assert await demo.claim_ip(db, "203.0.113.7", 24) is None
    db.add.assert_called_once()
    assert db.add.call_args.args[0].ip == "203.0.113.7"


@pytest.mark.asyncio
async def test_second_demo_within_cooldown_is_blocked():
    db = _db_with_origin(_origin(hours_ago=1))
    retry_after = await demo.claim_ip(db, "203.0.113.7", 24)
    # 23 Stunden Restzeit (auf die Sekunde genau, deshalb ein Toleranzfenster).
    assert retry_after is not None
    assert 23 * 3600 - 5 <= retry_after <= 23 * 3600 + 5
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_demo_allowed_again_after_cooldown_expired():
    origin = _origin(hours_ago=25, sessions=1)
    db = _db_with_origin(origin)
    assert await demo.claim_ip(db, "203.0.113.7", 24) is None
    # Kein neuer Datensatz, aber ein aktualisierter Zeitstempel und Zähler.
    db.add.assert_not_called()
    assert origin.sessions == 2
    assert (datetime.now(timezone.utc) - origin.last_created_at).total_seconds() < 5


@pytest.mark.asyncio
async def test_cooldown_zero_disables_the_lock():
    db = _db_with_origin(_origin(hours_ago=0))
    assert await demo.claim_ip(db, "203.0.113.7", 0) is None
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_without_client_ip_there_is_nothing_to_lock():
    db = _db_with_origin(None)
    assert await demo.claim_ip(db, None, 24) is None
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_concurrent_claims_lose_the_race_instead_of_slipping_through():
    db = _db_with_origin(None)
    db.flush.side_effect = IntegrityError("insert", {}, Exception("duplicate key"))
    retry_after = await demo.claim_ip(db, "203.0.113.7", 24)
    assert retry_after == 24 * 3600
    db.rollback.assert_awaited()


@pytest.mark.asyncio
async def test_demo_session_endpoint_answers_429_during_cooldown(monkeypatch):
    """Der Endpunkt lehnt die zweite Demo derselben IP mit Retry-After ab."""
    monkeypatch.setattr("app.services.demo.settings.demo_enabled", True)
    monkeypatch.setattr("app.services.demo.settings.demo_ip_cooldown_hours", 24)

    unset = MagicMock(); unset.scalar_one_or_none.return_value = None
    empty = MagicMock(); empty.scalars.return_value.all.return_value = []
    origin_row = MagicMock(); origin_row.scalar_one_or_none.return_value = _origin(hours_ago=2)
    no_session = MagicMock(); no_session.all.return_value = []
    db = AsyncMock()
    # 1) demo.enabled  2) demo.ip_cooldown_hours  3) Allowlist  4) demo_origins
    # 5) demo.session_hours  6) laufende Sitzung dieser IP (keine)
    db.execute.side_effect = [unset, unset, empty, origin_row, unset, no_session]

    async def _db():
        yield db
    app.dependency_overrides[get_db] = _db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/auth/demo-session")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 429
    retry_after = int(resp.headers["Retry-After"])
    assert retry_after > 0
    detail = resp.json()["detail"]
    assert "24 Stunden" in detail["message"]
    # Der genaue Zeitpunkt der Wiederfreigabe, damit die Startseite ihn in der
    # Zeitzone des Besuchers anzeigen kann statt nur „in 22 Stunden".
    retry_at = datetime.fromisoformat(detail["retry_at"])
    assert retry_at.tzinfo is not None
    expected = datetime.now(timezone.utc) + timedelta(seconds=retry_after)
    assert abs((retry_at - expected).total_seconds()) < 5


@pytest.mark.asyncio
async def test_demo_session_endpoint_names_the_reason_when_switched_off(monkeypatch):
    """Bei abgeschalteter Demo nennt die Absage den Grund — die Startseite zeigt
    diesen Text unverändert an, „später nochmal versuchen" wäre dort falsch."""
    monkeypatch.setattr("app.services.demo.settings.demo_enabled", False)

    unset = MagicMock(); unset.scalar_one_or_none.return_value = None
    db = AsyncMock()
    db.execute.return_value = unset

    async def _db():
        yield db
    app.dependency_overrides[get_db] = _db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/auth/demo-session")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 503
    assert "abgeschaltet" in resp.json()["detail"]


# ── Wiedereinstieg in die laufende Sitzung ────────────────────────────────────

def _demo_pair(*, expires_in_hours: float, is_demo_user: bool = True, ip: str = "203.0.113.7"):
    """Demo-Organisation samt Besitzer, deren Frist in *expires_in_hours* endet."""
    uid = uuid.uuid4()
    org = Organization(
        id=uuid.uuid4(), name="Demo ABC123", slug="demo-abc123", owner_id=uid, is_demo=True,
        demo_expires_at=datetime.now(timezone.utc) + timedelta(hours=expires_in_hours),
        demo_created_ip=ip,
    )
    # is_active/is_demo explizit: Spaltendefaults greifen erst beim INSERT, ein
    # frisch konstruiertes Objekt hätte hier None stehen.
    user = User(id=uid, email=f"demo-{uid.hex}@demo.local", hashed_password="x",
                is_demo=is_demo_user, is_active=True)
    return org, user


def _db_with_sessions(*pairs) -> AsyncMock:
    """Mock-DB, deren Sitzungsabfrage die übergebenen (Org, User)-Paare liefert."""
    db = AsyncMock()
    result = MagicMock()
    result.all.return_value = list(pairs)
    db.execute.return_value = result
    return db


@pytest.mark.asyncio
async def test_running_session_of_this_ip_is_resumable():
    org, user = _demo_pair(expires_in_hours=1.5)
    found = await demo.find_resumable_session(_db_with_sessions((org, user)), "203.0.113.7", 2)
    assert found is not None
    assert found[0].slug == "demo-abc123"


@pytest.mark.asyncio
async def test_expired_session_is_not_resumable():
    """Abgelaufen heißt abgelaufen — die Aufräumroutine hat die Daten schon im
    Zugriff, ein Token darauf wäre wertlos."""
    org, user = _demo_pair(expires_in_hours=-0.1)
    assert await demo.find_resumable_session(_db_with_sessions((org, user)), "203.0.113.7", 2) is None


@pytest.mark.asyncio
async def test_legacy_session_without_explicit_expiry_uses_the_configured_lifetime():
    org, user = _demo_pair(expires_in_hours=1)
    org.demo_expires_at = None
    org.created_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db = _db_with_sessions((org, user))
    # Noch innerhalb der 2-Stunden-Laufzeit …
    assert await demo.find_resumable_session(db, "203.0.113.7", 2) is not None
    # … aber nicht mehr innerhalb einer Stunde.
    assert await demo.find_resumable_session(db, "203.0.113.7", 1) is None


@pytest.mark.asyncio
async def test_a_non_demo_owner_is_never_resumed():
    org, user = _demo_pair(expires_in_hours=1, is_demo_user=False)
    assert await demo.find_resumable_session(_db_with_sessions((org, user)), "203.0.113.7", 2) is None


@pytest.mark.asyncio
async def test_a_deactivated_demo_user_is_not_resumed():
    """Ein Token darauf wäre beim ersten Aufruf wieder ungültig."""
    org, user = _demo_pair(expires_in_hours=1)
    user.is_active = False
    assert await demo.find_resumable_session(_db_with_sessions((org, user)), "203.0.113.7", 2) is None


@pytest.mark.asyncio
async def test_without_client_ip_there_is_nothing_to_resume():
    db = _db_with_sessions()
    assert await demo.find_resumable_session(db, None, 2) is None
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_demo_session_endpoint_resumes_instead_of_rejecting(monkeypatch):
    """Läuft die eigene Sitzung noch, führt der Demo-Knopf zurück in sie —
    die Karenzzeit soll niemanden aus seiner eigenen Demo aussperren."""
    monkeypatch.setattr("app.services.demo.settings.demo_enabled", True)
    monkeypatch.setattr("app.services.demo.settings.demo_ip_cooldown_hours", 24)
    monkeypatch.setattr("app.services.demo.settings.demo_session_hours", 2)

    org, user = _demo_pair(expires_in_hours=1.5)
    unset = MagicMock(); unset.scalar_one_or_none.return_value = None
    empty = MagicMock(); empty.scalars.return_value.all.return_value = []
    origin_row = MagicMock(); origin_row.scalar_one_or_none.return_value = _origin(hours_ago=2)
    session_row = MagicMock(); session_row.all.return_value = [(org, user)]
    db = AsyncMock()
    db.execute.side_effect = [unset, unset, empty, origin_row, unset, session_row]

    async def _db():
        yield db
    app.dependency_overrides[get_db] = _db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/auth/demo-session")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["resumed"] is True
    assert body["org_slug"] == "demo-abc123"
    assert body["expires_at"] == org.demo_expires_at.isoformat()
    # Das Token gehört zur bestehenden Sitzung, nicht zu einer neuen.
    payload = jwt.decode(body["access_token"], settings.jwt_secret,
                         algorithms=[settings.jwt_algorithm])
    assert payload["org_id"] == str(org.id)
    assert payload["sub"] == str(user.id)
    assert payload["is_demo"] is True


# ── Dauerhafte Ausnahmen (Allowlist) ──────────────────────────────────────────

def _db_with_allowlist(*patterns: str) -> AsyncMock:
    """Mock-DB, deren Allowlist-Abfrage *patterns* liefert."""
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = list(patterns)
    db.execute.return_value = result
    return db


def test_normalize_ip_pattern_accepts_addresses_and_networks():
    assert demo.normalize_ip_pattern("203.0.113.7") == "203.0.113.7"
    assert demo.normalize_ip_pattern("  203.0.113.7  ") == "203.0.113.7"
    # Einzeladresse mit /32 bleibt als Adresse stehen, nicht als Netz.
    assert demo.normalize_ip_pattern("203.0.113.7/32") == "203.0.113.7"
    assert demo.normalize_ip_pattern("203.0.113.0/24") == "203.0.113.0/24"
    # Hostbits werden verworfen, damit der Eintrag das bedeutet, was da steht.
    assert demo.normalize_ip_pattern("203.0.113.7/24") == "203.0.113.0/24"
    assert demo.normalize_ip_pattern("2001:db8::1") == "2001:db8::1"
    assert demo.normalize_ip_pattern("2001:db8::/32") == "2001:db8::/32"


def test_normalize_ip_pattern_rejects_nonsense_and_catch_all():
    for bad in ["", "   ", "kein Netz", "203.0.113.999", "203.0.113.0/33"]:
        with pytest.raises(ValueError):
            demo.normalize_ip_pattern(bad)
    # Ein Netz ohne Präfixlänge würde die Karenzzeit für alle abschalten —
    # dafür gibt es die Einstellung „Karenzzeit 0", nicht die Allowlist.
    with pytest.raises(ValueError):
        demo.normalize_ip_pattern("0.0.0.0/0")
    with pytest.raises(ValueError):
        demo.normalize_ip_pattern("::/0")


@pytest.mark.asyncio
async def test_allowlist_matches_single_address_and_network():
    assert await demo.is_ip_allowlisted(_db_with_allowlist("203.0.113.7"), "203.0.113.7") is True
    assert await demo.is_ip_allowlisted(_db_with_allowlist("203.0.113.7"), "203.0.113.8") is False
    net = _db_with_allowlist("203.0.113.0/24")
    assert await demo.is_ip_allowlisted(net, "203.0.113.200") is True
    assert await demo.is_ip_allowlisted(_db_with_allowlist("203.0.113.0/24"), "198.51.100.1") is False
    # Adressfamilien werden nicht verwechselt, und ein unbrauchbar gewordener
    # Eintrag darf den Demo-Start nicht zum Fehler machen.
    assert await demo.is_ip_allowlisted(_db_with_allowlist("2001:db8::/32"), "203.0.113.7") is False
    assert await demo.is_ip_allowlisted(_db_with_allowlist("Datenmüll"), "203.0.113.7") is False


@pytest.mark.asyncio
async def test_allowlisted_ip_is_never_blocked_and_leaves_no_trace():
    """Die Ausnahme greift vor der Sperre: kein 429 und kein Eintrag in
    demo_origins — die Adresse soll in der Sperrliste nicht auftauchen."""
    db = _db_with_allowlist("203.0.113.0/24")
    assert await demo.claim_ip(db, "203.0.113.7", 24) is None
    db.add.assert_not_called()
    # Nur die Allowlist wurde abgefragt, der Sperreintrag gar nicht erst.
    assert db.execute.await_count == 1


@pytest.mark.asyncio
async def test_adding_an_entry_lifts_the_running_lock():
    """Wer einen Anschluss freistellt, will ihn jetzt frei haben — nicht erst
    nach Ablauf der laufenden Karenzzeit."""
    db = AsyncMock()
    origins = MagicMock()
    origins.scalars.return_value.all.return_value = ["203.0.113.7", "203.0.113.9", "198.51.100.1"]
    db.execute.side_effect = [origins, MagicMock()]

    entry, released = await demo.add_ip_allowlist_entry(
        db, "203.0.113.7/24", note="Messe-WLAN", created_by="admin@example.com",
    )

    assert entry.pattern == "203.0.113.0/24"
    assert entry.note == "Messe-WLAN"
    # Beide Adressen aus dem Netz, die fremde nicht.
    assert released == 2
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_adding_a_known_entry_is_reported_as_duplicate():
    db = AsyncMock()
    db.flush.side_effect = IntegrityError("insert", {}, Exception("duplicate key"))
    with pytest.raises(demo.DuplicateAllowlistEntry):
        await demo.add_ip_allowlist_entry(db, "203.0.113.7")
    db.rollback.assert_awaited()


@pytest.mark.asyncio
async def test_removing_a_missing_entry_reports_nothing_removed():
    db = AsyncMock()
    db.get.return_value = None
    assert await demo.remove_ip_allowlist_entry(db, uuid.uuid4()) is None
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_allowlist_endpoint_rejects_a_pattern_that_is_not_an_address():
    app.dependency_overrides[require_superadmin] = _superadmin

    db = AsyncMock()

    async def _db():
        yield db
    app.dependency_overrides[get_db] = _db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/admin/demo-ip-allowlist", json={"pattern": "das ganze Internet"},
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 422
    db.add.assert_not_called()
