"""Die MCP-Richtlinie einer Organisation.

Der Instanzschalter beantwortet, ob es die Schnittstelle **gibt**. Diese
Tests halten die zweite Ebene fest: ob eine Organisation daran teilnimmt,
welchen Ausschnitt ihrer Daten sie freigibt und ob es beim Lesen bleibt.

Die Reihenfolge ist Absicht. Zuerst die Tabellen — sie sind statisch prüfbar
und die Stelle, an der ein neues Werkzeug ohne Bereich auffallen soll. Dann
die Richtlinie als Rechenregel. Erst danach der Weg durch den echten
Transport, wo es teuer wird.
"""
import ast
import pathlib

import pytest
from httpx import ASGITransport, AsyncClient

from app.database import AsyncSessionLocal
from app.mcp import ALLOWED_TOOLS, READ_TOOLS, WRITE_TOOLS
from app.mcp import areas
from app.mcp import scopes as scope_svc
from app.models.org_mcp_policy import OrganizationMcpPolicy
from app.services import org_mcp_policy
from tests.mcp_fixtures import (
    call,
    connect,
    convoyplan_access_token,
    mcp_app,
    mcp_session,
    purge_clients,
    reset_db_engine,  # noqa: F401 — autouse-Fixture, per Import aktiviert
    seeded,
    tool_payload,
)


# ── Die Tabellen ─────────────────────────────────────────────────────────


def test_jedes_werkzeug_hat_einen_bereich_oder_ist_ein_grundwerkzeug():
    """Die Lücke, durch die sonst still Daten abflössen.

    Ein Werkzeug ohne Bereich wäre von keiner Freigabe gedeckt — und weil
    ``bereich_fuer()`` fail-open ist, ginge es überall durch. Der Test ist
    die einzige Stelle, an der das auffällt, bevor es in Produktion steht."""
    ohne = [
        w
        for w in ALLOWED_TOOLS
        if w not in areas.TOOL_BEREICHE and w not in areas.GRUNDWERKZEUGE
    ]
    assert ohne == [], f"Werkzeuge ohne Bereich: {ohne}"


def test_kein_bereichseintrag_zeigt_auf_ein_werkzeug_das_es_nicht_gibt():
    verwaist = [w for w in areas.TOOL_BEREICHE if w not in ALLOWED_TOOLS]
    assert verwaist == []
    assert all(w in ALLOWED_TOOLS for w in areas.GRUNDWERKZEUGE)


def test_kein_werkzeug_steht_in_zwei_listen():
    """Grundwerkzeug *und* Bereich wäre widersprüchlich: das Grundwerkzeug
    bliebe trotz gesperrtem Bereich erreichbar, und niemand sähe, welche der
    beiden Angaben gilt."""
    assert not set(areas.GRUNDWERKZEUGE) & set(areas.TOOL_BEREICHE)


def test_jeder_bereich_traegt_eine_beschriftung():
    """„konvois" liest ein Org-Admin nicht als Freigabe, sondern als Spalte."""
    assert set(areas.BEREICH_LABELS) == set(areas.ALL_BEREICHE)
    assert all(areas.BEREICH_LABELS[b].strip() for b in areas.ALL_BEREICHE)


def test_jedes_werkzeug_uebergibt_seinen_eigenen_namen_an_mcp_context():
    """Die Richtlinienprüfung hängt daran, und zwar vollständig.

    Sie steht zentral in ``mcp_context(werkzeug=…)`` statt in 23 Werkzeugen,
    weil 23 Prüfungen genau eine sind, die jemand beim 24. Werkzeug vergisst.
    Der Preis dafür ist, dass jedes Werkzeug seinen Namen selbst durchreichen
    muss — und ein vertippter oder kopierter Name prüfte dann die Freigabe
    eines fremden Werkzeugs. Deshalb hier gegen den Quelltext."""
    gefunden: dict[str, str | None] = {}
    for datei in ("app/mcp/tools_read.py", "app/mcp/tools_write.py"):
        baum = ast.parse(pathlib.Path(datei).read_text())
        for knoten in ast.walk(baum):
            if not isinstance(knoten, ast.AsyncFunctionDef):
                continue
            if knoten.name not in ALLOWED_TOOLS:
                continue
            argumente = [
                aufruf.args
                for aufruf in ast.walk(knoten)
                if isinstance(aufruf, ast.Call)
                and isinstance(aufruf.func, ast.Name)
                and aufruf.func.id == "mcp_context"
            ]
            gefunden[knoten.name] = (
                argumente[0][0].value
                if argumente and argumente[0] and isinstance(argumente[0][0], ast.Constant)
                else None
            )

    assert set(gefunden) == set(ALLOWED_TOOLS), (
        "Werkzeug ohne gefundene Definition: "
        f"{sorted(set(ALLOWED_TOOLS) - set(gefunden))}"
    )
    falsch = {name: wert for name, wert in gefunden.items() if wert != name}
    assert falsch == {}, f"Werkzeuge mit falschem oder fehlendem Namen: {falsch}"


