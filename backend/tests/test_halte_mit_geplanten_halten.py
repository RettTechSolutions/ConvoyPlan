"""Halte-Empfehlung rechnet mit den Halten, die schon als Wegpunkt stehen.

Gemeldet: Ein Technischer Halt wurde wenige Kilometer hinter einem bereits
eingeplanten Tankhalt vorgeschlagen — zwei Stopps kurz hintereinander. Ein
geplanter Halt zählt jetzt wie ein TH, ein TH kurz davor geht in ihm auf,
und ein übernommener Vorschlag verschwindet aus der Liste.
"""
from app.services.fuel import (
    BREAK_DURATION_MIN,
    HALT_MERGE_WINDOW_S,
    TH_INTERVAL_S,
    _duration_halts,
    analyse_fuel,
)

# 64 km/h Marschgeschwindigkeit: 1 h Lenkzeit = 64 km
KMH = 64


def _km(stunden: float) -> float:
    return stunden * KMH


def _halts(stunden: float, geplant=(), fahrzeuge: int = 3):
    return _duration_halts(_km(stunden), stunden * 3600, [], fahrzeuge, list(geplant))


def test_ohne_geplante_halte_unveraendert():
    assert [h["kind"] for h in _halts(5)] == ["tech", "break"]


def test_th_kurz_vor_tankhalt_geht_in_ihm_auf():
    """Der gemeldete Fall: TH bei 2:00, Tankhalt bei 2:10 → kein eigener TH."""
    tankhalt_km = _km(2 + 10 / 60)
    halts = _halts(5, [(tankhalt_km, 20)])
    assert not [h for h in halts if h["kind"] == "tech" and abs(h["stop_km"] - tankhalt_km) < _km(0.5)]
    # Die Lenkpause bleibt fällig — ein 20-min-Tankhalt ersetzt sie nicht.
    assert [h["kind"] for h in halts] == ["break"]


def test_th_kurz_nach_tankhalt_entfaellt_ebenfalls():
    """Der Tankhalt kommt vor dem fälligen TH: das Intervall läuft danach neu an."""
    tankhalt_km = _km(1 + 50 / 60)
    halts = _halts(6, [(tankhalt_km, 20)])
    tech = [h for h in halts if h["kind"] == "tech"]
    assert all(h["after_drive_s"] >= (1 + 50 / 60) * 3600 + TH_INTERVAL_S - 1 for h in tech)


def test_geplanter_halt_weit_hinter_dem_th_ersetzt_ihn_nicht():
    """Liegt der geplante Halt mehr als das Fenster hinter dem TH, bleibt der TH."""
    spaeter = 2 + (HALT_MERGE_WINDOW_S + 15 * 60) / 3600
    halts = _halts(5, [(_km(spaeter), 20)])
    assert halts[0]["kind"] == "tech"
    assert halts[0]["after_drive_s"] == TH_INTERVAL_S


def test_frueher_geplanter_halt_verschiebt_das_intervall():
    halts = _halts(5, [(_km(1), 15)])
    assert halts[0]["after_drive_s"] == 3 * 3600


def test_lenkpause_kurz_nach_geplantem_halt_wird_an_ihn_gelegt():
    """Früher ist bei Lenkzeiten immer zulässig: die Pause rückt an den Halt."""
    halt_bei = 4 + 10 / 60
    halts = _halts(8, [(_km(2), 15), (_km(halt_bei), 20)])
    pausen = [h for h in halts if h["kind"] == "break"]
    assert pausen[0]["stop_km"] == round(_km(halt_bei), 1)
    assert pausen[0]["duration_min"] == BREAK_DURATION_MIN
    # und kein zweiter Stopp kurz dahinter
    danach = [h for h in halts if h["after_drive_s"] > halt_bei * 3600]
    assert all(h["after_drive_s"] - halt_bei * 3600 >= TH_INTERVAL_S - 1 for h in danach)


def test_langer_geplanter_halt_ersetzt_die_lenkpause():
    halts = _halts(5, [(_km(2), 15), (_km(4), BREAK_DURATION_MIN)])
    assert halts == []


def test_uebernommene_vorschlaege_verschwinden_aus_der_liste():
    """Jeder Vorschlag als Wegpunkt übernommen → nichts mehr zu empfehlen."""
    for stunden, fahrzeuge in [(5, 3), (10, 9), (25, 3), (14, 6)]:
        vorschlaege = _halts(stunden, fahrzeuge=fahrzeuge)
        assert vorschlaege
        uebernommen = [(h["stop_km"], h["duration_min"]) for h in vorschlaege]
        assert _halts(stunden, uebernommen, fahrzeuge) == [], (stunden, fahrzeuge)


