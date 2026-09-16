"""Scopes, Rollen und der abgeschaltete Zustand.

Scopes sind im MCP-Server eine Projektion der Rollenhierarchie, keine zweite
Berechtigungslogik. Diese Tests halten fest, dass die Projektion nicht mehr
hergibt als die Rolle — auch dann nicht, wenn sich die Rolle nach der
Zustimmung ändert.
"""
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.database import AsyncSessionLocal
from app.mcp import scopes as scope_svc
from app.models.organization import UserOrganization
from app.services import oauth_tokens
from tests.mcp_fixtures import (
    connect,
    convoyplan_access_token,
    mcp_app,
    purge_clients,
    reset_db_engine,  # noqa: F401 — autouse-Fixture, per Import aktiviert
    seeded,
)


# ── Die Projektion selbst ────────────────────────────────────────────────


def test_jede_rolle_bekommt_genau_ihre_scopes():
    assert scope_svc.scopes_for_role("beobachter") == [scope_svc.SCOPE_READ]
    assert scope_svc.scopes_for_role("fahrer") == [
        scope_svc.SCOPE_READ,
        scope_svc.SCOPE_FLEET_STATUS,
    ]
    assert scope_svc.scopes_for_role("planer") == list(scope_svc.ALL_SCOPES)
    assert scope_svc.scopes_for_role("admin") == list(scope_svc.ALL_SCOPES)


def test_unbekannte_rolle_bekommt_nichts():
    """Fail-closed. Eine Rolle, die wir nicht kennen, ist keine Erlaubnis."""
    assert scope_svc.scopes_for_role("geschaeftsfuehrung") == []
    assert scope_svc.scopes_for_role("") == []


def test_scope_hierarchie_wirkt_in_eine_richtung():
    """Wer schreiben darf, darf auch lesen — aber nicht umgekehrt."""
    assert scope_svc.satisfies([scope_svc.SCOPE_WRITE], scope_svc.SCOPE_READ)
    assert scope_svc.satisfies([scope_svc.SCOPE_WRITE], scope_svc.SCOPE_FLEET_STATUS)
    assert scope_svc.satisfies([scope_svc.SCOPE_FLEET_STATUS], scope_svc.SCOPE_READ)
    assert not scope_svc.satisfies([scope_svc.SCOPE_READ], scope_svc.SCOPE_WRITE)
    assert not scope_svc.satisfies([scope_svc.SCOPE_FLEET_STATUS], scope_svc.SCOPE_WRITE)


def test_grantable_schneidet_statt_zu_vereinigen():
    """Ein Client, der zu viel verlangt, bekommt weniger — kein Fehler und
    schon gar nicht mehr, als die Rolle hergibt."""
    assert scope_svc.grantable(scope_svc.ALL_SCOPES, "beobachter") == [
        scope_svc.SCOPE_READ
    ]
    # Und wer wenig verlangt, bekommt nicht mehr, nur weil er dürfte.
    assert scope_svc.grantable([scope_svc.SCOPE_READ], "admin") == [scope_svc.SCOPE_READ]


def test_scopes_supported_ist_der_minimale_satz():
    """Die Spec will in der Protected Resource Metadata den minimalen Satz
    für die Grundfunktion sehen, nicht die Gesamtmenge."""
    assert scope_svc.SCOPES_SUPPORTED == [scope_svc.SCOPE_READ]


# ── Die Projektion im Betrieb ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_beobachter_bekommt_kein_schreibrecht_zugestanden():
    """Auch wenn der Client convoy:write verlangt: die Rolle entscheidet."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token = await connect(
            client, fx.beobachter, fx.org_a, scopes=list(scope_svc.ALL_SCOPES)
        )
        assert token["scope"] == scope_svc.SCOPE_READ
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_herabstufung_nimmt_dem_bestehenden_token_das_schreibrecht():
    """Eine herabgestufte Rolle wirkt sofort, ohne dass das Token neu
    ausgestellt werden muss — die Scopes fallen bei jeder Prüfung auf das
    zurück, was die aktuelle Mitgliedschaft hergibt."""
    async with seeded() as fx:
        token, _ = oauth_tokens.mint_access_token(
            user=fx.planer,
            organization_id=fx.org_a.id,
            client_id="c",
            scopes=list(scope_svc.ALL_SCOPES),
        )
        async with AsyncSessionLocal() as db:
            verified = await oauth_tokens.verify_access_token(db, token)
            assert scope_svc.SCOPE_WRITE in verified.scopes

        async with AsyncSessionLocal() as db:
            membership = await db.get(
                UserOrganization, {"user_id": fx.planer.id, "organization_id": fx.org_a.id}
            )
            membership.role = "beobachter"
            await db.commit()

        async with AsyncSessionLocal() as db:
            verified = await oauth_tokens.verify_access_token(db, token)
            assert verified.scopes == [scope_svc.SCOPE_READ]


@pytest.mark.asyncio
async def test_ein_token_gilt_fuer_genau_eine_organisation():
    """Der Benutzer ist Planer in beiden Organisationen. Das Token für A
    darf trotzdem nichts in B ausrichten."""
    async with seeded() as fx:
        token, _ = oauth_tokens.mint_access_token(
            user=fx.planer,
            organization_id=fx.org_a.id,
            client_id="c",
            scopes=[scope_svc.SCOPE_READ],
        )
        async with AsyncSessionLocal() as db:
            verified = await oauth_tokens.verify_access_token(db, token)
        assert verified.organization_id == fx.org_a.id
        assert verified.organization_id != fx.org_b.id


# ── Der abgeschaltete Zustand ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ohne_mcp_enabled_existiert_nichts_davon():
    """Auslieferungszustand. Eine Bestandsinstallation, die nichts
    konfiguriert, darf keinen einzigen neuen Endpunkt bekommen."""
    from app.main import app as real_app

    assert settings.mcp_enabled is False
    async with AsyncClient(
        transport=ASGITransport(app=real_app), base_url="http://test"
    ) as client:
        for pfad in (
            "/mcp",
            "/.well-known/oauth-protected-resource/mcp",
            "/.well-known/oauth-authorization-server",
            "/authorize",
            "/token",
            "/register",
        ):
            resp = await client.get(pfad)
            assert resp.status_code == 404, f"{pfad} antwortet mit {resp.status_code}"


@pytest.mark.asyncio
async def test_consent_route_ist_ohne_mcp_enabled_zu():
    """Die Consent-Route hängt am selben Schalter — sonst bliebe ein
    Endpunkt offen, der Autorisierungscodes ausstellt."""
    from app.main import app as real_app

    async with seeded() as fx:
        bearer = convoyplan_access_token(fx.planer, fx.org_a)
        async with AsyncClient(
            transport=ASGITransport(app=real_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/mcp/consent",
                params={"request": "egal"},
                headers={"Authorization": f"Bearer {bearer}"},
            )
        assert resp.status_code == 404
