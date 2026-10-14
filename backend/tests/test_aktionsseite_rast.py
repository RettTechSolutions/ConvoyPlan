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


# ── Parken entlang der Route ───────────────────────────────────────────────

# Eine Route nach Osten auf 48,5° N, 12° bis 14° E (~148 km) — die Fahrt aus
# ``_fahrt`` liegt darauf.
ROUTE = a.strecke([(12.0 + i * 0.05, 48.5) for i in range(41)])
SCHLUESSEL = b"test-seite:test-konvoi"


def _halt_fahrt(vorher=120, halt_min=90, nachher=120):
    """Fahrt nach Osten, ``halt_min`` Minuten Halt, weiter nach Osten."""
    fahrt = _fahrt(vorher)
    halt = fahrt[-1]
    stand = _stand(halt, halt.t, halt_min)
    weiter_ab = stand[-1].t
    weiter = [
        a.Punkt(weiter_ab + timedelta(minutes=i), halt.lat, halt.lon + i * 0.01)
        for i in range(1, nachher + 1)
    ]
    return fahrt + stand + weiter, halt


def _zeig(punkte, stich, jetzt=None, route=ROUTE, schluessel=SCHLUESSEL):
    return a.konvoi(
        [a.Kandidat(True, 0, punkte)],
        stich,
        None,
        jetzt=jetzt or stich + timedelta(hours=1),
        route=route,
        schluessel=schluessel,
    )


def test_haltender_konvoi_parkt_auf_der_route_vor_oder_hinter_dem_halt():
    punkte, halt = _halt_fahrt()
    stand = _zeig(punkte, halt.t + timedelta(minutes=45))
    assert stand["status"] == "pause"
    pos = stand["position"]
    assert pos["coarse"] is True
    # Auf der Route, nicht irgendwo daneben …
    assert abs(pos["lat"] - 48.5) < 0.001
    # … und 10 bis 25 km vom Halt weg, nicht drumherum.
    weg = abstand_m(pos["lat"], pos["lon"], halt.lat, halt.lon)
    assert a.PARKEN_MIN_M * 0.95 <= weg <= a.PARKEN_MAX_M * 1.05


def test_der_parkplatz_bleibt_fuer_den_ganzen_halt_derselbe():
    """Ein Versatz je Abruf ließe sich über viele Abrufe herausmitteln."""
    punkte, halt = _halt_fahrt()
    orte = {
        (s["position"]["lat"], s["position"]["lon"])
        for m in range(0, 90, 5)
        for s in [_zeig(punkte, halt.t + timedelta(minutes=m))]
    }
    assert len(orte) == 1


def test_jede_seite_parkt_woanders():
    punkte, halt = _halt_fahrt()
    stich = halt.t + timedelta(minutes=45)
    orte = {
        (s["position"]["lat"], s["position"]["lon"])
        for k in range(12)
        for s in [_zeig(punkte, stich, schluessel=f"seite-{k}".encode())]
    }
    assert len(orte) > 6
    # Mal davor, mal dahinter.
    assert min(lon for _, lon in orte) < halt.lon < max(lon for _, lon in orte)


def test_der_halt_zeigt_sich_nicht_erst_nach_zwanzig_minuten():
    """Die ersten zwanzig Minuten stand der Konvoi früher metergenau auf der
    Seite, bevor er als stehend galt. Die Verzögerung erlaubt den Blick nach
    vorn: Was nach der Stichzeit kam, sagt, dass er hier stehen bleibt."""
    punkte, halt = _halt_fahrt()
    for m in (0, 1, 5, 19):
        stand = _zeig(punkte, halt.t + timedelta(minutes=m))
        assert stand["status"] == "pause", m
        assert (stand["position"]["lat"], stand["position"]["lon"]) != (
            round(halt.lat, 5),
            round(halt.lon, 5),
        )


def test_schon_auf_der_anfahrt_und_noch_nach_der_abfahrt_haltend():
    """Sonst läge der Halt kurz vor der letzten genauen Position vor der
    Pause oder kurz hinter der ersten danach."""
    punkte, halt = _halt_fahrt()
    # 5 km vor dem Halt (~7 Minuten Fahrt)
    assert _zeig(punkte, halt.t - timedelta(minutes=7))["status"] == "pause"
    # 5 km danach
    abfahrt = halt.t + timedelta(minutes=90)
    assert _zeig(punkte, abfahrt + timedelta(minutes=7))["status"] == "pause"
    # Weit davor und weit danach wieder genau.
    assert _zeig(punkte, halt.t - timedelta(minutes=60))["status"] == "unterwegs"
    weit = _zeig(punkte, abfahrt + timedelta(minutes=60))
    assert weit["status"] == "unterwegs"
    assert weit["position"]["coarse"] is False


def test_vorschau_reicht_nur_so_weit_wie_die_daten():
    """Ohne Punkte nach der Stichzeit gilt, was bis dahin war: Ein Konvoi,
    der gerade erst angehalten hat, fährt aus Sicht der Seite noch."""
    fahrt = _fahrt(60)
    stand = _zeig(fahrt, fahrt[-1].t, jetzt=fahrt[-1].t)
    assert stand["status"] == "unterwegs"


def test_linie_endet_vor_halt_und_parkplatz():
    punkte, halt = _halt_fahrt()
    for k in range(8):
        stand = _zeig(punkte, halt.t + timedelta(minutes=45), schluessel=f"s{k}".encode())
        pos = stand["position"]
        ende_lon, ende_lat = stand["trail"][-1]
        assert abstand_m(ende_lat, ende_lon, halt.lat, halt.lon) >= a.LINIE_ABSTAND_ZUM_HALT_M
        assert abstand_m(ende_lat, ende_lon, pos["lat"], pos["lon"]) >= a.LINIE_ABSTAND_ZUM_HALT_M
        # Nach Osten gefahren: die Linie reicht nicht über den Parkplatz hinaus.
        assert ende_lon < min(pos["lon"], halt.lon)


def test_nach_der_abfahrt_reicht_die_linie_nicht_ueber_den_halt():
    """Auch ohne Route: Solange er als haltend gilt, zeigt die Linie nicht,
    wie weit er schon wieder ist."""
    punkte, halt = _halt_fahrt()
    abfahrt = halt.t + timedelta(minutes=90)
    for route in (ROUTE, None):
        stand = _zeig(punkte, abfahrt + timedelta(minutes=15), route=route)
        assert stand["status"] == "pause"
        assert max(lon for lon, _ in stand["trail"]) < halt.lon


def test_gefahrene_kilometer_passen_zum_parkplatz():
    punkte, halt = _halt_fahrt()
    stand = _zeig(punkte, halt.t + timedelta(minutes=45))
    bis_halt = a.strecke_km(punkte[:120])
    pos = stand["position"]
    versatz_km = abstand_m(pos["lat"], pos["lon"], halt.lat, halt.lon) / 1000
    erwartet = bis_halt + (versatz_km if pos["lon"] > halt.lon else -versatz_km)
    assert stand["driven_km"] == float(round(stand["driven_km"]))
    assert abs(stand["driven_km"] - erwartet) <= 2


def test_ohne_route_bleibt_es_beim_raster():
    punkte, halt = _halt_fahrt()
    stand = _zeig(punkte, halt.t + timedelta(minutes=45), route=None)
    assert (stand["position"]["lat"], stand["position"]["lon"]) == a.vergroebern(halt.lat, halt.lon)


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
