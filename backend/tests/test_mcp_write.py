"""Die schreibenden Werkzeuge des MCP-Servers.

Der Kern dieser Datei sind nicht die Erfolgsfälle — die stehen im Erfolgsfall
ohnehin in der Datenbank. Geprüft wird, was schiefgehen kann: dass eine Rolle
nicht mehr darf als sie darf, dass jeder Schreibaufruf eine Spur hinterlässt,
dass „entfernen" wirklich nur die Zuordnung löst, und dass ohne Lizenz gar
nichts Schreibendes angeboten wird.
"""
import pytest
from sqlalchemy import select

from app.mcp import READ_TOOLS, WRITE_TOOLS
from app.mcp import scopes as scope_svc
from app.models.audit_log import AuditLog
from app.models.convoy import Convoy, ConvoyVehicle
from app.models.vehicle import Vehicle
from app.models.waypoint import Waypoint
from app.database import AsyncSessionLocal
from tests.mcp_fixtures import (
    MCP_HEADERS,
    PROTOCOL_VERSION,
    call,
    connect,
    mcp_app,
    mcp_session,
    purge_clients,
    reset_db_engine,  # noqa: F401 — autouse-Fixture, per Import aktiviert
    seeded,
    tool_payload,
)

ALLE_SCOPES = list(scope_svc.ALL_SCOPES)


async def _sitzung(client, user, org, scopes=None):
    reg, token = await connect(client, user, org, scopes or ALLE_SCOPES)
    session = await mcp_session(client, token["access_token"])
    return reg, token["access_token"], session


async def _werkzeug(client, token, session, name, argumente):
    return await call(
        client, token, session, "tools/call", {"name": name, "arguments": argumente}
    )


async def _roh(client, token, session, name, argumente):
    """Derselbe Aufruf, aber die HTTP-Antwort statt des JSON-RPC-Ergebnisses.

    Nötig, seit die Step-up-Schicht (``mount.StepUpScopeMiddleware``) einen
    Aufruf mit zu schmalen Rechten schon vor dem Transport mit 403 beantwortet
    — dann gibt es gar kein Werkzeugergebnis mehr, in das man hineinsehen
    könnte."""
    return await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0", "id": 7, "method": "tools/call",
            "params": {"name": name, "arguments": argumente},
        },
        headers={
            **MCP_HEADERS,
            "Authorization": f"Bearer {token}",
            "mcp-session-id": session,
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        },
    )


# ── Schreiben mit ausreichender Rolle ────────────────────────────────────