def test_werkzeuge_fuer_bereiche_ist_die_umkehrung_der_tabelle():
    alle = areas.werkzeuge_fuer(areas.ALL_BEREICHE)
    assert set(alle) == set(READ_TOOLS) | set(WRITE_TOOLS)
    nur_routen = areas.werkzeuge_fuer([areas.BEREICH_ROUTEN])
    assert "route_berechnen" in nur_routen
    assert "konvois_auflisten" not in nur_routen
    # Grundwerkzeuge bleiben auch bei leerer Auswahl dabei.
    assert set(areas.werkzeuge_fuer([])) == set(areas.GRUNDWERKZEUGE)


# ── Die Richtlinie als Rechenregel ───────────────────────────────────────


def test_standard_ist_aus():
    """Der Kern der Sache: ohne Eintrag geht nichts, egal welche Rolle."""
    assert org_mcp_policy.AUS.enabled is False
    assert org_mcp_policy.AUS.scopes == ()
    assert org_mcp_policy.AUS.bereiche == ()
    for werkzeug in ALLOWED_TOOLS:
        assert org_mcp_policy.AUS.erlaubt_werkzeug(werkzeug) is False


def test_abgeschaltete_organisation_gibt_nichts_her_auch_bei_voller_liste():
    """Der Schalter schlägt die Listen. Sonst genügte eine vergessene Zeile
    mit vollen Freigaben, um einen bewussten „aus"-Klick zu überstimmen."""
    policy = org_mcp_policy.Policy(
        enabled=False,
        scopes=tuple(scope_svc.ALL_SCOPES),
        bereiche=tuple(areas.ALL_BEREICHE),
    )
    assert policy.erlaubt_werkzeug("konvois_auflisten") is False
    assert policy.zuschneiden(list(scope_svc.ALL_SCOPES)) == []


def test_bereich_und_scope_wirken_als_und():
    policy = org_mcp_policy.Policy(
        enabled=True,
        scopes=(scope_svc.SCOPE_READ, scope_svc.SCOPE_WRITE),
        bereiche=(areas.BEREICH_KONVOIS,),
    )
    assert policy.erlaubt_werkzeug("konvoi_anlegen") is True
    # Scope da, Bereich nicht.
    assert policy.erlaubt_werkzeug("wegpunkt_anlegen") is False
    # Bereich da, Scope nicht: fleet:status fehlt.
    policy_status = org_mcp_policy.Policy(
        enabled=True,
        scopes=(scope_svc.SCOPE_READ,),
        bereiche=(areas.BEREICH_STATUS,),
    )
    assert policy_status.erlaubt_werkzeug("konvoi_status") is True
    assert policy_status.erlaubt_werkzeug("fahrzeugstatus_setzen") is False


def test_freigabe_kennt_keine_scope_hierarchie():
    """``convoy:write`` freizugeben heißt nicht, Standorte freizugeben.

    Die Hierarchie sagt, was ein erteiltes *Recht* einschließt. Was eine
    Organisation **freigeben will**, ist eine andere Frage — „planen ja,
    Positionen nein" muss sich ausdrücken lassen."""
    policy = org_mcp_policy.Policy(
        enabled=True,
        scopes=(scope_svc.SCOPE_READ, scope_svc.SCOPE_WRITE),
        bereiche=tuple(areas.ALL_BEREICHE),
    )
    assert policy.erlaubt_werkzeug("konvoi_anlegen") is True
    assert policy.erlaubt_werkzeug("fahrzeugstatus_setzen") is False


def test_grundwerkzeug_braucht_keinen_bereich():
    policy = org_mcp_policy.Policy(
        enabled=True, scopes=(scope_svc.SCOPE_READ,), bereiche=()
    )
    assert policy.erlaubt_werkzeug("organisation_details") is True
    assert policy.erlaubt_werkzeug("konvois_auflisten") is False


