"""Aktionsseite: Fotos von unterwegs zeigen nie mehr als die Karte daneben.

Ein Foto ist eine Position, auch ohne Koordinate — Ortsschild, Rastplatz,
Kirchturm. Deshalb liegt es dort, wo der Konvoi zu seiner Zeit auf der Seite
stand, und erscheint erst, wenn die Linie bis dorthin reicht. Der Autohof-Fall
ist der Grund für diesen Test: Ein Foto vom Halt um 20 Uhr wäre mit zwei
Stunden Verzögerung ab 22 Uhr zu sehen, während der Konvoi noch dort steht.

Plan: docs/superpowers/plans/2026-10-13-fotos-auf-der-aktionsseite.md, § 4.
Ohne Datenbank und Uhr, wie ``test_aktionsseite_rast.py``.
"""
from datetime import datetime, timedelta, timezone

from app.services import aktionsseite as a
from app.services.positionsverlauf import abstand_m

T0 = datetime(2026, 12, 27, 18, 0, tzinfo=timezone.utc)
# Eine Route nach Osten auf 48,5° N, 12° bis 14° E (~148 km).
ROUTE = a.strecke([(12.0 + i * 0.05, 48.5) for i in range(41)])
SCHLUESSEL = b"test-seite:test-konvoi"


def _fahrt(minuten: int, start=(48.5, 12.1), schritt_grad=0.01) -> list[a.Punkt]:
    """Ein Punkt pro Minute nach Osten, ~0,74 km je Minute (~44 km/h)."""
    return [
        a.Punkt(T0 + timedelta(minutes=i), start[0], start[1] + i * schritt_grad)
        for i in range(minuten)
    ]


def _stand(bei: a.Punkt, ab: datetime, minuten: int) -> list[a.Punkt]:
    return [a.Punkt(ab + timedelta(minutes=m), bei.lat, bei.lon) for m in range(5, minuten + 1, 5)]


def _halt_fahrt(vorher=120, halt_min=90, nachher=120):
    """Fahrt nach Osten, ``halt_min`` Minuten Halt, weiter nach Osten."""
    fahrt = _fahrt(vorher)
    halt = fahrt[-1]
    stand = _stand(halt, halt.t, halt_min)
    weiter = [
        a.Punkt(stand[-1].t + timedelta(minutes=i), halt.lat, halt.lon + i * 0.01)
        for i in range(1, nachher + 1)
    ]
    return fahrt + stand + weiter, halt


def _k(punkte):
    return [a.Kandidat(True, 0, punkte)]


def _pos(punkte, t, stich, ziel=None, schluessel=SCHLUESSEL, route=ROUTE):
    return a.beitrag_position(
        _k(punkte), t, stich, ziel, jetzt=stich + timedelta(hours=1), route=route,
        schluessel=schluessel,
    )


def _sichtbar(punkte, t, stich, ziel=None, schluessel=SCHLUESSEL, ab=None, jetzt=None):
    return a.beitrag_sichtbar(
        _k(punkte), t, stich, ziel, jetzt=jetzt or stich + timedelta(hours=1), route=ROUTE,
        schluessel=schluessel, ab=ab,
    )


def _konvoi(punkte, stich, ziel=None, schluessel=SCHLUESSEL):
    return a.konvoi(
        _k(punkte), stich, ziel, jetzt=stich + timedelta(hours=1), route=ROUTE,
        schluessel=schluessel,
    )


# ── Wo ein Beitrag liegt ───────────────────────────────────────────────────


def test_in_fahrt_dort_wo_der_konvoi_zu_der_zeit_war():
    fahrt = _fahrt(120)
    t = T0 + timedelta(minutes=30, seconds=30)
    pos = _pos(fahrt, t, fahrt[-1].t)
    assert pos == {"lat": 48.5, "lon": round(12.1 + 30.5 * 0.01, 5), "coarse": False}