def test_teilweise_uebernommen_laesst_den_rest_stehen():
    vorschlaege = _halts(25)
    erster = vorschlaege[0]
    rest = _halts(25, [(erster["stop_km"], erster["duration_min"])])
    assert rest == vorschlaege[1:]


def test_analyse_reicht_geplante_halte_durch():
    route_km = _km(5)
    ohne = analyse_fuel([], route_km * 1000, [], route_duration_s=5 * 3600)
    mit = analyse_fuel([], route_km * 1000, [], route_duration_s=5 * 3600,
                       geplante_halte=[(_km(2), 15), (_km(4), BREAK_DURATION_MIN)])
    assert ohne["duration_halt_needed"] is True
    assert mit["duration_halt_needed"] is False
    assert mit["duration_halts"] == []


# ── Vermerk: was zusammengelegt wurde, geht nicht verloren ───────────────────
#
# „Tankhalt + TH": Die WOLKE-Prüfung entfällt nicht, sie findet am Tankhalt
# statt. Das muss am Wegpunkt stehen — auf dem Schirm und auf dem Ausdruck.

import uuid  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402

from app.services import pdf as pdf_svc  # noqa: E402
from app.services import roadbook  # noqa: E402
from app.services.fuel import halteplan  # noqa: E402


def _plan(stunden: float, geplant=(), fahrzeuge: int = 3):
    return halteplan(_km(stunden), stunden * 3600, [], fahrzeuge, list(geplant))


def test_tankhalt_traegt_den_aufgegangenen_th():
    halts, zusammen = _plan(5, [(_km(2 + 10 / 60), 20, "tank")], fahrzeuge=6)
    assert zusammen == [{"waypoint_id": "tank", "kind": "tech", "duration_min": 30, "faellig_km": _km(2)}]
    assert [h["kind"] for h in halts] == ["break"]


def test_auch_ein_tankhalt_kurz_vor_dem_th_traegt_ihn():
    _, zusammen = _plan(5, [(_km(1 + 45 / 60), 20, "tank")])
    assert [z["waypoint_id"] for z in zusammen] == ["tank"]


def test_ein_viel_frueherer_halt_ersetzt_nichts():
    """Er setzt das Intervall zurück, aber kein fälliger Halt ging in ihm auf."""
    _, zusammen = _plan(5, [(_km(1), 15, "frueh")])
    assert zusammen == []


def test_zu_kurzer_halt_ersetzt_keine_lenkpause_und_traegt_sie_nicht():
    halt_bei = 4 + 10 / 60
    halts, zusammen = _plan(8, [(_km(2), 15, "th"), (_km(halt_bei), 20, "tank")])
    assert "tank" not in [z["waypoint_id"] for z in zusammen]
    assert any(h["kind"] == "break" and h["stop_km"] == round(_km(halt_bei), 1) for h in halts)


def test_langer_halt_traegt_die_lenkpause():
    _, zusammen = _plan(5, [(_km(2), 15, "th"), (_km(4 + 20 / 60), 45, "rast")])
    assert {z["waypoint_id"]: z["kind"] for z in zusammen} == {"th": "tech", "rast": "break"}


def test_uebernommener_vorschlag_ist_kein_zusammengelegter():
    """Ein Vorschlag an seiner eigenen Stelle ist er selbst — der Vermerk
    stünde trotzdem richtig da („zugleich Technischer Halt“)."""
    vorschlaege = _halts(5)
    _, zusammen = _plan(5, [(h["stop_km"], h["duration_min"], f"v{i}") for i, h in enumerate(vorschlaege)])
    assert [z["kind"] for z in zusammen] == [h["kind"] for h in vorschlaege]


@pytest.mark.parametrize(("eintraege", "halt", "text"), [
    ([{"kind": "tech", "duration_min": 30}], 20, "zugleich Technischer Halt (WOLKE), empfohlen 30 min"),
    ([{"kind": "tech", "duration_min": 15}], 20, "zugleich Technischer Halt (WOLKE)"),
    ([{"kind": "break", "duration_min": 45}], 45, "zugleich Lenkpause"),
    ([], 20, ""),
    (None, 20, ""),
])
def test_vermerk_text(eintraege, halt, text):
    assert pdf_svc.halt_vermerk(eintraege, halt) == text