@pytest.mark.asyncio
async def test_setzen_ergaenzt_den_basis_scope_und_wirft_unbekanntes_weg():
    """Ohne ``convoy:read`` käme keine Verbindung an ``/mcp`` vorbei — eine
    eingeschaltete Organisation, die ihn nicht trüge, wäre eine Einstellung,
    die nichts tut außer Rätsel aufzugeben."""
    async with seeded() as fx:
        async with AsyncSessionLocal() as db:
            policy = await org_mcp_policy.setzen(
                db,
                fx.org_a.id,
                enabled=True,
                scopes=[scope_svc.SCOPE_WRITE, "convoy:delete"],
                bereiche=[areas.BEREICH_KONVOIS, "geheimakten"],
            )
            await db.commit()
        assert policy.scopes == (scope_svc.SCOPE_READ, scope_svc.SCOPE_WRITE)
        assert policy.bereiche == (areas.BEREICH_KONVOIS,)

        async with AsyncSessionLocal() as db:
            gelesen = await org_mcp_policy.fuer_org(db, fx.org_a.id)
        assert gelesen == policy


@pytest.mark.asyncio
async def test_abschalten_laesst_keine_scopes_stehen():
    async with seeded() as fx:
        async with AsyncSessionLocal() as db:
            policy = await org_mcp_policy.setzen(
                db,
                fx.org_a.id,
                enabled=False,
                scopes=list(scope_svc.ALL_SCOPES),
                bereiche=list(areas.ALL_BEREICHE),
            )
            await db.commit()
        # Gespeichert bleibt die Auswahl — abgeschaltet gibt sie nichts her.
        assert policy.enabled is False
        assert policy.zuschneiden(list(scope_svc.ALL_SCOPES)) == []


@pytest.mark.asyncio
async def test_keine_zeile_heisst_aus():
    async with seeded() as fx:
        async with AsyncSessionLocal() as db:
            zeile = await db.get(OrganizationMcpPolicy, fx.org_a.id)
            await db.delete(zeile)
            await db.commit()
        async with AsyncSessionLocal() as db:
            policy = await org_mcp_policy.fuer_org(db, fx.org_a.id)
        assert policy.enabled is False
        assert policy.gesetzt is False


# ── Durch den echten Transport ───────────────────────────────────────────


async def _policy_setzen(org_id, *, enabled, scopes, bereiche) -> None:
    async with AsyncSessionLocal() as db:
        await org_mcp_policy.setzen(
            db, org_id, enabled=enabled, scopes=scopes, bereiche=bereiche
        )
        await db.commit()


def _fehlertext(antwort: dict) -> str:
    """Den Text einer abgelehnten Werkzeugantwort holen."""
    result = antwort.get("result", {})
    assert result.get("isError") is True, antwort
    return " ".join(
        teil.get("text", "") for teil in result.get("content", []) if isinstance(teil, dict)
    )