def test_ohne_verlaufspunkt_in_der_naehe_keine_position():
    """Geraten wird nicht, das Foto kommt dann nur in die Leiste — etwa eines
    von vor der Abfahrt, als noch niemand aufgezeichnet hat."""
    fahrt = _fahrt(120)
    t = T0 - timedelta(minutes=30)
    assert _pos(fahrt, t, fahrt[-1].t) is None


def test_funkloch_zaehlt_als_halt():
    """Wie beim Konvoi selbst: Ein Handy, das nichts sendet, liegt oft im
    geparkten Fahrzeug. Ein Foto aus der Stille kommt auf den Parkplatz,
    nicht an die letzte genaue Stelle davor."""
    fahrt = _fahrt(30)
    spaeter = [a.Punkt(T0 + timedelta(minutes=120 + i), 48.5, 13.5 + i * 0.01) for i in range(60)]
    t = T0 + timedelta(minutes=75)
    pos = _pos(fahrt + spaeter, t, T0 + timedelta(minutes=125))
    assert pos["coarse"] is True
    assert (pos["lat"], pos["lon"]) != (round(fahrt[-1].lat, 5), round(fahrt[-1].lon, 5))


def test_foto_vom_halt_liegt_auf_dem_parkplatz_des_konvois():
    """Dieselbe Stelle, an der der Konvoi in dieser Zeit zu sehen war — nicht
    der echte Ort, und kein zweiter, anderer Versatz."""
    punkte, halt = _halt_fahrt()
    t = halt.t + timedelta(minutes=30)
    for k in range(8):
        schluessel = f"seite-{k}".encode()
        konvoi = _konvoi(punkte, halt.t + timedelta(minutes=45), schluessel=schluessel)
        pos = _pos(punkte, t, halt.t + timedelta(minutes=45), schluessel=schluessel)
        assert pos == {
            "lat": konvoi["position"]["lat"],
            "lon": konvoi["position"]["lon"],
            "coarse": True,
        }
        assert abstand_m(pos["lat"], pos["lon"], halt.lat, halt.lon) >= a.PARKEN_MIN_M * 0.95


def test_foto_auf_der_anfahrt_zum_halt_liegt_auch_auf_dem_parkplatz():
    punkte, halt = _halt_fahrt()
    t = halt.t - timedelta(minutes=7)  # ~5 km davor, im Schutzbereich
    pos = _pos(punkte, t, halt.t + timedelta(minutes=45))
    assert pos["coarse"] is True


def test_foto_am_ziel_ist_vergroebert_nicht_versetzt():
    fahrt = _fahrt(60)
    ziel = (fahrt[-1].lat, fahrt[-1].lon + 0.01)
    punkte = fahrt + _stand(fahrt[-1], fahrt[-1].t, 120)
    pos = _pos(punkte, fahrt[-1].t + timedelta(minutes=60), fahrt[-1].t + timedelta(minutes=100), ziel)
    assert (pos["lat"], pos["lon"]) == a.vergroebern(fahrt[-1].lat, fahrt[-1].lon)
    assert pos["coarse"] is True


# ── Wann ein Beitrag hinausgeht ────────────────────────────────────────────


def test_nicht_vor_der_stichzeit():
    fahrt = _fahrt(240)
    t = T0 + timedelta(minutes=100)
    assert not _sichtbar(fahrt, t, t - timedelta(minutes=1))
    assert _sichtbar(fahrt, t, t)


def test_presse_kann_spaeter_terminieren_nie_frueher():
    fahrt = _fahrt(240)
    t = T0 + timedelta(minutes=100)
    stich = t + timedelta(minutes=30)
    jetzt = stich + timedelta(hours=2)
    assert not _sichtbar(fahrt, t, stich, ab=jetzt + timedelta(minutes=1), jetzt=jetzt)
    assert _sichtbar(fahrt, t, stich, ab=jetzt, jetzt=jetzt)
    # Ein Termin vor der Stichzeit holt nichts nach vorn.
    assert not _sichtbar(fahrt, t, t - timedelta(minutes=1), ab=T0)