@pytest.mark.asyncio
async def test_konvoi_anlegen_und_aendern():
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token, session = await _sitzung(client, fx.planer, fx.org_a)

        angelegt = tool_payload(
            await _werkzeug(client, token, session, "konvoi_anlegen", {
                "name": "Marschverband Süd", "start_lat": 48.1, "start_lon": 11.6,
            })
        )
        neue_id = angelegt["konvoi"]["id"]

        geaendert = tool_payload(
            await _werkzeug(client, token, session, "konvoi_aktualisieren", {
                "konvoi_id": neue_id, "auftrag": "Verlegung nach Norden",
                "funkgruppe": "BOS 4m 510",
            })
        )
        assert "auftrag" in geaendert["ergebnis"]

        async with AsyncSessionLocal() as db:
            convoy = await db.get(Convoy, __import__("uuid").UUID(neue_id))
            assert convoy.organization_id == fx.org_a.id
            assert convoy.auftrag == "Verlegung nach Norden"
            assert convoy.funkgruppe == "BOS 4m 510"
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_wegpunkt_anlegen_haengt_hinten_an():
    """Die Reihenfolge ist die Marschfolge — ein neuer Wegpunkt darf sich
    nicht vor die bestehenden drängen."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token, session = await _sitzung(client, fx.planer, fx.org_a)
        kid = str(fx.convoy_a.id)

        for name in ("Rastplatz Nord", "Tankstelle A9"):
            await _werkzeug(client, token, session, "wegpunkt_anlegen", {
                "konvoi_id": kid, "name": name, "lat": 48.2, "lon": 11.7,
            })

        liste = tool_payload(
            await _werkzeug(client, token, session, "wegpunkte_auflisten",
                            {"konvoi_id": kid})
        )
        assert [w["name"] for w in liste["wegpunkte"]] == [
            "Rastplatz Nord", "Tankstelle A9"
        ]
        assert [w["reihenfolge"] for w in liste["wegpunkte"]] == [0, 1]
        await purge_clients([reg["client_id"]])


# ── Die Ausnahme von der Löschregel ──────────────────────────────────────


@pytest.mark.asyncio
async def test_fahrzeug_aus_konvoi_entfernen_loest_nur_die_zuordnung():
    """Die schärfste Zusage dieses Werkzeugs: Fahrzeug und Konvoi überleben.

    Bräche das, wäre die Regel „kein Werkzeug löscht Daten" gebrochen, und
    zwar an der einzigen Stelle, an der sie überhaupt angreifbar ist."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token, session = await _sitzung(client, fx.planer, fx.org_a)

        antwort = tool_payload(
            await _werkzeug(client, token, session, "fahrzeug_aus_konvoi_entfernen", {
                "konvoi_id": str(fx.convoy_a.id), "fahrzeug_id": str(fx.vehicle_a.id),
            })
        )
        # Die Quittung muss benennen, was gelöst wurde — sonst merkt im
        # Gesprächsverlauf niemand einen versehentlichen Aufruf.
        assert "Florian 1" in antwort["fahrzeug"]
        assert "bleibt im Bestand" in antwort["ergebnis"]
        assert antwort["rueckgaengig_mit"] == "fahrzeug_zu_konvoi_hinzufuegen"

        async with AsyncSessionLocal() as db:
            assert await db.get(Vehicle, fx.vehicle_a.id) is not None
            assert await db.get(Convoy, fx.convoy_a.id) is not None
            zuordnung = (
                await db.execute(
                    select(ConvoyVehicle).where(
                        ConvoyVehicle.convoy_id == fx.convoy_a.id,
                        ConvoyVehicle.vehicle_id == fx.vehicle_a.id,
                    )
                )
            ).scalar_one_or_none()
            assert zuordnung is None, "die Zuordnung hätte gelöst sein müssen"
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_entfernen_ist_mit_hinzufuegen_umkehrbar():
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token, session = await _sitzung(client, fx.planer, fx.org_a)
        kid, fid = str(fx.convoy_a.id), str(fx.vehicle_a.id)

        await _werkzeug(client, token, session, "fahrzeug_aus_konvoi_entfernen",
                        {"konvoi_id": kid, "fahrzeug_id": fid})
        await _werkzeug(client, token, session, "fahrzeug_zu_konvoi_hinzufuegen",
                        {"konvoi_id": kid, "fahrzeug_id": fid})

        status = tool_payload(
            await _werkzeug(client, token, session, "konvoi_status", {"konvoi_id": kid})
        )
        assert [f["fahrzeug_id"] for f in status["fahrzeuge"]] == [fid]
        await purge_clients([reg["client_id"]])


# ── Rollen und Scopes ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_beobachter_darf_nicht_schreiben():
    """Die Rolle deckelt, was das Token kann — auch wenn der Client alles
    angefragt hat."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token, session = await _sitzung(client, fx.beobachter, fx.org_a)

        # Ein Beobachter bekommt convoy:write gar nicht erst zugeteilt
        # (scopes.grantable), der Aufruf scheitert also schon an der
        # Step-up-Schicht — und die antwortet protokollgerecht mit 403 und
        # der Challenge, statt mit einem Werkzeugfehler.
        antwort = await _roh(client, token, session, "konvoi_anlegen",
                             {"name": "Sollte nicht entstehen"})
        assert antwort.status_code == 403, antwort.text
        assert scope_svc.SCOPE_WRITE in antwort.headers["www-authenticate"]

        async with AsyncSessionLocal() as db:
            treffer = (
                await db.execute(
                    select(Convoy).where(Convoy.name == "Sollte nicht entstehen")
                )
            ).scalar_one_or_none()
            assert treffer is None
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_nur_lese_scope_reicht_fuer_status_nicht():
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token, session = await _sitzung(
            client, fx.planer, fx.org_a, [scope_svc.SCOPE_READ]
        )
        antwort = await _roh(client, token, session, "fahrzeugstatus_setzen", {
            "konvoi_id": str(fx.convoy_a.id), "fahrzeug_id": str(fx.vehicle_a.id),
            "status": "en_route",
        })
        assert antwort.status_code == 403, antwort.text
        assert scope_svc.SCOPE_FLEET_STATUS in antwort.headers["www-authenticate"]
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_fremder_konvoi_laesst_sich_nicht_beschreiben():
    """Mandantentrennung gilt schreibend genauso wie lesend."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token, session = await _sitzung(client, fx.planer, fx.org_a)
        antwort = await _werkzeug(client, token, session, "konvoi_aktualisieren", {
            "konvoi_id": str(fx.convoy_b.id), "auftrag": "Fremdzugriff",
        })
        assert antwort["result"]["isError"] is True

        async with AsyncSessionLocal() as db:
            fremd = await db.get(Convoy, fx.convoy_b.id)
            assert fremd.auftrag != "Fremdzugriff"
        await purge_clients([reg["client_id"]])


