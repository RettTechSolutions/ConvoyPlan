"""Reihenfolge der Wegpunkte für eine Routenberechnung.

`order_index` ist die Wahrheit: er ist das, was jemand in der Wegpunktliste an
seinen Platz gezogen hat. Die Route folgt ihm, und die Berechnung schreibt ihn
**nicht** aus der fertigen Route zurück. Genau das tat sie einmal, und dabei
schloss sich ein Kreis: die neue Route entstand aus der Sortierung entlang der
**alten**, und danach wurde die Reihenfolge wieder aus der neuen gewonnen. Ein
Umsortieren von Hand ging dabei zweimal verloren — es kam nie in die Anfrage
hinein und wurde nach der Antwort überschrieben. Die Route blieb, wie sie war,
die Liste sprang zurück.

Die eine Ausnahme sind die Wegpunkte, die die Anwendung selbst vorgeschlagen
hat (Technischer Halt, Lenkpause, Tankstopp). Das Frontend hängt sie ans Ende
der Liste, obwohl sie geografisch in der Mitte liegen; ohne Einordnen führe der
Konvoi erst an ihnen vorbei bis zum letzten Wegpunkt und dann zurück — der
gemeldete Umweg von mehreren hundert Kilometern.

Wer eingeordnet wird, sagt `pending_placement` und **nicht** die Position in der
Liste (Migration 0045). Vorher wurde geraten: „der zusammenhängende Lauf von
`technical_stop` am Ende". Das traf den Normalfall, verschob aber auch einen
Technischen Halt, den jemand bewusst als *letzten* Wegpunkt gesetzt hatte. Die
Marke kommt von der Herkunft: gesetzt beim Anlegen eines Vorschlags, gelöscht,
sobald der Wegpunkt einen Platz hat — durch diese Einordnung, durch Ziehen in
der Liste oder durch ein ausdrücklich gesetztes `order_index`.
"""

from typing import Any, Callable, Sequence

from app.services.fuel import project_onto_route

Coords = tuple[float, float]
CoordsOf = Callable[[Any], Coords | None]


def is_pending(wp: Any) -> bool:
    """Wartet dieser Wegpunkt noch auf seinen Platz in der Reihenfolge?"""
    return bool(getattr(wp, "pending_placement", False))


def visiting_order(
    waypoints: Sequence[Any],
    coords_of: CoordsOf,
    prev_route_coords: Sequence[Sequence[float]] | None = None,
) -> list[Any]:
    """Alle Wegpunkte in der Reihenfolge, in der sie angefahren werden.

    Grundlage ist `order_index`. Nur die als unplatziert markierten Wegpunkte
    werden entlang *prev_route_coords* eingeordnet, und auch das nur, wenn es
    eine vorherige Route und mindestens einen platzierten Wegpunkt mit Lage
    gibt — ohne Bezugspunkte bliebe die Projektion eine Vermutung.
    """
    ordered = sorted(waypoints, key=lambda wp: getattr(wp, "order_index", 0) or 0)
    if not prev_route_coords:
        return ordered

    anchors = [wp for wp in ordered if not is_pending(wp)]
    floats = [wp for wp in ordered if is_pending(wp)]
    if not anchors or not floats:
        return ordered

    # Kilometrierung der platzierten Wegpunkte: je Einfügestelle (hinter dem
    # i-ten Anker) die Strecke, ab der ein Vorschlag dahinter gehört.
    slots: list[tuple[int, float]] = []
    for index, wp in enumerate(anchors):
        c = coords_of(wp)
        if c is not None:
            slots.append((index + 1, project_onto_route(prev_route_coords, c[0], c[1])))
    if not slots:
        return ordered

    def slot_for(distance_m: float) -> int:
        position = 0
        for index, anchor_distance in slots:
            if anchor_distance <= distance_m:
                position = index
        return position

    placed: list[tuple[int, float, Any]] = []
    unplaced: list[Any] = []
    for wp in floats:
        c = coords_of(wp)
        if c is None:
            # Ohne Koordinaten fährt der Konvoi ihn ohnehin nicht an; er bleibt,
            # wo er steht, statt an eine geratene Stelle zu rutschen.
            unplaced.append(wp)
            continue
        distance_m = project_onto_route(prev_route_coords, c[0], c[1])
        placed.append((slot_for(distance_m), distance_m, wp))

    placed.sort(key=lambda entry: (entry[0], entry[1]))
    result = list(anchors)
    for offset, (position, _, wp) in enumerate(placed):
        result.insert(position + offset, wp)
    result.extend(unplaced)
    return result


def cumulative_along_route(
    route_coords: Sequence[Sequence[float]],
    points: Sequence[Coords],
) -> list[float]:
    """Kilometrierung der *points* auf der Route, monoton steigend.

    Die Route besucht die Punkte in der übergebenen Reihenfolge, also dürfen die
    Werte nicht fallen. Eine Projektion kann das verletzen, wo die Route ein
    Stück doppelt befährt — bei einer Stichfahrt zu einem Halt und zurück trifft
    die Suche nach dem nächsten Streckenpunkt die falsche Vorbeifahrt. Statt
    daraus eine negative Teilstrecke und damit eine rückwärts laufende Uhr zu
    machen, wird der Wert auf das bisherige Maximum angehoben.
    """
    cumulative: list[float] = []
    highest = 0.0
    for lat, lon in points:
        distance_m = max(highest, project_onto_route(route_coords, lat, lon))
        highest = distance_m
        cumulative.append(distance_m)
    return cumulative