@pytest.mark.asyncio
async def test_abgeschaltete_organisation_lehnt_bestehende_verbindungen_ab():
    """Der wichtigste Fall: die Verbindung besteht schon, das Token gilt noch.

    Die Richtlinie wird bei **jedem** Aufruf frisch gelesen, nicht aus dem
    Token. Ein Org-Admin, der abschaltet, soll nicht 15 Minuten auf den
    Ablauf eines Access-Tokens warten müssen."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token = await connect(client, fx.planer, fx.org_a)
        session = await mcp_session(client, token["access_token"])

        # Vorher geht es.
        vorher = tool_payload(
            await call(
                client, token["access_token"], session,
                "tools/call", {"name": "konvois_auflisten", "arguments": {}},
            )
        )
        assert fx.convoy_a.name in [k["name"] for k in vorher["konvois"]]

        await _policy_setzen(
            fx.org_a.id, enabled=False, scopes=[], bereiche=[]
        )

        nachher = await call(
            client, token["access_token"], session,
            "tools/call", {"name": "konvois_auflisten", "arguments": {}},
        )
        assert "abgeschaltet" in _fehlertext(nachher)
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_gesperrter_bereich_ist_auch_ueber_andere_werkzeuge_zu():
    """Ein Bereich, der zu ist, ist zu — nicht nur im offensichtlichen
    Werkzeug. Sonst wäre die Freigabe eine Frage danach, welchen Umweg ein
    Modell findet."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token = await connect(client, fx.planer, fx.org_a)
        session = await mcp_session(client, token["access_token"])

        await _policy_setzen(
            fx.org_a.id,
            enabled=True,
            scopes=list(scope_svc.ALL_SCOPES),
            bereiche=[areas.BEREICH_KONVOIS],
        )

        # Konvois: frei.
        erlaubt = tool_payload(
            await call(
                client, token["access_token"], session,
                "tools/call", {"name": "konvois_auflisten", "arguments": {}},
            )
        )
        assert "konvois" in erlaubt

        # Fahrzeuge, Positionen, Wegpunkte: zu.
        for werkzeug, argumente in (
            ("fahrzeuge_auflisten", {}),
            ("fahrzeugpositionen_abrufen", {"konvoi_id": str(fx.convoy_a.id)}),
            ("wegpunkte_auflisten", {"konvoi_id": str(fx.convoy_a.id)}),
        ):
            antwort = await call(
                client, token["access_token"], session,
                "tools/call", {"name": werkzeug, "arguments": argumente},
            )
            assert "nicht für die KI-Schnittstelle freigegeben" in _fehlertext(antwort)

        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_nur_lesend_freigegeben_verhindert_das_schreiben():
    """Der Planer *darf* schreiben und sein Token trägt ``convoy:write``.
    Die Organisation gibt es trotzdem nicht her — das ist der Punkt."""
    async with seeded() as fx, mcp_app() as (_app, client):
        # Verbunden wird, solange die Organisation noch alles freigibt — das
        # Token trägt danach ``convoy:write``. Erst dann wird zurückgedreht:
        # geprüft werden soll das *bestehende* Schreibrecht gegen die neue
        # Freigabe, nicht ein Token, das nie eines hatte.
        reg, token = await connect(
            client, fx.planer, fx.org_a, scopes=list(scope_svc.ALL_SCOPES)
        )
        assert scope_svc.SCOPE_WRITE in token["scope"].split()
        session = await mcp_session(client, token["access_token"])

        await _policy_setzen(
            fx.org_a.id,
            enabled=True,
            scopes=[scope_svc.SCOPE_READ],
            bereiche=list(areas.ALL_BEREICHE),
        )

        antwort = await call(
            client, token["access_token"], session,
            "tools/call",
            {"name": "konvoi_anlegen", "arguments": {"name": "Heimlicher Verband"}},
        )
        text = _fehlertext(antwort)
        assert "nur freigegeben" in text
        assert "Einstellung der Organisation" in text
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_werkzeugliste_zeigt_nur_das_freigegebene():
    """Ein Modell, das ein Werkzeug sieht, probiert es aus. Eine Absage nach
    dem Versuch ist eine schlechtere Auskunft als ein Werkzeug, das es in
    dieser Organisation nicht gibt."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token = await connect(client, fx.planer, fx.org_a)
        session = await mcp_session(client, token["access_token"])

        await _policy_setzen(
            fx.org_a.id,
            enabled=True,
            scopes=[scope_svc.SCOPE_READ],
            bereiche=[areas.BEREICH_KONVOIS, areas.BEREICH_ROUTEN],
        )

        listing = await call(client, token["access_token"], session, "tools/list")
        namen = {t["name"] for t in listing["result"]["tools"]}

        assert "konvois_auflisten" in namen
        assert "route_abrufen" in namen
        assert "organisation_details" in namen
        # Bereich gesperrt …
        assert "fahrzeuge_auflisten" not in namen
        # … und Schreiben nicht freigegeben.
        assert "konvoi_anlegen" not in namen
        assert "route_berechnen" not in namen
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_abgeschaltete_organisation_zeigt_keine_werkzeuge():
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token = await connect(client, fx.planer, fx.org_a)
        session = await mcp_session(client, token["access_token"])
        await _policy_setzen(fx.org_a.id, enabled=False, scopes=[], bereiche=[])

        listing = await call(client, token["access_token"], session, "tools/list")
        assert listing["result"]["tools"] == []
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_gesperrter_bereich_sperrt_auch_die_resource():
    """Resources sind kein Nebeneingang. Der Marschbefehl als PDF ist
    derselbe Konvoi wie in ``konvoi_details``."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token = await connect(client, fx.planer, fx.org_a)
        session = await mcp_session(client, token["access_token"])
        await _policy_setzen(
            fx.org_a.id,
            enabled=True,
            scopes=[scope_svc.SCOPE_READ],
            bereiche=[areas.BEREICH_FAHRZEUGE],
        )

        antwort = await call(
            client, token["access_token"], session,
            "resources/read",
            {"uri": f"convoyplan://konvoi/{fx.convoy_a.id}/marschbefehl.pdf"},
        )
        # Resources melden ihren Fehler als JSON-RPC-Fehler, nicht als
        # isError-Ergebnis — geprüft wird deshalb beides.
        text = str(antwort)
        assert "nicht für die KI-Schnittstelle freigegeben" in text
        await purge_clients([reg["client_id"]])