# ── Audit ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_schreibaufruf_hinterlaesst_genau_eine_spur():
    """Wer später nachvollziehen muss, wie eine Kolonne zu ihrem Auftrag kam,
    muss sehen, dass hier ein Modell gehandelt hat — und über welchen Client."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token, session = await _sitzung(client, fx.planer, fx.org_a)
        await _werkzeug(client, token, session, "konvoi_aktualisieren", {
            "konvoi_id": str(fx.convoy_a.id), "auftrag": "Nachweisbar",
        })

        async with AsyncSessionLocal() as db:
            eintraege = (
                await db.execute(
                    select(AuditLog).where(
                        AuditLog.org_id == fx.org_a.id, AuditLog.action == "mcp.tool.call"
                    )
                )
            ).scalars().all()
        assert len(eintraege) == 1
        eintrag = eintraege[0]
        assert eintrag.detail["source"] == "mcp"
        assert eintrag.detail["tool"] == "konvoi_aktualisieren"
        assert eintrag.detail["client_id"] == reg["client_id"]
        assert eintrag.actor_id == fx.planer.id
        assert eintrag.target_id == str(fx.convoy_a.id)
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_lesender_aufruf_hinterlaesst_keine_spur():
    """Sonst wäre das Audit-Log nach einer Woche Modellbetrieb unlesbar."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token, session = await _sitzung(client, fx.planer, fx.org_a)
        await _werkzeug(client, token, session, "konvois_auflisten", {})

        async with AsyncSessionLocal() as db:
            # Auf die Werkzeug-Aktion filtern: die erteilte Zustimmung schreibt
            # ebenfalls einen Eintrag, und das ist richtig so — sie ist eine
            # Rechteerteilung, kein Werkzeugaufruf.
            anzahl = len(
                (
                    await db.execute(
                        select(AuditLog).where(
                            AuditLog.org_id == fx.org_a.id,
                            AuditLog.action == "mcp.tool.call",
                        )
                    )
                ).scalars().all()
            )
        assert anzahl == 0
        await purge_clients([reg["client_id"]])


# ── Lizenz ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ohne_lizenz_werden_schreibende_werkzeuge_nicht_angeboten(monkeypatch):
    """Ein Modell, das ein Werkzeug sieht, probiert es aus. Eine Absage nach
    dem Versuch ist die schlechtere Auskunft als ein Werkzeug, das es in
    dieser Betriebsart gar nicht gibt."""
    import app.mcp.mount as mount

    async def _keine_lizenz() -> bool:
        return False

    monkeypatch.setattr(mount, "is_licensed", _keine_lizenz)

    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token, session = await _sitzung(client, fx.planer, fx.org_a)
        listing = await call(client, token, session, "tools/list")
        namen = {t["name"] for t in listing["result"]["tools"]}
        assert namen == set(READ_TOOLS)
        assert not (namen & set(WRITE_TOOLS))
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_mit_lizenz_sind_alle_werkzeuge_da():
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token, session = await _sitzung(client, fx.planer, fx.org_a)
        listing = await call(client, token, session, "tools/list")
        namen = {t["name"] for t in listing["result"]["tools"]}
        assert namen == set(READ_TOOLS) | set(WRITE_TOOLS)
        await purge_clients([reg["client_id"]])


# ── Kontingente ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_aufrufgrenze_je_verbindung_greift(monkeypatch):
    """Ein Modell in einer Schleife ist ein realistisches Lastprofil."""
    from app.config import settings
    from app.services import rate_limit

    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "mcp_tool_calls_per_minute", 3)
    rate_limit.reset()
    try:
        async with seeded() as fx, mcp_app() as (_app, client):
            reg, token, session = await _sitzung(client, fx.planer, fx.org_a)
            fehler = None
            for _ in range(6):
                antwort = await _werkzeug(client, token, session, "konvois_auflisten", {})
                if antwort["result"].get("isError"):
                    fehler = antwort["result"]["content"][0]["text"]
                    break
            assert fehler is not None, "die Aufrufgrenze hat nicht gegriffen"
            assert "Schleife" in fehler, "die Meldung sagt dem Modell nicht, was zu tun ist"
            await purge_clients([reg["client_id"]])
    finally:
        rate_limit.reset()