def test_foto_vom_autohof_erst_wenn_der_konvoi_wieder_faehrt():
    """Der Grund für diese Datei: Steht der Konvoi um 20 Uhr auf dem Autohof,
    zeigte ein Foto von dort mit zwei Stunden Verzögerung ab 22 Uhr, wo er
    gerade steht — egal, wohin die Karte ihn legt."""
    punkte, halt = _halt_fahrt()
    t = halt.t + timedelta(minutes=10)
    abfahrt = halt.t + timedelta(minutes=90)
    for m in (10, 30, 60, 89):
        assert not _sichtbar(punkte, t, halt.t + timedelta(minutes=m)), m
    # Kurz nach der Abfahrt gilt er noch als haltend …
    assert not _sichtbar(punkte, t, abfahrt + timedelta(minutes=7))
    # … weit danach ist das Foto da.
    assert _sichtbar(punkte, t, abfahrt + timedelta(minutes=60))


def test_solange_er_dort_steht_bleibt_das_foto_zurueck_auch_ohne_abfahrt():
    """Hat er den Halt bis jetzt nicht verlassen, gibt es kein Ende des
    Schutzbereichs — und damit kein Foto."""
    fahrt = _fahrt(120)
    halt = fahrt[-1]
    punkte = fahrt + _stand(halt, halt.t, 600)
    t = halt.t + timedelta(minutes=5)
    assert not _sichtbar(punkte, t, halt.t + timedelta(minutes=300))


def test_halt_gilt_schon_auf_der_anfahrt():
    """Das Foto vom Ortsschild fünf Kilometer vor dem Autohof verrät ihn genauso."""
    punkte, halt = _halt_fahrt()
    t = halt.t - timedelta(minutes=7)
    assert not _sichtbar(punkte, t, halt.t + timedelta(minutes=45))


def test_nie_frueher_sichtbar_als_die_linie_zu_seinem_ort():
    """Hält der Konvoi, endet die Linie vor Halt und Parkplatz. Ein Foto
    dahinter verriete, wie weit er schon ist."""
    punkte, halt = _halt_fahrt()
    stich = halt.t + timedelta(minutes=45)
    for k in range(10):
        schluessel = f"seite-{k}".encode()
        konvoi = _konvoi(punkte, stich, schluessel=schluessel)
        linie_bis_lon = max(lon for lon, _ in konvoi["trail"])
        gezeigt = 0
        for m in range(0, 120, 3):
            t = T0 + timedelta(minutes=m)
            if not _sichtbar(punkte, t, stich, schluessel=schluessel):
                continue
            gezeigt += 1
            pos = _pos(punkte, t, stich, schluessel=schluessel)
            assert pos["lon"] <= linie_bis_lon + 1e-9, (k, m)
        # Die frühen Fotos der Fahrt sind trotzdem da.
        assert gezeigt > 10, k


def test_in_fahrt_sichtbar_sobald_die_stichzeit_vorbei_ist():
    fahrt = _fahrt(240)
    t = T0 + timedelta(minutes=100)
    assert _sichtbar(fahrt, t, t + timedelta(minutes=30))


def test_am_ziel_kommt_das_uebergabefoto():
    """Am Ziel bleibt der Konvoi stehen — ohne Ausnahme käme das Foto, auf das
    alle warten, nie. Der Ort steht vergröbert ohnehin auf der Seite."""
    fahrt = _fahrt(60)
    ziel = (fahrt[-1].lat, fahrt[-1].lon + 0.01)
    punkte = fahrt + _stand(fahrt[-1], fahrt[-1].t, 240)
    t = fahrt[-1].t + timedelta(minutes=60)
    stich = fahrt[-1].t + timedelta(minutes=100)
    assert _konvoi(punkte, stich, ziel)["status"] == "angekommen"
    assert _sichtbar(punkte, t, stich, ziel)
    # Ohne Ziel ist es ein Halt wie jeder andere.
    assert not _sichtbar(punkte, t, stich)


def test_ohne_jede_position_nichts():
    assert not _sichtbar([], T0, T0 + timedelta(hours=3))
    assert _pos([], T0, T0 + timedelta(hours=3)) is None