# ── Der Zustimmungsbildschirm ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_consent_bietet_eine_gesperrte_organisation_nicht_an():
    from tests.mcp_fixtures import authorize, pkce_pair, register_client

    async with seeded() as fx, mcp_app() as (_app, client):
        await _policy_setzen(fx.org_a.id, enabled=False, scopes=[], bereiche=[])

        reg = await register_client(client)
        _verifier, challenge = pkce_pair()
        ticket = await authorize(client, reg, challenge, list(scope_svc.ALL_SCOPES))

        bearer = convoyplan_access_token(fx.planer, fx.org_a)
        info = (
            await client.get(
                f"/api/mcp/consent?request={ticket}",
                headers={"Authorization": f"Bearer {bearer}"},
            )
        ).json()

        eintrag = next(o for o in info["organizations"] if o["id"] == str(fx.org_a.id))
        assert eintrag["mcp_enabled"] is False
        assert eintrag["grantable_scopes"] == []
        assert eintrag["optional_scopes"] == []
        # Die Organisation bleibt in der Liste: sie wegzulassen erzeugte die
        # Frage „wo ist meine Org hin?", auf die niemand eine Antwort fände.
        assert eintrag["name"] == fx.org_a.name

        # Und der Versuch, trotzdem zuzustimmen, endet mit 403.
        antwort = await client.post(
            "/api/mcp/consent",
            json={
                "request": ticket,
                "approve": True,
                "organization_id": str(fx.org_a.id),
                "scopes": list(scope_svc.ALL_SCOPES),
            },
            headers={"Authorization": f"Bearer {bearer}"},
        )
        assert antwort.status_code == 403, antwort.text
        assert "nicht freigegeben" in antwort.text
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_consent_erteilt_nie_mehr_als_die_organisation_freigibt():
    """Die Freigabe wirkt **nach** dem Ausschreiben der Hierarchie.

    ``effective()`` ergänzt, was ein Recht einschließt — und genau dort
    brächte ``convoy:write`` sonst ein ``fleet:status`` mit, das die
    Organisation nicht freigegeben hat."""
    async with seeded() as fx, mcp_app() as (_app, client):
        await _policy_setzen(
            fx.org_a.id,
            enabled=True,
            scopes=[scope_svc.SCOPE_READ, scope_svc.SCOPE_WRITE],
            bereiche=list(areas.ALL_BEREICHE),
        )
        reg, token = await connect(
            client, fx.planer, fx.org_a, scopes=list(scope_svc.ALL_SCOPES)
        )
        erteilt = token["scope"].split()
        assert scope_svc.SCOPE_WRITE in erteilt
        assert scope_svc.SCOPE_READ in erteilt
        assert scope_svc.SCOPE_FLEET_STATUS not in erteilt
        await purge_clients([reg["client_id"]])


# ── Die Einstellung im Org-Adminbereich ──────────────────────────────────


def _org_app(ctx):
    """Eine schlanke App nur mit dem Org-MCP-Router.

    Der Organisationskontext wird überschrieben, alles andere bleibt echt —
    insbesondere die Datenbank: geprüft werden soll, was in der Zeile landet,
    nicht was ein Mock behauptet."""
    from fastapi import FastAPI

    from app.api.deps import get_org_context
    from app.api.routes import org_mcp

    app = FastAPI()
    app.include_router(org_mcp.router, prefix="/api")
    app.dependency_overrides[get_org_context] = lambda: ctx
    return app


