"""Aktionsseite: hinaus geht genau die Positivliste, nichts sonst.

Die Antwort an den EventTracker ist öffentlich. Ein Feld, das jemand später
an ``nutzlast`` anhängt — ein Rufname „nur zur Anzeige", die Stärke „weil es
schön wäre" —, ginge ohne diesen Test still mit hinaus. Die Liste steht hier
ausgeschrieben; wer sie ändert, ändert sie bewusst und an dieser Stelle.

Sie ist zugleich der Vertrag mit dem zweiten Repository
(Convoyplan-EventTracker): was hier steht, darf der dort erwarten.
"""
import json
from datetime import datetime, timedelta, timezone

from app.api.routes import aktionsseite as routen
from tests.aktionsseite_fixtures import (  # noqa: F401 — Fixtures, per Import aktiviert
    GEHEIMER_KONVOINAME,
    RUFNAME,
    TELEFON,
    aktion,
    client,
    fahrt,
    h,
    reset_db_engine,
    seite_anlegen,
    verlauf,
)

POSITIVLISTE = {
    "OeffentlicheAktion": {
        "title", "subtitle", "facts", "theme", "delay_minutes", "as_of",
        "generated_at", "valid_until", "convoys",
    },
    "OeffentlicherKonvoi": {
        "key", "name", "destination", "destination_point", "color", "status",
        "position", "trail", "driven_km", "total_km",
    },
    "OeffentlichePosition": {"lat", "lon", "coarse", "at"},
    "OeffentlicherPunkt": {"lat", "lon"},
}


def test_schema_ist_die_positivliste():
    for name, felder in POSITIVLISTE.items():
        modell = getattr(routen, name)
        assert set(modell.model_fields) == felder, name
        # Ein zusätzliches Feld lässt die Antwort scheitern, statt hinauszugehen.
        assert modell.model_config.get("extra") == "forbid", name


async def test_antwort_enthaelt_nichts_aus_dem_einsatz(aktion, client):
    seite = await seite_anlegen(client, aktion)
    await verlauf(aktion, fahrt(aktion.spitze, datetime.now(timezone.utc), 240))
    r = await client.get(f"/api/public/aktion/{seite['slug']}", headers=h(seite["fetch_token"]))
    assert r.status_code == 200, r.text
    text = r.text
    for geheim in (
        GEHEIMER_KONVOINAME, RUFNAME, TELEFON,
        str(aktion.convoy_id), str(aktion.spitze), str(aktion.schluss), str(aktion.org_id),
        seite["id"], seite["fetch_token"],
    ):
        assert geheim not in text, geheim
    k = json.loads(text)["convoys"][0]
    assert (k["key"], k["name"], k["destination"]) == ("1", "Konvoi Bosnien", "Tuzla")


async def test_zielpunkt_nur_auf_wunsch_und_nur_grob(aktion, client):
    seite = await seite_anlegen(client, aktion)
    r = await client.get(f"/api/public/aktion/{seite['slug']}", headers=h(seite["fetch_token"]))
    assert r.json()["convoys"][0]["destination_point"] is None


async def test_eigener_zielpunkt_schlaegt_den_letzten_wegpunkt(aktion, client):
    """Der letzte Wegpunkt ist oft nur die Fähre. Shkodra statt Bari."""
    from app.services import aktionsseite as a

    shkodra = {"lat": 42.0683, "lon": 19.5126}
    seite = await seite_anlegen(
        client,
        aktion,
        show_destination=True,
        convoys=[{
            "convoy_id": str(aktion.convoy_id), "display_name": "Konvoi Albanien",
            "destination_label": "Shkodra", "destination_point": shkodra,
        }],
    )
    # Die Verwaltung gibt ihn zurück, wie er gesetzt wurde …
    assert seite["convoys"][0]["destination_point"] == shkodra
    # … hinaus geht er grob, wie jeder Zielpunkt.
    r = await client.get(f"/api/public/aktion/{seite['slug']}", headers=h(seite["fetch_token"]))
    zlat, zlon = a.vergroebern(shkodra["lat"], shkodra["lon"])
    assert r.json()["convoys"][0]["destination_point"] == {"lat": zlat, "lon": zlon}

    # Ohne Haken bleibt er drinnen.
    r = await client.put(
        f"/api/org/aktionsseiten/{seite['id']}",
        json={
            "title": "Weihnachtskonvois 2026", "theme": "weihnachten", "delay_minutes": 120,
            "show_destination": False,
            "convoys": [{
                "convoy_id": str(aktion.convoy_id), "display_name": "Konvoi Albanien",
                "destination_point": shkodra,
            }],
        },
        headers=h(aktion.admin),
    )
    assert r.status_code == 200, r.text
    r = await client.get(f"/api/public/aktion/{seite['slug']}", headers=h(seite["fetch_token"]))
    assert r.json()["convoys"][0]["destination_point"] is None


async def test_angekommen_heisst_am_eigenen_zielpunkt(aktion, client):
    """Wer an der Fähre steht, ist nicht angekommen — nur wer am Ziel steht."""
    jetzt = datetime.now(timezone.utc)
    ende = jetzt - timedelta(minutes=150)
    punkte = fahrt(aktion.spitze, ende, 60)
    _, _, lat, lon = punkte[-1]
    stehen = [(aktion.spitze, ende + timedelta(minutes=m), lat, lon) for m in range(5, 146, 5)]
    await verlauf(aktion, punkte + stehen)
    seite = await seite_anlegen(
        client,
        aktion,
        convoys=[{
            "convoy_id": str(aktion.convoy_id), "display_name": "Konvoi Bosnien",
            "destination_point": {"lat": lat, "lon": lon + 0.01},
        }],
    )
    r = await client.get(f"/api/public/aktion/{seite['slug']}", headers=h(seite["fetch_token"]))
    assert r.json()["convoys"][0]["status"] == "angekommen"


async def test_halber_zielpunkt_wird_abgewiesen(aktion, client):
    r = await client.post(
        "/api/org/aktionsseiten",
        json={
            "title": "x", "convoys": [{
                "convoy_id": str(aktion.convoy_id), "display_name": "K",
                "destination_point": {"lat": 42.0},
            }],
        },
        headers=h(aktion.admin),
    )
    assert r.status_code == 422
