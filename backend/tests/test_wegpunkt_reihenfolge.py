"""Die Wegpunktreihenfolge gehört dem Menschen, nicht der Route.

Gemeldet war: nach dem Umsortieren und einer erneuten Berechnung stand die alte
Reihenfolge wieder da, und die Route war unverändert. Ursache war ein Kreis —
die Anfrage wurde entlang der *alten* Route sortiert, die Antwort schrieb
`order_index` aus der *neuen* zurück. Diese Tests halten beide Enden fest.

Wer eingeordnet wird, sagt seit Migration 0045 `pending_placement` und nicht
mehr die Position in der Liste.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.waypoint_order import cumulative_along_route, visiting_order


def _wp(name, order_index, lat=None, lon=None, pending=False):
    return SimpleNamespace(
        name=name, order_index=order_index, lat=lat, lon=lon, pending_placement=pending
    )


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


def test_vorgeschlagener_halt_wandert_in_die_mitte():
    """Das Frontend hängt Vorschläge ans Ende — dort dürfen sie nicht bleiben."""
    wps = [
        _wp("West", 0, 50.0, 9.0),
        _wp("Ost", 1, 50.0, 11.0),
        _wp("TH", 2, 50.0, 10.0, pending=True),
    ]
    assert [w.name for w in visiting_order(wps, _coords, ROUTE)] == ["West", "TH", "Ost"]


def test_mehrere_vorschlaege_werden_einzeln_eingeordnet():
    wps = [
        _wp("West", 0, 50.0, 8.5),
        _wp("Mitte", 1, 50.0, 10.0),
        _wp("Ost", 2, 50.0, 11.5),
        _wp("TH spaet", 3, 50.0, 11.0, pending=True),
        _wp("TH frueh", 4, 50.0, 9.0, pending=True),
    ]
    assert [w.name for w in visiting_order(wps, _coords, ROUTE)] == [
        "West", "TH frueh", "Mitte", "TH spaet", "Ost",
    ]


def test_ein_halt_am_listenende_bleibt_stehen_wenn_er_platziert_ist():
    """Der Fall, für den es die Marke gibt.

    Ein Technischer Halt, den jemand bewusst als *letzten* Wegpunkt gesetzt hat,
    liegt geografisch in der Mitte — die alte Regel („der Lauf am Listenende")
    hätte ihn dorthin verschoben. Ohne Marke wird er nicht angefasst.
    """
    wps = [
        _wp("West", 0, 50.0, 9.0),
        _wp("Ost", 1, 50.0, 11.0),
        _wp("TH zuletzt", 2, 50.0, 10.0),
    ]
    assert [w.name for w in visiting_order(wps, _coords, ROUTE)] == [
        "West", "Ost", "TH zuletzt",
    ]


def test_ein_vorschlag_mitten_in_der_liste_wird_trotzdem_eingeordnet():
    """Die Marke entscheidet, nicht die Position."""
    wps = [
        _wp("West", 0, 50.0, 9.0),
        _wp("TH", 1, 50.0, 11.5, pending=True),
        _wp("Ost", 2, 50.0, 11.0),
    ]
    assert [w.name for w in visiting_order(wps, _coords, ROUTE)] == ["West", "Ost", "TH"]


def test_nur_vorschlaege_behalten_ihre_reihenfolge():
    """Ohne platzierten Wegpunkt gibt es nichts, wogegen man einordnen könnte."""
    wps = [
        _wp("TH Ost", 0, 50.0, 11.0, pending=True),
        _wp("TH West", 1, 50.0, 9.0, pending=True),
    ]
    assert [w.name for w in visiting_order(wps, _coords, ROUTE)] == ["TH Ost", "TH West"]


def test_vorschlag_ohne_lage_rutscht_nicht_an_eine_geratene_stelle():
    wps = [
        _wp("West", 0, 50.0, 9.0),
        _wp("Ost", 1, 50.0, 11.0),
        _wp("TH ohne Lage", 2, pending=True),
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


# ── Die Marke verfällt, sobald jemand platziert hat ───────────────────────────
#
# Ohne das bliebe ein vorgeschlagener Halt für immer „unplatziert" und würde bei
# jeder Berechnung erneut entlang der Route wandern — auch dahin, wo ihn gerade
# jemand weggezogen hat.

def _konvoi_mit(wegpunkte, monkeypatch):
    """Konvoi-Zugriff und Wegpunktabfrage stubben, ohne Datenbank."""
    from app.api.routes import convoys

    org = MagicMock()
    org.id = uuid.uuid4()
    user = MagicMock()
    user.id = uuid.uuid4()
    convoy = MagicMock()
    convoy.id = uuid.uuid4()
    convoy.organization_id = org.id

    async def _access(*a, **k):
        return convoy

    monkeypatch.setattr(convoys, "get_convoy_access", _access)
    monkeypatch.setattr(
        convoys.geo_svc, "waypoint_coords", lambda w: {"lat": 50.0, "lon": 10.0}
    )

    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = wegpunkte
    result.scalar_one_or_none.return_value = wegpunkte[0] if wegpunkte else None
    db.execute.return_value = result
    return convoys, convoy, (user, org, "planer"), db


def _db_wegpunkt(order_index, pending):
    wp = MagicMock()
    wp.id = uuid.uuid4()
    wp.order_index = order_index
    wp.pending_placement = pending
    wp.__dict__.update(
        id=wp.id,
        name="TH",
        type="technical_stop",
        planned_arrival=None,
        planned_departure=None,
        hold_duration_min=0,
        halt_purpose=None,
        notes=None,
        order_index=order_index,
        pending_placement=pending,
    )
    return wp


@pytest.mark.asyncio
async def test_ziehen_in_der_liste_platziert_einen_vorschlag(monkeypatch):
    from app.schemas.waypoint import WaypointReorderItem

    vorschlag = _db_wegpunkt(order_index=1, pending=True)
    fest = _db_wegpunkt(order_index=0, pending=False)
    convoys, convoy, ctx, db = _konvoi_mit([fest, vorschlag], monkeypatch)

    await convoys.reorder_waypoints(
        convoy_id=convoy.id,
        items=[
            WaypointReorderItem(id=vorschlag.id, order_index=0),
            WaypointReorderItem(id=fest.id, order_index=1),
        ],
        ctx=ctx,
        db=db,
    )

    assert vorschlag.pending_placement is False
    assert vorschlag.order_index == 0


@pytest.mark.asyncio
async def test_ausdruecklicher_order_index_platziert_einen_vorschlag(monkeypatch):
    from app.schemas.waypoint import WaypointUpdate

    vorschlag = _db_wegpunkt(order_index=3, pending=True)
    convoys, convoy, ctx, db = _konvoi_mit([vorschlag], monkeypatch)

    await convoys.update_waypoint(
        convoy_id=convoy.id,
        waypoint_id=vorschlag.id,
        data=WaypointUpdate(order_index=1),
        ctx=ctx,
        db=db,
    )

    assert vorschlag.pending_placement is False
    assert vorschlag.order_index == 1


@pytest.mark.asyncio
async def test_eine_namensaenderung_platziert_nichts(monkeypatch):
    """Nur ein gesetzter Platz platziert — sonst bliebe kein Vorschlag übrig."""
    from app.schemas.waypoint import WaypointUpdate

    vorschlag = _db_wegpunkt(order_index=3, pending=True)
    convoys, convoy, ctx, db = _konvoi_mit([vorschlag], monkeypatch)

    await convoys.update_waypoint(
        convoy_id=convoy.id,
        waypoint_id=vorschlag.id,
        data=WaypointUpdate(name="Tankstopp Nord"),
        ctx=ctx,
        db=db,
    )

    assert vorschlag.pending_placement is True
