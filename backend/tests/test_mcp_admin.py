"""Die Verwaltung der MCP-Schnittstelle im Adminportal.

Der Kern ist der Widerruf: eine getrennte Verbindung muss wirklich getrennt
sein. Solange das nur in der Oberfläche so aussieht, ist der Knopf schlimmer
als keiner — er erzeugt die Gewissheit, ohne sie einzulösen.
"""
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.oauth_client import OAuthClient
from app.models.oauth_refresh_token import OAuthRefreshToken
from app.models.user import User
from app.services import oauth_tokens
from tests.mcp_fixtures import (
    connect,
    convoyplan_access_token,
    mcp_app,
    purge_clients,
    register_client,
    reset_db_engine,  # noqa: F401 — autouse-Fixture, per Import aktiviert
    seeded,
)


async def _superadmin_token(fx) -> str:
    """Den Testbenutzer vorübergehend zum Superadmin machen.

    Der Admin-Router ist durchgehend superadmin-gesichert; für die Prüfung
    der Endpunkte braucht es also einen."""
    async with AsyncSessionLocal() as db:
        user = await db.get(User, fx.planer.id)
        user.is_superadmin = True
        await db.commit()
    token = convoyplan_access_token(fx.planer, fx.org_a)
    # Die Superadmin-Claim muss im Token stehen, nicht nur in der Datenbank.
    import jwt as _jwt

    from app.config import settings

    payload = _jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    payload["is_superadmin"] = True
    return _jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def _admin_client(token: str) -> AsyncClient:
    from app.main import app as real_app

    return AsyncClient(
        transport=ASGITransport(app=real_app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )


# ── Zugriffsschutz ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ohne_superadmin_kein_zugriff():
    async with seeded() as fx:
        token = convoyplan_access_token(fx.planer, fx.org_a)  # kein Superadmin
        async with await _admin_client(token) as client:
            for pfad in ("/api/admin/mcp/status", "/api/admin/mcp/clients",
                         "/api/admin/mcp/connections",
                         "/api/admin/mcp/organizations"):
                resp = await client.get(pfad)
                assert resp.status_code == 403, f"{pfad}: {resp.status_code}"


@pytest.mark.asyncio
async def test_status_spiegelt_die_konfiguration():
    async with seeded() as fx:
        token = await _superadmin_token(fx)
        async with await _admin_client(token) as client:
            body = (await client.get("/api/admin/mcp/status")).json()
        from app.config import settings

        assert body["enabled"] is settings.mcp_enabled
        assert body["allow_dcr"] is settings.mcp_allow_dcr
        assert body["access_token_ttl_minutes"] == settings.mcp_access_token_ttl_minutes
        assert body["connection_url"] == oauth_tokens.public_resource_url()


# ── Verbindungen ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_erteilte_verbindung_taucht_in_der_liste_auf():
    async with seeded() as fx, mcp_app() as (_app, mcp_client):
        reg, _token = await connect(mcp_client, fx.planer, fx.org_a)
        admin_token = await _superadmin_token(fx)

        async with await _admin_client(admin_token) as client:
            eintraege = (await client.get("/api/admin/mcp/connections")).json()

        meine = [e for e in eintraege if e["client_id"] == reg["client_id"]]
        assert len(meine) == 1, "genau eine Verbindung je erteilter Zustimmung"
        eintrag = meine[0]
        assert eintrag["organization_id"] == str(fx.org_a.id)
        assert eintrag["user_email"] == fx.planer.email
        assert "convoy:read" in eintrag["scopes"]
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_trennen_macht_das_refresh_token_wertlos():
    """Der eigentliche Punkt dieses Reiters."""
    async with seeded() as fx, mcp_app() as (_app, mcp_client):
        reg, token = await connect(mcp_client, fx.planer, fx.org_a)
        admin_token = await _superadmin_token(fx)

        async with await _admin_client(admin_token) as client:
            eintraege = (await client.get("/api/admin/mcp/connections")).json()
            familie = next(
                e["family_id"] for e in eintraege if e["client_id"] == reg["client_id"]
            )
            resp = await client.delete(f"/api/admin/mcp/connections/{familie}")
            assert resp.status_code == 204

        # Das Refresh-Token darf sich danach nicht mehr einlösen lassen.
        antwort = await mcp_client.post("/token", data={
            "grant_type": "refresh_token",
            "refresh_token": token["refresh_token"],
            "client_id": reg["client_id"],
            "client_secret": reg.get("client_secret", ""),
        })
        assert antwort.status_code == 400

        async with AsyncSessionLocal() as db:
            zeilen = (
                await db.execute(
                    select(OAuthRefreshToken).where(
                        OAuthRefreshToken.family_id == uuid.UUID(familie)
                    )
                )
            ).scalars().all()
            assert zeilen and all(z.revoked for z in zeilen)
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_getrennte_verbindung_verschwindet_aus_der_liste():
    async with seeded() as fx, mcp_app() as (_app, mcp_client):
        reg, _token = await connect(mcp_client, fx.planer, fx.org_a)
        admin_token = await _superadmin_token(fx)

        async with await _admin_client(admin_token) as client:
            eintraege = (await client.get("/api/admin/mcp/connections")).json()
            familie = next(
                e["family_id"] for e in eintraege if e["client_id"] == reg["client_id"]
            )
            await client.delete(f"/api/admin/mcp/connections/{familie}")
            danach = (await client.get("/api/admin/mcp/connections")).json()

        assert not [e for e in danach if e["client_id"] == reg["client_id"]]
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_unbekannte_verbindung_ergibt_404():
    async with seeded() as fx:
        token = await _superadmin_token(fx)
        async with await _admin_client(token) as client:
            resp = await client.delete(f"/api/admin/mcp/connections/{uuid.uuid4()}")
        assert resp.status_code == 404


# ── Clients ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_client_liste_kennzeichnet_den_namen_als_ungeprueft():
    """Bei DCR darf sich jeder registrieren. Ein Name, den die Oberfläche
    ungekennzeichnet zeigt, ist eine Einladung für ein Programm, das sich
    „ConvoyPlan Desktop" nennt."""
    async with seeded() as _fx, mcp_app() as (_app, mcp_client):
        reg = await register_client(mcp_client)
        admin_token = await _superadmin_token(_fx)

        async with await _admin_client(admin_token) as client:
            eintraege = (await client.get("/api/admin/mcp/clients")).json()

        meiner = next(e for e in eintraege if e["client_id"] == reg["client_id"])
        assert meiner["name_verified"] is False
        assert meiner["client_name"] == "Testclient"
        assert meiner["redirect_uris"] == reg["redirect_uris"]
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_client_sperren_trennt_auch_seine_verbindungen():
    """Ein gesperrter Client, dessen Refresh-Tokens weiterleben, behielte
    seinen Zugang bis zu deren Ablauf — die Sperre wäre eine Attrappe."""
    async with seeded() as fx, mcp_app() as (_app, mcp_client):
        reg, token = await connect(mcp_client, fx.planer, fx.org_a)
        admin_token = await _superadmin_token(fx)

        async with await _admin_client(admin_token) as client:
            resp = await client.delete(f"/api/admin/mcp/clients/{reg['client_id']}")
            assert resp.status_code == 204

        async with AsyncSessionLocal() as db:
            zeile = await db.get(OAuthClient, reg["client_id"])
            assert zeile.revoked is True
            familien = (
                await db.execute(
                    select(OAuthRefreshToken).where(
                        OAuthRefreshToken.client_id == reg["client_id"]
                    )
                )
            ).scalars().all()
            assert familien and all(f.revoked for f in familien)

        antwort = await mcp_client.post("/token", data={
            "grant_type": "refresh_token",
            "refresh_token": token["refresh_token"],
            "client_id": reg["client_id"],
            "client_secret": reg.get("client_secret", ""),
        })
        assert antwort.status_code in (400, 401)
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_gesperrter_client_kann_sich_nicht_neu_autorisieren():
    async with seeded() as fx, mcp_app() as (_app, mcp_client):
        reg = await register_client(mcp_client)
        admin_token = await _superadmin_token(fx)
        async with await _admin_client(admin_token) as client:
            await client.delete(f"/api/admin/mcp/clients/{reg['client_id']}")

        from tests.mcp_fixtures import pkce_pair

        _verifier, challenge = pkce_pair()
        resp = await mcp_client.get("/authorize", params={
            "client_id": reg["client_id"],
            "redirect_uri": reg["redirect_uris"][0],
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        })
        assert resp.status_code >= 400
        await purge_clients([reg["client_id"]])


# ── Aufräumen verwaister Registrierungen ─────────────────────────────────


async def _zurueckdatieren(client_id: str, *, stunden: int) -> None:
    """Eine Registrierung künstlich altern lassen.

    Die Karenzzeit ist der einzige Teil der Bedingung, der sich nicht ohne
    Warten herstellen lässt — also wird hier die Zeile alt gemacht statt der
    Test langsam."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import update

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(OAuthClient)
            .where(OAuthClient.client_id == client_id)
            .values(created_at=datetime.now(timezone.utc) - timedelta(hours=stunden))
        )
        await db.commit()


@pytest.mark.asyncio
async def test_aufraeumen_entfernt_eine_registrierung_ohne_verbindung():
    """Der Grund für den Knopf: bei Selbstregistrierung legt jeder
    Verbindungsversuch eine Zeile an, auch der abgebrochene."""
    async with seeded() as fx, mcp_app() as (_app, mcp_client):
        reg = await register_client(mcp_client)
        await _zurueckdatieren(reg["client_id"], stunden=48)
        admin_token = await _superadmin_token(fx)

        async with await _admin_client(admin_token) as client:
            resp = await client.post("/api/admin/mcp/clients/cleanup")
            assert resp.status_code == 200
            assert resp.json()["removed"] >= 1

        async with AsyncSessionLocal() as db:
            assert await db.get(OAuthClient, reg["client_id"]) is None


@pytest.mark.asyncio
async def test_aufraeumen_laesst_eine_tragende_registrierung_stehen():
    """Was eine Verbindung trägt, ist nicht verwaist — auch wenn es alt ist.

    Sonst wäre das Aufräumen ein Zugangsentzug mit anderem Namen."""
    async with seeded() as fx, mcp_app() as (_app, mcp_client):
        reg, _token = await connect(mcp_client, fx.planer, fx.org_a)
        await _zurueckdatieren(reg["client_id"], stunden=24 * 365)
        admin_token = await _superadmin_token(fx)

        async with await _admin_client(admin_token) as client:
            assert (await client.post("/api/admin/mcp/clients/cleanup")).status_code == 200

        async with AsyncSessionLocal() as db:
            assert await db.get(OAuthClient, reg["client_id"]) is not None
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_aufraeumen_verschont_einen_laufenden_verbindungsversuch():
    """Zwischen Registrierung und Zustimmung steht die Anmeldung des
    Benutzers. In dieser Spanne trägt die Zeile nichts und sähe wie Müll aus
    — dafür ist die Karenzzeit da."""
    async with seeded() as fx, mcp_app() as (_app, mcp_client):
        reg = await register_client(mcp_client)  # eben erst, nicht zurückdatiert
        admin_token = await _superadmin_token(fx)

        async with await _admin_client(admin_token) as client:
            assert (await client.post("/api/admin/mcp/clients/cleanup")).status_code == 200

        async with AsyncSessionLocal() as db:
            assert await db.get(OAuthClient, reg["client_id"]) is not None
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_client_liste_zeigt_vorher_an_was_das_aufraeumen_traefe():
    """Das Portal soll die Zeilen kennzeichnen, die der Knopf mitnimmt —
    andernfalls bliebe nur, es hinterher an der Zahl abzulesen."""
    async with seeded() as fx, mcp_app() as (_app, mcp_client):
        verwaist = await register_client(mcp_client)
        await _zurueckdatieren(verwaist["client_id"], stunden=48)
        verbunden, _token = await connect(mcp_client, fx.planer, fx.org_a)
        await _zurueckdatieren(verbunden["client_id"], stunden=48)
        admin_token = await _superadmin_token(fx)

        async with await _admin_client(admin_token) as client:
            eintraege = (await client.get("/api/admin/mcp/clients")).json()

        nach_id = {e["client_id"]: e for e in eintraege}
        assert nach_id[verwaist["client_id"]]["orphaned"] is True
        assert nach_id[verbunden["client_id"]]["orphaned"] is False
        await purge_clients([verwaist["client_id"], verbunden["client_id"]])


# ── Welche Organisationen teilnehmen ─────────────────────────────────────


@pytest.mark.asyncio
async def test_organisationsliste_zeigt_freigabe_und_verbindungen():
    """Die Frage, die der Betreiber stellt: wer nutzt das eigentlich?

    Der Instanzschalter beantwortet sie nicht — eingeschaltet heißt nur, dass
    es ``/mcp`` gibt, nicht dass jemand teilnimmt."""
    from app.mcp import areas
    from app.mcp import scopes as scope_svc
    from app.services import org_mcp_policy

    async with seeded() as fx, mcp_app() as (_app, mcp_client):
        reg, _token = await connect(mcp_client, fx.planer, fx.org_a)

        # Organisation B nimmt nicht teil; die Fixture gibt beide frei, also
        # hier ausdrücklich zurückdrehen.
        async with AsyncSessionLocal() as db:
            await org_mcp_policy.setzen(
                db, fx.org_b.id, enabled=False, scopes=[], bereiche=[]
            )
            await org_mcp_policy.setzen(
                db,
                fx.org_a.id,
                enabled=True,
                scopes=[scope_svc.SCOPE_WRITE],
                bereiche=[areas.BEREICH_KONVOIS, areas.BEREICH_ROUTEN],
            )
            await db.commit()

        admin_token = await _superadmin_token(fx)
        async with await _admin_client(admin_token) as client:
            zeilen = (await client.get("/api/admin/mcp/organizations")).json()
            status = (await client.get("/api/admin/mcp/status")).json()

        nach_id = {z["organization_id"]: z for z in zeilen}

        a = nach_id[str(fx.org_a.id)]
        assert a["enabled"] is True
        assert a["konfiguriert"] is True
        assert a["bereiche"] == [areas.BEREICH_KONVOIS, areas.BEREICH_ROUTEN]
        # convoy:read ist Voraussetzung und kommt beim Speichern dazu.
        assert a["scopes"] == [scope_svc.SCOPE_READ, scope_svc.SCOPE_WRITE]
        assert a["active_connections"] == 1

        b = nach_id[str(fx.org_b.id)]
        assert b["enabled"] is False
        assert b["scopes"] == []
        assert b["active_connections"] == 0

        # Die Zählung im Status stimmt mit der Liste überein — zwei Zahlen für
        # dasselbe, nebeneinander im Portal, dürfen nicht auseinanderlaufen.
        assert status["organizations_total"] == len(zeilen)
        assert status["organizations_enabled"] == sum(1 for z in zeilen if z["enabled"])

        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_organisation_ohne_richtlinie_steht_als_standard_aus_in_der_liste():
    """Keine Zeile heißt aus — und die Liste muss sie trotzdem zeigen.

    Ein LEFT JOIN, kein Join über die Richtlinien: sonst fehlte genau die
    Mehrheit der Organisationen, und der Betreiber suchte im Nichts nach der
    Erklärung, warum eine Anbindung nicht zustande kommt."""
    from app.models.org_mcp_policy import OrganizationMcpPolicy

    async with seeded() as fx:
        async with AsyncSessionLocal() as db:
            zeile = await db.get(OrganizationMcpPolicy, fx.org_b.id)
            await db.delete(zeile)
            await db.commit()

        admin_token = await _superadmin_token(fx)
        async with await _admin_client(admin_token) as client:
            zeilen = (await client.get("/api/admin/mcp/organizations")).json()

        b = next(z for z in zeilen if z["organization_id"] == str(fx.org_b.id))
        assert b["enabled"] is False
        assert b["konfiguriert"] is False
        assert b["name"] == fx.org_b.name


@pytest.mark.asyncio
async def test_freigegebene_organisationen_stehen_oben():
    """Die Liste wird gelesen, um etwas zu finden, nicht um sie durchzugehen."""
    from app.services import org_mcp_policy

    async with seeded() as fx:
        async with AsyncSessionLocal() as db:
            await org_mcp_policy.setzen(
                db, fx.org_a.id, enabled=False, scopes=[], bereiche=[]
            )
            await db.commit()

        admin_token = await _superadmin_token(fx)
        async with await _admin_client(admin_token) as client:
            zeilen = (await client.get("/api/admin/mcp/organizations")).json()

        freigegeben = [i for i, z in enumerate(zeilen) if z["enabled"]]
        gesperrt = [i for i, z in enumerate(zeilen) if not z["enabled"]]
        assert not freigegeben or not gesperrt or max(freigegeben) < min(gesperrt)
