"""Aktionsseite: hinaus geht genau die Positivliste, nichts sonst.

Die Antwort an den EventTracker ist öffentlich. Ein Feld, das jemand später
an ``nutzlast`` anhängt — ein Rufname „nur zur Anzeige", die Stärke „weil es
schön wäre" —, ginge ohne diesen Test still mit hinaus. Die Liste steht hier
ausgeschrieben; wer sie ändert, ändert sie bewusst und an dieser Stelle.

Sie ist zugleich der Vertrag mit dem zweiten Repository
(Convoyplan-EventTracker): was hier steht, darf der dort erwarten.
"""
import json
from datetime import datetime, timezone

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