def test_roadbook_nennt_den_th_am_tankhalt():
    tank = SimpleNamespace(
        id=uuid.uuid4(), name="Raststätte Pfefferhöhe", type="technical_stop",
        planned_arrival=None, planned_departure=None, hold_duration_min=20,
        halt_purpose="fuel", notes=None,
    )
    anweisungen = roadbook.link_waypoints([
        {"sign": 0, "text": "Weiter auf A 5", "distance_m": 1000.0},
        {"sign": 5, "text": "Wegpunkt 1 erreicht", "distance_m": 0.0},
        {"sign": 4, "text": "Ziel erreicht!", "distance_m": 0.0},
    ], [str(tank.id)])
    zeilen = roadbook.build_rows(
        anweisungen, [tank], None, {str(tank.id): [{"kind": "tech", "duration_min": 30}]},
    )
    assert "20 min Halt (Betriebsstoff)" in zeilen[1].detail
    assert "zugleich Technischer Halt (WOLKE), empfohlen 30 min" in zeilen[1].detail


def test_marschbefehl_nennt_den_th_unter_dem_tankhalt(monkeypatch):
    texte: list[str] = []
    cell = pdf_svc._PDF.cell

    def _cell(self, w=None, h=None, text="", *a, **k):
        texte.append(str(text))
        return cell(self, w, h, text, *a, **k)

    monkeypatch.setattr(pdf_svc._PDF, "cell", _cell)
    konvoi = SimpleNamespace(
        name="Konvoi", organization=None, start_time=None, lage=None, auftrag=None,
        marschform=None, ablaufpunkt=None, ablaufzeit=None, ablaufführer=None,
        versorgung=None, funkgruppe=None, anlagen=None, speed_urban_kmh=40, speed_rural_kmh=65,
    )
    wegpunkte = [{
        "lat": 50.7, "lon": 9.3, "name": "Raststätte Pfefferhöhe", "type": "technical_stop",
        "notes": None, "halt_purpose": "fuel", "hold_duration_min": 20,
        "planned_arrival": None, "planned_departure": None,
        "zusammengelegt": [{"kind": "tech", "duration_min": 30}],
    }]
    assert pdf_svc.generate_marschbefehl(konvoi, wegpunkte, [], None).startswith(b"%PDF-")
    assert any("zugleich Technischer Halt (WOLKE), empfohlen 30 min" in t for t in texte)


def test_uebernommener_th_traegt_keinen_vermerk_der_tankhalt_schon(monkeypatch):
    """Durch die App: der Tankhalt bekommt „+ TH“, ein übernommener TH-Vorschlag
    nicht „zugleich Technischer Halt“ an sich selbst."""
    from app.api.routes import routing

    # Gerade Strecke nach Osten; die Lage eines Wegpunkts ist sein km.
    coords = [[9.0 + i * 0.01, 50.0] for i in range(1000)]
    lage = {}

    def _latlon(wp):
        return lage.get(wp.id)

    monkeypatch.setattr(routing, "_waypoint_latlon", _latlon)
    route_m = routing.fuel_svc.haversine_m(9.0, 50.0, coords[-1][0], 50.0)
    dauer_s = 5 * 3600

    def _bei(stunden):
        return (50.0, 9.0 + (coords[-1][0] - 9.0) * stunden * 3600 / dauer_s)

    tank = SimpleNamespace(id=uuid.uuid4(), type="technical_stop", halt_purpose="fuel", hold_duration_min=20)
    th = SimpleNamespace(id=uuid.uuid4(), type="technical_stop", halt_purpose=None, hold_duration_min=15)
    lage[tank.id] = _bei(2 + 10 / 60)
    konvoi = SimpleNamespace(waypoints=[tank], convoy_vehicles=[])
    analyse = routing._halteanalyse(konvoi, route_m, coords, dauer_s)
    assert [(z["waypoint_id"], z["kind"]) for z in analyse["zusammengelegt"]] == [(str(tank.id), "tech")]

    # Ohne Tankhalt, mit übernommenem Vorschlag an seiner Stelle: kein Vermerk.
    lage[th.id] = _bei(2)
    konvoi = SimpleNamespace(waypoints=[th], convoy_vehicles=[])
    analyse = routing._halteanalyse(konvoi, route_m, coords, dauer_s)
    assert analyse["zusammengelegt"] == []
    assert all(h["kind"] != "tech" or h["after_drive_s"] > 2 * 3600 for h in analyse["duration_halts"])
