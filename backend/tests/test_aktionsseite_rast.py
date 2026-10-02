"""Aktionsseite: ein stehender Konvoi wird vergröbert, ein fahrender nicht.

Die Verzögerung schützt einen fahrenden Konvoi. Einen parkenden nicht — zwei
Stunden nach dem Abstellen zeigte die Seite sonst den Autohof metergenau, die
ganze Nacht. Das ist der wichtigste Schutz der Aktionsseite, deshalb steht er
hier ohne Datenbank und Uhr.
"""
from datetime import datetime, timedelta, timezone

from app.services import aktionsseite as a
from app.services.positionsverlauf import abstand_m

T0 = datetime(2026, 12, 27, 18, 0, tzinfo=timezone.utc)


def _fahrt(minuten: int, start=(48.5, 12.1), schritt_grad=0.01) -> list[a.Punkt]:
    """Ein Punkt pro Minute nach Osten, ~0,74 km je Minute (~44 km/h)."""
    return [
        a.Punkt(T0 + timedelta(minutes=i), start[0], start[1] + i * schritt_grad)
        for i in range(minuten)
    ]


def _stand(bei: a.Punkt, ab: datetime, minuten: int) -> list[a.Punkt]:
    """Fünfminütlich am selben Ort, wie es der Verlauf beim Stehen aufzeichnet."""
    return [a.Punkt(ab + timedelta(minutes=m), bei.lat, bei.lon) for m in range(5, minuten + 1, 5)]


# ── Stehen erkennen ────────────────────────────────────────────────────────


def test_fahrender_konvoi_steht_nicht():
    punkte = _fahrt(60)
    assert not a.steht(punkte, punkte[-1].t)


def test_nach_zwanzig_minuten_am_selben_ort_steht_er():
    fahrt = _fahrt(60)
    halt = fahrt[-1]
    punkte = fahrt + _stand(halt, halt.t, 20)
    assert a.steht(punkte, punkte[-1].t)


def test_kurzer_ampelhalt_ist_kein_stehen():
    fahrt = _fahrt(60)
    halt = fahrt[-1]
    punkte = fahrt + _stand(halt, halt.t, 10)
    assert not a.steht(punkte, punkte[-1].t)


def test_ohne_daten_gilt_er_als_stehend():
    """Ein Handy, das nichts mehr sendet, liegt oft im geparkten Fahrzeug."""
    punkte = _fahrt(30)
    assert a.steht(punkte, punkte[-1].t + timedelta(minutes=25))
    assert a.steht([], T0)


# ── Vergröbern ─────────────────────────────────────────────────────────────


def test_vergroebern_legt_auf_eine_feste_zelle():
    """Fest gerastert, nicht verrauscht: ein Versatz ließe sich herausmitteln."""
    lat, lon = 48.5432, 12.1234
    assert a.vergroebern(lat, lon) == a.vergroebern(lat, lon)
    # Zwei Punkte im selben Feld ergeben dieselbe Zelle — ein paar hundert Meter
    # Bewegung auf dem Parkplatz verraten nichts.
    assert a.vergroebern(48.5432, 12.1234) == a.vergroebern(48.5461, 12.1251)


def test_vergroebert_ist_kilometer_weg_vom_echten_ort_aber_nicht_beliebig():
    lat, lon = 48.5432, 12.1234
    glat, glon = a.vergroebern(lat, lon)
    assert abstand_m(lat, lon, glat, glon) < 12_000


def test_stehender_konvoi_wird_vergroebert_fahrender_nicht():
    fahrt = _fahrt(60)
    stand_konvoi = a.konvoi(
        [a.Kandidat(spitze=True, reihenfolge=0, punkte=fahrt + _stand(fahrt[-1], fahrt[-1].t, 30))],
        fahrt[-1].t + timedelta(minutes=30),
        None,
    )
    assert stand_konvoi["status"] == "pause"
    assert stand_konvoi["position"]["coarse"] is True
    assert (stand_konvoi["position"]["lat"], stand_konvoi["position"]["lon"]) == a.vergroebern(
        fahrt[-1].lat, fahrt[-1].lon
    )

    fahrend = a.konvoi([a.Kandidat(True, 0, fahrt)], fahrt[-1].t, None)
    assert fahrend["status"] == "unterwegs"
    assert fahrend["position"]["coarse"] is False
    assert fahrend["position"]["lon"] == round(fahrt[-1].lon, 5)


def test_linie_endet_vor_dem_halt():
    fahrt = _fahrt(120)
    halt = fahrt[-1]
    stand = a.konvoi(
        [a.Kandidat(True, 0, fahrt + _stand(halt, halt.t, 30))],
        halt.t + timedelta(minutes=30),
        None,
    )
    ende_lon, ende_lat = stand["trail"][-1]
    assert abstand_m(ende_lat, ende_lon, halt.lat, halt.lon) >= a.LINIE_ABSTAND_ZUM_HALT_M


# ── Wer den Konvoi vertritt ────────────────────────────────────────────────


def test_spitzenfahrzeug_vertritt_den_konvoi():
    spitze = a.Kandidat(True, 0, _fahrt(30, start=(48.0, 12.0)))
    hinten = a.Kandidat(False, 5, _fahrt(31, start=(47.0, 12.0)))
    assert a.vertreter([hinten, spitze]) is spitze


def test_faellt_die_spitze_aus_nimmt_die_seite_das_frischeste_fahrzeug():
    spitze = a.Kandidat(True, 0, _fahrt(10))
    hinten = a.Kandidat(False, 5, _fahrt(60, start=(47.0, 12.0)))
    assert a.vertreter([spitze, hinten]) is hinten


def test_ohne_jede_position_vor_abfahrt():
    stand = a.konvoi([a.Kandidat(True, 0, [])], T0, None)
    assert stand == {"status": "vor_abfahrt", "position": None, "trail": [], "driven_km": 0.0}


def test_am_ziel_angekommen():
    fahrt = _fahrt(60)
    ziel = (fahrt[-1].lat, fahrt[-1].lon + 0.01)
    stand = a.konvoi(
        [a.Kandidat(True, 0, fahrt + _stand(fahrt[-1], fahrt[-1].t, 30))],
        fahrt[-1].t + timedelta(minutes=30),
        ziel,
    )
    assert stand["status"] == "angekommen"
    # Auch am Ziel bleibt der Standort grob: die Lagerhalle steht nicht auf der Seite.
    assert stand["position"]["coarse"] is True
