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
    authorize,
    connect,
    convoyplan_access_token,
    mcp_app,
    pkce_pair,
    purge_clients,
    register_client,
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


def test_scopes_supported_nennt_alles_was_die_resource_versteht():
    """Die Protected Resource Metadata weist aus, was es gibt.

    Stünde hier nur ``convoy:read``, bliebe jeder Client ohne Step-up für
    immer lesend — er hätte nie erfahren, dass es mehr gibt."""
    assert scope_svc.SCOPES_SUPPORTED == list(scope_svc.ALL_SCOPES)


def test_endpunkt_verlangt_nur_das_lesende_minimum():
    """Was ``scopes_supported`` ausweist, darf der Endpunkt nicht verlangen.

    ``RequireAuthMiddleware`` prüft jeden Eintrag aus ``required_scopes``
    einzeln gegen das Token. Stünden dort alle drei, käme ein lesendes Token
    an keinem einzigen Werkzeug mehr an."""
    assert scope_svc.REQUIRED_SCOPES == [scope_svc.SCOPE_READ]


def test_erteilte_scopes_werden_ausgeschrieben():
    """Ein Token mit nur ``convoy:write`` käme am Endpunkt nicht vorbei.

    Die Hierarchie kennt nur ConvoyPlan, nicht die Middleware des SDK —
    was ein Scope einschließt, muss deshalb im Token stehen."""
    assert scope_svc.effective([scope_svc.SCOPE_WRITE], "planer") == list(
        scope_svc.ALL_SCOPES
    )
    # Die Rolle bleibt die Obergrenze, auch beim Ausschreiben.
    assert scope_svc.effective([scope_svc.SCOPE_WRITE], "beobachter") == []
    assert scope_svc.effective([scope_svc.SCOPE_FLEET_STATUS], "fahrer") == [
        scope_svc.SCOPE_READ,
        scope_svc.SCOPE_FLEET_STATUS,
    ]


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


# ── Die Auswahl auf dem Zustimmungsbildschirm ────────────────────────────
#
# Ein Client, der nur lesend anfragt, bleibt sonst für immer lesend: nicht
# jeder kann später nachfordern, was er zunächst nicht wollte. Die Auswahl
# liegt deshalb beim angemeldeten Menschen — gedeckelt durch seine Rolle.


@pytest.mark.asyncio
async def test_zustimmung_kann_mehr_erteilen_als_der_client_verlangt():
    """Der Client fragt lesend, der Planer kreuzt Schreiben an."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token = await connect(
            client,
            fx.planer,
            fx.org_a,
            scopes=[scope_svc.SCOPE_READ],
            zustimmung=[scope_svc.SCOPE_READ, scope_svc.SCOPE_WRITE],
        )
        erteilt = token["scope"].split()
        assert scope_svc.SCOPE_WRITE in erteilt
        # Ausgeschrieben, nicht nur angedeutet: der Endpunkt prüft ohne
        # Hierarchie, ein Token ohne convoy:read käme nicht durch.
        assert scope_svc.SCOPE_READ in erteilt
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_zustimmung_kommt_nicht_ueber_die_rolle_hinaus():
    """Ankreuzen hilft nicht, wo die Mitgliedschaft nichts hergibt."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token = await connect(
            client,
            fx.beobachter,
            fx.org_a,
            scopes=[scope_svc.SCOPE_READ],
            zustimmung=list(scope_svc.ALL_SCOPES),
        )
        assert token["scope"] == scope_svc.SCOPE_READ
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_zustimmung_kann_das_angefragte_auch_beschneiden():
    """Abwählen ist die andere Richtung derselben Auswahl."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token = await connect(
            client,
            fx.planer,
            fx.org_a,
            scopes=list(scope_svc.ALL_SCOPES),
            zustimmung=[scope_svc.SCOPE_READ],
        )
        assert token["scope"] == scope_svc.SCOPE_READ
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_ohne_angekreuztes_recht_entsteht_kein_code():
    """Eine leere Auswahl ist keine Zustimmung."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg = await register_client(client)
        _verifier, challenge = pkce_pair()
        ticket = await authorize(client, reg, challenge, [scope_svc.SCOPE_READ])
        bearer = convoyplan_access_token(fx.planer, fx.org_a)
        resp = await client.post(
            "/api/mcp/consent",
            json={
                "request": ticket,
                "approve": True,
                "organization_id": str(fx.org_a.id),
                "scopes": [],
            },
            headers={"Authorization": f"Bearer {bearer}"},
        )
        assert resp.status_code == 403, resp.text
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_der_bildschirm_nennt_was_die_rolle_zusaetzlich_hergaebe():
    """Was nicht angefragt wurde, muss trotzdem ankreuzbar sein — sonst
    weiß der Benutzer nicht, dass es die Wahl gibt."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg = await register_client(client)
        _verifier, challenge = pkce_pair()
        ticket = await authorize(client, reg, challenge, [scope_svc.SCOPE_READ])
        bearer = convoyplan_access_token(fx.planer, fx.org_a)
        resp = await client.get(
            "/api/mcp/consent",
            params={"request": ticket},
            headers={"Authorization": f"Bearer {bearer}"},
        )
        assert resp.status_code == 200, resp.text
        info = resp.json()
        assert [s["scope"] for s in info["requested_scopes"]] == [scope_svc.SCOPE_READ]
        weitere = {s["scope"] for s in info["optional_scopes"]}
        assert scope_svc.SCOPE_WRITE in weitere
        org = next(o for o in info["organizations"] if o["id"] == str(fx.org_a.id))
        assert scope_svc.SCOPE_WRITE in org["optional_scopes"]
        # Und jeder angebotene Text ist beschriftet, nicht nur benannt.
        assert all(s["label"] for s in info["optional_scopes"])
        await purge_clients([reg["client_id"]])