@pytest.mark.asyncio
async def test_routing_kontingent_nutzt_dieselbe_einstellung(monkeypatch):
    """Zwei Zahlenwelten für dasselbe Kontingent wären eine Einladung zum
    Auseinanderlaufen."""
    from app.config import settings
    from app.services import rate_limit

    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "quota_routing_per_hour", 1)
    rate_limit.reset()
    try:
        async with seeded() as fx, mcp_app() as (_app, client):
            reg, token, session = await _sitzung(client, fx.planer, fx.org_a)
            kid = str(fx.convoy_a.id)
            # Zweimal aufrufen. Der erste Versuch scheitert fachlich (kein
            # Start-/Zielpunkt), verbraucht aber das Kontingent — genau wie
            # an der REST-API, wo die Dependency vor dem Handler zählt.
            await _werkzeug(client, token, session, "route_berechnen", {"konvoi_id": kid})
            zweiter = await _werkzeug(
                client, token, session, "route_berechnen", {"konvoi_id": kid}
            )
            text = zweiter["result"]["content"][0]["text"]
            assert "Kontingent" in text and "routing" in text
            await purge_clients([reg["client_id"]])
    finally:
        rate_limit.reset()


# ── Resources und Prompt ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resources_und_prompt_sind_angemeldet():
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token, session = await _sitzung(client, fx.planer, fx.org_a)
        vorlagen = await call(client, token, session, "resources/templates/list")
        uris = {t["uriTemplate"] for t in vorlagen["result"]["resourceTemplates"]}
        assert "convoyplan://konvoi/{konvoi_id}/marschbefehl.pdf" in uris

        prompts = await call(client, token, session, "prompts/list")
        assert "marschbefehl_erstellen" in {p["name"] for p in prompts["result"]["prompts"]}
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_resource_eines_fremden_konvois_bleibt_verschlossen():
    """Eine Resource ist kein Nebeneingang an den Zugriffsprüfungen vorbei."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token, session = await _sitzung(client, fx.planer, fx.org_a)
        antwort = await call(client, token, session, "resources/read", {
            "uri": f"convoyplan://konvoi/{fx.convoy_b.id}/konvoi.json"
        })
        assert "error" in antwort or antwort.get("result", {}).get("isError")
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_konvoi_json_resource_liefert_den_eigenen_konvoi():
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token, session = await _sitzung(client, fx.planer, fx.org_a)
        antwort = await call(client, token, session, "resources/read", {
            "uri": f"convoyplan://konvoi/{fx.convoy_a.id}/konvoi.json"
        })
        inhalt = antwort["result"]["contents"][0]["text"]
        assert fx.convoy_a.name in inhalt
        await purge_clients([reg["client_id"]])


# ── Die Positivliste, jetzt mit Schreibwerkzeugen ────────────────────────


@pytest.mark.asyncio
async def test_kein_werkzeug_loescht_einen_datensatz():
    """Gegenprobe zur Positivliste: das einzige Werkzeug, dessen Name nach
    Löschen klingt, ist `fahrzeug_aus_konvoi_entfernen` — und dessen
    Verhalten ist oben eigens geprüft."""
    verdaechtig = [
        n for n in READ_TOOLS + WRITE_TOOLS
        if "loesch" in n or "delete" in n or "entfern" in n
    ]
    assert verdaechtig == ["fahrzeug_aus_konvoi_entfernen"]


@pytest.mark.asyncio
async def test_wegpunkte_bleiben_beim_umsortieren_vollstaendig():
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token, session = await _sitzung(client, fx.planer, fx.org_a)
        kid = str(fx.convoy_a.id)
        for name in ("A", "B", "C"):
            await _werkzeug(client, token, session, "wegpunkt_anlegen", {
                "konvoi_id": kid, "name": name, "lat": 48.0, "lon": 11.0,
            })
        liste = tool_payload(
            await _werkzeug(client, token, session, "wegpunkte_auflisten",
                            {"konvoi_id": kid})
        )
        ids = [w["id"] for w in liste["wegpunkte"]]
        await _werkzeug(client, token, session, "wegpunkte_umsortieren", {
            "konvoi_id": kid, "wegpunkt_ids_in_reihenfolge": list(reversed(ids)),
        })
        danach = tool_payload(
            await _werkzeug(client, token, session, "wegpunkte_auflisten",
                            {"konvoi_id": kid})
        )
        assert [w["name"] for w in danach["wegpunkte"]] == ["C", "B", "A"]

        async with AsyncSessionLocal() as db:
            anzahl = len(
                (
                    await db.execute(
                        select(Waypoint).where(Waypoint.convoy_id == fx.convoy_a.id)
                    )
                ).scalars().all()
            )
        assert anzahl == 3, "beim Umsortieren darf kein Wegpunkt verlorengehen"
        await purge_clients([reg["client_id"]])


# ── Mannschaftsstärke ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_staerke_melden_schreibt_und_rechnet_die_gesamtzahl():
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token, session = await _sitzung(client, fx.planer, fx.org_a)
        antwort = await _werkzeug(client, token, session, "fahrzeugstaerke_melden", {
            "konvoi_id": str(fx.convoy_a.id), "fahrzeug_id": str(fx.vehicle_a.id),
            "fuehrer": 0, "unterfuehrer": 1, "mannschaften": 8,
        })
        assert tool_payload(antwort)["gesamt"] == 9

        async with AsyncSessionLocal() as db:
            cv = await db.get(ConvoyVehicle, (fx.convoy_a.id, fx.vehicle_a.id))
            assert (cv.staerke_ist_fuehrer, cv.staerke_ist_unterfuehrer, cv.staerke_ist_mannschaften) == (0, 1, 8)
            assert cv.staerke_gemeldet_at is not None
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_nur_lese_scope_reicht_fuer_die_staerke_nicht():
    """Eine Stärkemeldung ist dasselbe wie eine Statusmeldung: sie ändert die
    Lage, die die Führung sieht. Lesen allein trägt das nicht."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token, session = await _sitzung(
            client, fx.planer, fx.org_a, [scope_svc.SCOPE_READ]
        )
        antwort = await _roh(client, token, session, "fahrzeugstaerke_melden", {
            "konvoi_id": str(fx.convoy_a.id), "fahrzeug_id": str(fx.vehicle_a.id),
            "fuehrer": 0, "unterfuehrer": 1, "mannschaften": 8,
        })
        assert antwort.status_code == 403, antwort.text
        assert scope_svc.SCOPE_FLEET_STATUS in antwort.headers["www-authenticate"]
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_unplausible_staerke_wird_abgewiesen():
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token, session = await _sitzung(client, fx.planer, fx.org_a)
        antwort = await _werkzeug(client, token, session, "fahrzeugstaerke_melden", {
            "konvoi_id": str(fx.convoy_a.id), "fahrzeug_id": str(fx.vehicle_a.id),
            "fuehrer": 0, "unterfuehrer": 1, "mannschaften": 500,
        })
        assert antwort["result"]["isError"] is True
        # Sonst wäre der Test auch grün, solange es das Werkzeug gar nicht gibt.
        listing = await call(client, token, session, "tools/list")
        assert "fahrzeugstaerke_melden" in {t["name"] for t in listing["result"]["tools"]}

        async with AsyncSessionLocal() as db:
            cv = await db.get(ConvoyVehicle, (fx.convoy_a.id, fx.vehicle_a.id))
            assert cv.staerke_ist_mannschaften is None
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_konvoi_status_haelt_ungemeldet_und_unbesetzt_auseinander():
    """Die Zusage aus der Oberfläche, noch einmal für das Modell: ein
    schweigendes Fahrzeug darf nicht als Null-Besatzung herauskommen."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token, session = await _sitzung(client, fx.planer, fx.org_a)

        vorher = tool_payload(
            await _werkzeug(client, token, session, "konvoi_status", {
                "konvoi_id": str(fx.convoy_a.id),
            })
        )
        assert vorher["fahrzeuge"][0]["staerke"]["ist"] is None
        assert vorher["fahrzeuge"][0]["staerke"]["gesamt"] is None
        assert vorher["staerke"]["offen"] == 1
        assert vorher["staerke"]["gesamt"] is None

        await _werkzeug(client, token, session, "fahrzeugstaerke_melden", {
            "konvoi_id": str(fx.convoy_a.id), "fahrzeug_id": str(fx.vehicle_a.id),
            "fuehrer": 0, "unterfuehrer": 0, "mannschaften": 0,
        })

        nachher = tool_payload(
            await _werkzeug(client, token, session, "konvoi_status", {
                "konvoi_id": str(fx.convoy_a.id),
            })
        )
        # Unbesetzt gemeldet: eine Aussage, keine fehlende Meldung.
        assert nachher["fahrzeuge"][0]["staerke"]["ist"] == "0/0/0"
        assert nachher["fahrzeuge"][0]["staerke"]["gesamt"] == 0
        assert nachher["staerke"]["offen"] == 0
        assert nachher["staerke"]["gesamt"] == 0
        await purge_clients([reg["client_id"]])