@pytest.mark.asyncio
async def test_org_admin_liest_und_setzt_die_freigabe():
    async with seeded() as fx:
        async with AsyncSessionLocal() as db:
            user = await db.get(type(fx.planer), fx.planer.id)
            org = await db.get(type(fx.org_a), fx.org_a.id)
            app = _org_app((user, org, "admin"))

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                vorher = (await client.get("/api/org/mcp")).json()
                assert vorher["enabled"] is True  # aus der Fixture
                assert vorher["basis_scope"] == scope_svc.SCOPE_READ
                # Die Auswahlmöglichkeiten kommen vom Server, damit ein neuer
                # Bereich im Portal erscheint, ohne dass jemand daran denkt.
                assert {b["wert"] for b in vorher["verfuegbare_bereiche"]} == set(
                    areas.ALL_BEREICHE
                )

                antwort = await client.put(
                    "/api/org/mcp",
                    json={
                        "enabled": True,
                        "scopes": [scope_svc.SCOPE_FLEET_STATUS],
                        "bereiche": [areas.BEREICH_STATUS],
                    },
                )
                assert antwort.status_code == 200, antwort.text
                nachher = antwort.json()
                # convoy:read kommt dazu, ohne dass es geschickt wurde.
                assert nachher["scopes"] == [
                    scope_svc.SCOPE_READ,
                    scope_svc.SCOPE_FLEET_STATUS,
                ]
                assert nachher["bereiche"] == [areas.BEREICH_STATUS]
                assert nachher["konfiguriert"] is True

        async with AsyncSessionLocal() as db:
            gespeichert = await org_mcp_policy.fuer_org(db, fx.org_a.id)
        assert gespeichert.bereiche == (areas.BEREICH_STATUS,)


@pytest.mark.asyncio
async def test_ohne_org_adminrechte_geht_nichts():
    """Planer genügt nicht. Wessen Daten herausgehen, entscheidet nicht, wer
    die Marschkolonnen plant."""
    async with seeded() as fx:
        async with AsyncSessionLocal() as db:
            user = await db.get(type(fx.planer), fx.planer.id)
            org = await db.get(type(fx.org_a), fx.org_a.id)
            app = _org_app((user, org, "planer"))

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                assert (await client.get("/api/org/mcp")).status_code == 403
                antwort = await client.put(
                    "/api/org/mcp",
                    json={"enabled": True, "scopes": [], "bereiche": []},
                )
                assert antwort.status_code == 403
                assert (
                    await client.get("/api/org/mcp/connections")
                ).status_code == 403


@pytest.mark.asyncio
async def test_verbindung_einer_fremden_organisation_laesst_sich_nicht_trennen():
    """Die Eingrenzung steht in der Abfrage, nicht dahinter: eine fremde
    ``family_id`` findet nichts, statt geladen und dann abgelehnt zu werden."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, _token = await connect(client, fx.planer, fx.org_b)

        async with AsyncSessionLocal() as db:
            from sqlalchemy import select

            from app.models.oauth_refresh_token import OAuthRefreshToken

            family_id = (
                await db.execute(
                    select(OAuthRefreshToken.family_id).where(
                        OAuthRefreshToken.organization_id == fx.org_b.id
                    )
                )
            ).scalars().first()
            assert family_id is not None

            user = await db.get(type(fx.planer), fx.planer.id)
            org_a = await db.get(type(fx.org_a), fx.org_a.id)
            app = _org_app((user, org_a, "admin"))

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as org_client:
                # Admin in A, Verbindung gehört zu B.
                antwort = await org_client.delete(
                    f"/api/org/mcp/connections/{family_id}"
                )
                assert antwort.status_code == 404
                # Und die Liste zeigt sie erst gar nicht.
                liste = (await org_client.get("/api/org/mcp/connections")).json()
                assert all(v["family_id"] != str(family_id) for v in liste)

        await purge_clients([reg["client_id"]])


def test_aktive_verbindung_heisst_im_portal_dasselbe_wie_hier():
    """Zwei Fassungen derselben Regel liefen unweigerlich auseinander.

    Der Org-Router kann ``admin.py`` nicht importieren, ohne die
    Abhängigkeiten in die falsche Richtung zu drehen — also steht die
    Bedingung zweimal da, und dieser Test hält sie zusammen."""
    from app.api.routes.admin import _active_connection_filter
    from app.api.routes.org_mcp import _aktive_verbindungen
    from app.models.oauth_refresh_token import OAuthRefreshToken

    portal = str(_active_connection_filter(OAuthRefreshToken))
    organisation = str(_aktive_verbindungen())
    assert portal == organisation
