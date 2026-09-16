"""Verwaltung der E-Mail-Vorlagen: Verzeichnis, Hinterlegen, Testversand.

Die Vorlagen sind vom Superadmin frei editierbar und landen unverändert in
verschickten Mails — die Tests decken deshalb vor allem ab, was dabei schief
gehen kann: eine Vorlage, die es nicht gibt, ein Platzhalter, der keiner ist,
und ein Testversand ohne SMTP.
"""

import re
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_db, require_superadmin
from app.api.routes import email_template as routes
from app.api.routes.email_template import KINDS
from app.main import app
from app.services import email as email_svc


def _superadmin(email: str = "admin@example.com") -> MagicMock:
    u = MagicMock()
    u.id = uuid.uuid4()
    u.is_superadmin = True
    u.email = email
    return u


def _db_without_overrides() -> AsyncMock:
    """Mock-DB, in der keine Einstellung hinterlegt ist — überall der Standard."""
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result
    return db


async def _call(method: str, path: str, *, db: AsyncMock, user=None, json=None):
    app.dependency_overrides[require_superadmin] = lambda: (user or _superadmin())

    async def _db():
        yield db
    app.dependency_overrides[get_db] = _db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, path, json=json)
    finally:
        app.dependency_overrides.clear()


# ── Verzeichnis ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_both_templates_are_listed_with_their_purpose():
    """Das Verzeichnis ist die einzige Stelle, an der steht, wofür eine Vorlage
    überhaupt verschickt wird — ohne Beschreibung rät der Superadmin."""
    resp = await _call("GET", "/api/admin/email-templates", db=_db_without_overrides())

    assert resp.status_code == 200
    by_kind = {row["kind"]: row for row in resp.json()}
    assert set(by_kind) == {"password", "demo_followup"}
    assert all(row["description"] for row in by_kind.values())
    # Ohne hinterlegte Fassung gilt der mitgelieferte Standard.
    assert not any(row["is_custom"] for row in by_kind.values())


@pytest.mark.asyncio
async def test_an_unknown_template_is_a_404_not_a_crash():
    resp = await _call("GET", "/api/admin/email-templates/gibtsnicht", db=_db_without_overrides())
    assert resp.status_code == 404


# ── Platzhalter ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["password", "demo_followup"])
async def test_every_advertised_placeholder_is_actually_substituted(kind):
    """Der Editor listet die Platzhalter als das, was man einsetzen darf. Stünde
    dort einer, den das Rendering gar nicht kennt, landete er beim ersten
    Bearbeiten wörtlich in der Mail des Empfängers.

    Geprüft wird deshalb am Rendering selbst, nicht an der mitgelieferten
    Vorlage: Die nutzt nicht jeden erlaubten Platzhalter (`{recipient_name}`
    etwa steckt dort in `{recipient_name_greeting}`), erlaubt ist er trotzdem."""
    template = KINDS[kind]
    probe = " ".join(f"{{{name}}}" for name in template.placeholders)

    with patch.object(email_svc, "get_template", AsyncMock(return_value=(probe, probe))):
        subject, html = await template.preview(_db_without_overrides())

    leftover = re.findall(r"\{(\w+)\}", subject + html)
    assert not leftover, f"nicht ersetzt: {sorted(set(leftover))}"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["password", "demo_followup"])
async def test_the_default_uses_no_placeholder_the_editor_hides(kind):
    """Die Gegenrichtung: Ein Platzhalter in der Vorlage, der nicht in der Liste
    steht, ist für den Bearbeitenden unsichtbar — er streicht ihn versehentlich
    und merkt es nicht."""
    template = KINDS[kind]
    used = set(re.findall(r"\{(\w+)\}", template.default_subject + template.default_html))
    assert used <= set(template.placeholders), f"nicht dokumentiert: {used - set(template.placeholders)}"


# ── Hinterlegen und Verwerfen ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_stored_template_is_reported_as_custom():
    db = AsyncMock()
    stored = MagicMock()
    stored.key = "email.template.demo_followup.subject"
    stored.value = "Na, wie war's?"
    result = MagicMock()
    result.scalars.return_value.all.return_value = [stored]
    result.scalar_one_or_none.return_value = stored
    db.execute.return_value = result

    resp = await _call("GET", "/api/admin/email-templates/demo_followup", db=db)

    assert resp.status_code == 200
    body = resp.json()
    assert body["subject"] == "Na, wie war's?"
    assert body["is_custom"] is True
    # Nur der Betreff war hinterlegt — das HTML bleibt der Standard.
    assert "Hat alles gepasst" in body["html"]


