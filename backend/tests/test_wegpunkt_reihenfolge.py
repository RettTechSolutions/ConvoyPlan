"""Die Wegpunktreihenfolge gehört dem Menschen, nicht der Route.

Gemeldet war: nach dem Umsortieren und einer erneuten Berechnung stand die alte
Reihenfolge wieder da, und die Route war unverändert. Ursache war ein Kreis —
die Anfrage wurde entlang der *alten* Route sortiert, die Antwort schrieb
`order_index` aus der *neuen* zurück. Diese Tests halten beide Enden fest.
"""

from types import SimpleNamespace

from app.services.waypoint_order import cumulative_along_route, visiting_order


def _wp(name, order_index, lat=None, lon=None, type="waypoint"):
    return SimpleNamespace(name=name, order_index=order_index, lat=lat, lon=lon, type=type)


def _coords(wp):
    return None if wp.lat is None else (wp.lat, wp.lon)


# Eine Route von West nach Ost auf einem Breitengrad.
ROUTE = [[8.0, 50.0], [9.0, 50.0], [10.0, 50.0], [11.0, 50.0], [12.0, 50.0]]


def test_handsortierte_reihenfolge_bleibt_gegen_die_route_stehen():
    """Der Kern der Meldung: umsortieren, neu berechnen — und es bleibt so."""
    # Von Hand gegen die Fahrtrichtung sortiert: Ost zuerst.
    wps = [
        _wp("Ost", 0, 50.0, 11.0),
        _wp("Mitte", 1, 50.0, 10.0),
        _wp("West", 2, 50.0, 9.0),
    ]
    order = visiting_order(wps, _coords, ROUTE)
    assert [w.name for w in order] == ["Ost", "Mitte", "West"]


def test_ohne_vorherige_route_gilt_der_index():
    wps = [_wp("B", 1, 50.0, 10.0), _wp("A", 0, 50.0, 11.0)]
    assert [w.name for w in visiting_order(wps, _coords, [])] == ["A", "B"]


def test_angehaengter_technischer_halt_wandert_in_die_mitte():
    """Das Frontend hängt Halte ans Ende — dort dürfen sie nicht bleiben."""
    wps = [
        _wp("West", 0, 50.0, 9.0),
        _wp("Ost", 1, 50.0, 11.0),
        _wp("TH", 2, 50.0, 10.0, type="technical_stop"),
    ]
    assert [w.name for w in visiting_order(wps, _coords, ROUTE)] == ["West", "TH", "Ost"]


def test_mehrere_angehaengte_halte_werden_einzeln_eingeordnet():
    wps = [
        _wp("West", 0, 50.0, 8.5),
        _wp("Mitte", 1, 50.0, 10.0),
        _wp("Ost", 2, 50.0, 11.5),
        _wp("TH spaet", 3, 50.0, 11.0, type="technical_stop"),
        _wp("TH frueh", 4, 50.0, 9.0, type="technical_stop"),
    ]
    assert [w.name for w in visiting_order(wps, _coords, ROUTE)] == [
        "West", "TH frueh", "Mitte", "TH spaet", "Ost",
    ]


def test_eingeordneter_halt_bleibt_beim_naechsten_lauf_stehen():
    """Einmal eingeordnet ist ein Halt ein Wegpunkt wie jeder andere.

    Er steht dann nicht mehr am Listenende und wird deshalb nicht erneut
    angefasst — auch nicht, wenn jemand ihn bewusst woandershin gezogen hat.
    """
    wps = [
        _wp("West", 0, 50.0, 9.0),
        _wp("TH", 1, 50.0, 11.0, type="technical_stop"),
        _wp("Ost", 2, 50.0, 10.0),
    ]
    assert [w.name for w in visiting_order(wps, _coords, ROUTE)] == ["West", "TH", "Ost"]


def test_nur_technische_halte_behalten_ihre_reihenfolge():
    """Ohne festen Wegpunkt davor gibt es nichts, wogegen man einordnen könnte."""
    wps = [
        _wp("TH Ost", 0, 50.0, 11.0, type="technical_stop"),
        _wp("TH West", 1, 50.0, 9.0, type="technical_stop"),
    ]
    order = visiting_order(wps, _coords, ROUTE)
    assert [w.name for w in order] == ["TH Ost", "TH West"]


def test_halt_ohne_lage_rutscht_nicht_an_eine_geratene_stelle():
    wps = [
        _wp("West", 0, 50.0, 9.0),
        _wp("Ost", 1, 50.0, 11.0),
        _wp("TH ohne Lage", 2, type="technical_stop"),
    ]
    assert [w.name for w in visiting_order(wps, _coords, ROUTE)] == [
        "West", "Ost", "TH ohne Lage",
    ]


def test_kilometrierung_faellt_nie_zurueck():
    """Eine Stichfahrt darf keine negative Teilstrecke und keine Zeitreise ergeben."""
    # Route fährt nach Osten, kehrt um und fährt zurück nach Westen.
    hin_und_zurueck = [[8.0, 50.0], [10.0, 50.0], [12.0, 50.0], [10.0, 50.0], [8.0, 50.0]]
    werte = cumulative_along_route(hin_und_zurueck, [(50.0, 10.0), (50.0, 12.0), (50.0, 10.0)])
    assert werte == sorted(werte)
    assert werte[2] >= werte[1]


def test_kilometrierung_steigt_entlang_der_route():
    werte = cumulative_along_route(ROUTE, [(50.0, 9.0), (50.0, 10.0), (50.0, 11.0)])
    assert werte[0] < werte[1] < werte[2]
