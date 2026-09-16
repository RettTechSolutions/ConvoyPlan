"""Kontakterfassung beim Demo-Start und die Nachfrage-Mail nach Sitzungsende.

Die Kontaktzeile (`demo_leads`) überlebt die Demo-Org bewusst — der Versand
findet statt, wenn die Umgebung längst gelöscht ist. Diese Tests decken beide
Enden ab: was beim Start verlangt wird und was der Retention-Durchgang daraus
macht.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_db, require_superadmin
from app.main import app
from app.models.demo_lead import DemoLead
from app.services import demo, email as email_svc, retention


def _lead(**overrides) -> DemoLead:
    """Eine Kontaktzeile, wie sie der Versandjob vorfindet."""
    lead = DemoLead(
        id=uuid.uuid4(),
        email="interessent@example.org",
        first_name="Max",
        last_name="Mustermann",
        org_id=None,
        org_slug="demo-abc123",
        session_expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        unsubscribe_token="t" * 32,
    )
    lead.followup_attempts = 0
    lead.followup_sent_at = None
    lead.followup_error = None
    lead.unsubscribed_at = None
    for key, value in overrides.items():
        setattr(lead, key, value)
    return lead


# ── Beim Start: Adresse ist Pflicht ───────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"first_name": "Max"}, {"email": "keine-adresse"}])
async def test_demo_start_insists_on_a_usable_address(body):
    """Ohne brauchbare Adresse gibt es keine Sitzung — sie ist das einzige
    Merkmal, an dem sich Besucher auseinanderhalten und später erreichen
    lassen."""
    db = AsyncMock()

    async def _db():
        yield db
    app.dependency_overrides[get_db] = _db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/auth/demo-session", json=body)
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 422
    # Die Prüfung greift vor jedem Datenbankzugriff — kein halb angelegter Zustand.
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_name_stays_optional():
    """Der Name ist freiwillig: Pflichtfelder auf dem Weg in eine Demo kosten
    nur Abbrüche, die Adresse allein trägt Zuordnung und Nachfrage."""
    from app.api.routes.auth import DemoSessionRequest

    parsed = DemoSessionRequest(email="  Interessent@Example.ORG ")
    assert parsed.first_name is None and parsed.last_name is None
    # Adressen werden normalisiert, sonst wären Max@x.de und max@x.de zwei Leute.
    assert parsed.email == "interessent@example.org"


# ── Widerspruch schlägt auf neue Sitzungen durch ──────────────────────────────

@pytest.mark.asyncio
async def test_a_new_session_does_not_revive_a_previous_objection():
    """Wer abbestellt hat, bekommt auch nach einer zweiten Demo keine Mail."""
    db = AsyncMock()
    suppressed = MagicMock()
    suppressed.first.return_value = (uuid.uuid4(),)   # es gibt eine abbestellte Zeile
    db.execute.return_value = suppressed

    lead = await demo.record_lead(
        db, email="interessent@example.org", first_name=None, last_name=None,
        org_id=uuid.uuid4(), org_slug="demo-abc123",
        session_expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )

    assert lead.unsubscribed_at is not None
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_without_a_previous_objection_the_lead_is_mailable():
    db = AsyncMock()
    clean = MagicMock()
    clean.first.return_value = None
    db.execute.return_value = clean

    lead = await demo.record_lead(
        db, email="interessent@example.org", first_name="Max", last_name=None,
        org_id=uuid.uuid4(), org_slug="demo-abc123",
        session_expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )

    assert lead.unsubscribed_at is None
    assert lead.unsubscribe_token and len(lead.unsubscribe_token) >= 32


# ── Der Versandjob ────────────────────────────────────────────────────────────

def _mail_setup(monkeypatch, *, enabled=True, smtp=True):
    monkeypatch.setattr(
        "app.services.retention.demo_svc.is_demo_followup_enabled", AsyncMock(return_value=enabled)
    )
    monkeypatch.setattr(
        "app.services.retention.email_svc.is_smtp_configured", AsyncMock(return_value=smtp)
    )


@pytest.mark.asyncio
async def test_nothing_is_sent_while_the_switch_is_off(monkeypatch):
    _mail_setup(monkeypatch, enabled=False)
    sender = AsyncMock()
    monkeypatch.setattr("app.services.retention.email_svc.send_demo_followup_email", sender)

    assert await retention.send_due_demo_followups(AsyncMock()) == 0
    sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_without_smtp_the_attempt_is_not_even_counted(monkeypatch):
    """Sonst wären nach drei Durchgängen alle Adressen verbraucht, ohne dass je
    eine Mail möglich gewesen wäre."""
    _mail_setup(monkeypatch, smtp=False)
    lead = _lead()
    monkeypatch.setattr(
        "app.services.retention.demo_svc.due_followups", AsyncMock(return_value=[lead])
    )

    assert await retention.send_due_demo_followups(AsyncMock()) == 0
    assert lead.followup_attempts == 0


@pytest.mark.asyncio
async def test_a_sent_followup_is_marked_and_not_repeated(monkeypatch):
    _mail_setup(monkeypatch)
    lead = _lead()
    monkeypatch.setattr(
        "app.services.retention.demo_svc.due_followups", AsyncMock(return_value=[lead])
    )
    sender = AsyncMock()
    monkeypatch.setattr("app.services.retention.email_svc.send_demo_followup_email", sender)
    db = AsyncMock()

    assert await retention.send_due_demo_followups(db) == 1

    assert lead.followup_sent_at is not None
    assert lead.followup_error is None
    db.commit.assert_awaited()
    # Die Anrede kommt aus den angegebenen Namen, der Abmeldelink aus dem Token.
    kwargs = sender.await_args.kwargs
    assert kwargs["recipient_name"] == "Max Mustermann"
    assert lead.unsubscribe_token in kwargs["unsubscribe_url"]
    # Beim nächsten Durchgang taucht die Zeile nicht mehr auf (followup_sent_at).
    assert lead.followup_sent_at is not None


@pytest.mark.asyncio
async def test_one_dead_mailbox_does_not_stop_the_others(monkeypatch):
    _mail_setup(monkeypatch)
    broken = _lead(email="tot@example.org")
    fine = _lead(email="lebt@example.org")
    monkeypatch.setattr(
        "app.services.retention.demo_svc.due_followups", AsyncMock(return_value=[broken, fine])
    )

    async def _send(db, *, recipient_email, **kwargs):
        if recipient_email == "tot@example.org":
            raise RuntimeError("550 no such mailbox")

    monkeypatch.setattr("app.services.retention.email_svc.send_demo_followup_email", _send)

    assert await retention.send_due_demo_followups(AsyncMock()) == 1

    assert broken.followup_sent_at is None
    assert broken.followup_attempts == 1
    assert "550" in broken.followup_error
    assert fine.followup_sent_at is not None


@pytest.mark.asyncio
async def test_a_used_up_mailbox_is_left_alone():
    """`due_followups` filtert über die Versuchszahl — nach drei Fehlschlägen
    ruht die Adresse, statt den Job stündlich in denselben Fehler zu schicken."""
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute.return_value = result

    assert await demo.due_followups(db) == []
    # Die Bedingung steht in der Abfrage, nicht in einer Nachbearbeitung.
    query = str(db.execute.await_args[0][0])
    assert "followup_attempts" in query and "followup_sent_at IS NULL" in query


# ── Abmeldung ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unsubscribing_covers_every_session_of_that_address():
    db = AsyncMock()
    lead = _lead()
    other = _lead(email=lead.email, org_slug="demo-zzz999")
    found = MagicMock(); found.scalar_one_or_none.return_value = lead
    siblings = MagicMock(); siblings.scalars.return_value.all.return_value = [lead, other]
    db.execute.side_effect = [found, siblings]

    assert await demo.unsubscribe_by_token(db, lead.unsubscribe_token) is True
    assert lead.unsubscribed_at is not None
    assert other.unsubscribed_at is not None


@pytest.mark.asyncio
async def test_an_unknown_token_is_answered_with_404():
    db = AsyncMock()
    missing = MagicMock(); missing.scalar_one_or_none.return_value = None
    db.execute.return_value = missing

    async def _db():
        yield db
    app.dependency_overrides[get_db] = _db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/auth/demo-followup/unsubscribe", json={"token": "x" * 32}
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404


# ── Die Mail selbst ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_followup_asks_all_three_questions():
    """Inhalt der Mail: hat es funktioniert, ist etwas offen, wollen wir uns das
    gemeinsam ansehen — plus der Abmeldelink im Fußbereich."""
    db = AsyncMock()
    branding = MagicMock()
    branding.scalars.return_value.all.return_value = []   # Standard-Branding
    db.execute.return_value = branding

    subject, body = await email_svc._render_demo_followup_email_async(
        db, "Max Mustermann",
        unsubscribe_url="https://example.test/demo/abmelden?token=abc",
        contact_url="https://example.test/kontakt",
    )

    assert "ConvoyPlan" in subject
    assert "Hallo Max Mustermann" in body
    assert "funktioniert" in body and "offen geblieben" in body and "Session" in body
    assert "https://example.test/demo/abmelden?token=abc" in body
    assert "https://example.test/kontakt" in body


@pytest.mark.asyncio
async def test_a_visitor_without_a_name_is_greeted_without_one():
    db = AsyncMock()
    branding = MagicMock()
    branding.scalars.return_value.all.return_value = []
    db.execute.return_value = branding

    _, body = await email_svc._render_demo_followup_email_async(
        db, "", unsubscribe_url="https://example.test/u", contact_url="https://example.test/k",
    )

    assert "Hallo," in body


# ── Kennzahlen für die Übersicht ──────────────────────────────────────────────

def _superadmin() -> MagicMock:
    u = MagicMock()
    u.id = uuid.uuid4()
    u.is_superadmin = True
    u.email = "admin@example.com"
    return u


def _counting_db(counts: list[int]) -> AsyncMock:
    """Mock-DB, die jede Zählung der Reihe nach beantwortet.

    Nebenbei wird jede Anweisung gegen den Postgres-Dialekt übersetzt: Die
    Kennzahlen bestehen aus einem Dutzend handgeschriebener Abfragen, und ein
    Mock allein würde auch die durchwinken, die sich gar nicht ausführen ließe.
    """
    from sqlalchemy.dialects import postgresql

    remaining = iter(counts)

    def _execute(statement, *args, **kwargs):
        statement.compile(dialect=postgresql.dialect())
        result = MagicMock()
        # Einstellungen (Laufzeit, Karenzzeit) sind nicht gesetzt → Rückfall auf
        # die Umgebungsvariablen; nur die Zählungen zehren von der Liste.
        result.scalar_one_or_none.return_value = None
        result.scalar_one.side_effect = lambda: next(remaining)
        return result

    db = AsyncMock()
    db.execute.side_effect = _execute
    return db


async def _get_stats(db: AsyncMock) -> dict:
    app.dependency_overrides[require_superadmin] = _superadmin

    async def _db():
        yield db
    app.dependency_overrides[get_db] = _db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/admin/demo-stats")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_every_count_lands_in_its_own_field(monkeypatch):
    """Dreizehn Zahlen, dreizehn Felder — vertauschte Zuordnungen fallen sonst
    erst in der Oberfläche auf, wo sie niemand nachrechnet."""
    monkeypatch.setattr("app.services.demo.settings.demo_ip_cooldown_hours", 24)
    body = await _get_stats(_counting_db([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]))

    assert body == {
        "sessions_open": 1,
        "sessions_expiring_24h": 2,
        "convoys_in_demo": 3,
        "leads_total": 4,
        "leads_last_7d": 5,
        "leads_last_30d": 6,
        "followups_sent": 7,
        "unsubscribed": 8,
        "followups_due": 9,
        "followups_waiting": 10,
        "followups_failed": 11,
        "ip_locks_active": 12,
        "allowlist_entries": 13,
    }


@pytest.mark.asyncio
async def test_without_a_cooldown_no_address_counts_as_blocked(monkeypatch):
    """Karenzzeit 0 heißt: Es gibt keine Sperre, also auch nichts zu zählen —
    die Abfrage entfällt statt jede je gesehene Adresse zu melden."""
    monkeypatch.setattr("app.services.demo.settings.demo_ip_cooldown_hours", 0)
    body = await _get_stats(_counting_db([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 99]))

    assert body["ip_locks_active"] == 0
    # Die übersprungene Zählung verschiebt nichts: 99 ist die Allowlist.
    assert body["allowlist_entries"] == 99