@pytest.mark.asyncio
async def test_an_empty_stored_value_falls_back_to_the_default():
    """Eine leere Vorlage wäre eine Mail ohne Inhalt — die ist nie gemeint."""
    db = AsyncMock()
    result = MagicMock()
    empty = MagicMock()
    empty.key = "a"
    empty.value = ""
    result.scalars.return_value.all.return_value = [empty]
    db.execute.return_value = result

    subject, html = await email_svc.get_template(
        db, "a", "b", "Standardbetreff", "<p>Standard</p>",
    )
    assert subject == "Standardbetreff"
    assert html == "<p>Standard</p>"


# ── Testversand ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_without_smtp_the_test_send_says_so_instead_of_failing_obscurely():
    with patch.object(routes, "is_smtp_configured", AsyncMock(return_value=False)):
        resp = await _call(
            "POST", "/api/admin/email-templates/demo_followup/test",
            db=_db_without_overrides(),
        )

    assert resp.status_code == 400
    assert "SMTP" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_the_test_mail_goes_to_the_caller_and_nowhere_else():
    """Ein frei wählbarer Empfänger machte aus dem Admin-Portal einen Versender
    für beliebige Adressen — mit dem Absender der Installation im Rücken."""
    sent = {}

    async def _send(db, recipient, subject, body, **kwargs):
        sent.update(recipient=recipient, subject=subject, body=body)

    with (
        patch.object(routes, "is_smtp_configured", AsyncMock(return_value=True)),
        patch.object(routes, "_send_html_email", _send),
    ):
        resp = await _call(
            "POST", "/api/admin/email-templates/demo_followup/test",
            db=_db_without_overrides(), user=_superadmin("chef@example.org"),
        )

    assert resp.status_code == 200
    assert resp.json() == {"status": "sent", "recipient": "chef@example.org"}
    assert sent["recipient"] == "chef@example.org"
    # Als Test erkennbar, damit die Mail im Postfach nicht mit einer echten
    # Nachfrage verwechselt wird.
    assert sent["subject"].startswith("[Test] ")
    # Verschickt wird das Musterexemplar der echten Vorlage, kein Ersatztext.
    assert "Hat alles gepasst" in sent["body"]


@pytest.mark.asyncio
async def test_a_refusing_mail_server_is_reported_with_its_own_words():
    """„Versand fehlgeschlagen" allein hilft niemandem — die Auskunft des
    Servers ist hier die eigentliche Fehlersuche."""
    async def _send(*args, **kwargs):
        raise RuntimeError("535 Authentifizierung fehlgeschlagen")

    with (
        patch.object(routes, "is_smtp_configured", AsyncMock(return_value=True)),
        patch.object(routes, "_send_html_email", _send),
    ):
        resp = await _call(
            "POST", "/api/admin/email-templates/password/test",
            db=_db_without_overrides(),
        )

    assert resp.status_code == 502
    assert "535" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_an_account_without_an_address_cannot_send_itself_a_test():
    with patch.object(email_svc, "is_smtp_configured", AsyncMock(return_value=True)):
        resp = await _call(
            "POST", "/api/admin/email-templates/password/test",
            db=_db_without_overrides(), user=_superadmin(""),
        )

    assert resp.status_code == 400


# ── Vorschau ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["password", "demo_followup"])
async def test_the_preview_renders_the_real_thing(kind):
    """Gerendert wird mit derselben Funktion wie die echte Mail; eine eigene
    Vorschau-Implementierung liefe irgendwann auseinander."""
    resp = await _call("GET", f"/api/admin/email-templates/{kind}/preview",
                       db=_db_without_overrides())

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    body = resp.text
    assert "<!DOCTYPE html>" in body
    # Musterwerte statt leerer Platzhalter — sonst zeigt die Vorschau Lücken,
    # die in der echten Mail gefüllt sind.
    assert "Max Mustermann" in body
    assert "{recipient_name" not in body
