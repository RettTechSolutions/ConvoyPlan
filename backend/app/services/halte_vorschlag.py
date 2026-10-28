"""Übernommene Halte-Vorschläge und was aus ihnen nach einer neuen Route wird.

Wer eine Empfehlung (Technischer Halt, Lenkpause, Tagesruhezeit) übernimmt,
bekommt einen gewöhnlichen Wegpunkt. Ändert sich danach die Route — anderer
Weg, weil Höhe oder Gewicht sperren, ein Wegpunkt mehr —, stehen diese Halte
dort, wo sie für die *alte* Route fällig waren. Die Halte-Empfehlung zählt sie
als geplante Halte und legt vor jeden, der jetzt zu spät kommt, einen neuen:
„früher geht immer, später nie". Gemeldet war das Ergebnis: zwei
Tagesruhezeiten 45 km auseinander, zwei Lenkpausen, zwei THs — 11 h Stillstand
für nichts, und keine Regel schlug an, weil zu viel Pause nie verboten ist.

Deshalb trägt ein übernommener Vorschlag seine Herkunft (`vorschlag_art`,
Migration 0074), solange niemand ihn anfasst. Diese Halte rechnet die Analyse
einmal **ohne** sie neu und vergleicht: Passen sie zur frischen Empfehlung,
ist nichts zu tun. Passt einer nicht mehr, bietet die Planung an, sie neu zu
verteilen — die veralteten weg, die fehlenden dazu. Automatisch geschieht das
nicht: die Halteliste gehört dem Menschen, wie die Reihenfolge.

Angefasst heißt: Name, Art, Lage, Dauer oder Grund geändert. Danach ist es
sein Halt und bleibt, wo er steht. Umsortieren und Notizen zählen nicht — sie
ändern nicht, wo und wie lange gehalten wird.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

ARTEN = ("tech", "break", "daily_rest")

NAME = {"tech": "Technischer Halt", "break": "Lenkpause", "daily_rest": "Tagesruhezeit"}

# Wie weit ein übernommener Halt von der frischen Empfehlung abliegen darf, in
# Lenkzeit. Kleine Verschiebungen (ein Wegpunkt näher an der Linie, ein paar
# Minuten Fahrzeit mehr) sollen niemanden zum Neuverteilen auffordern; ein
# anderer Weg über die Alpen schon.
TOLERANZ_S = 15 * 60

# Felder, deren Änderung einen Vorschlag zum eigenen Halt macht.
FELDER_DES_HALTS = ("name", "type", "hold_duration_min", "halt_purpose")


@dataclass(frozen=True)
class Uebernommen:
    waypoint_id: str
    kind: str
    km: float


def toleranz_km(route_km: float, route_duration_s: float) -> float:
    if route_duration_s <= 0:
        return 0.0
    return TOLERANZ_S / route_duration_s * route_km


def abgleich(
    frisch: Iterable[dict[str, Any]],
    uebernommen: Iterable[Uebernommen],
    toleranz: float,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Welche übernommenen Halte veraltet sind und welche frischen fehlen.

    *frisch* ist die Empfehlung ohne die übernommenen Halte (``fuel.halteplan``),
    *uebernommen* die unberührten Vorschläge mit ihrem Kilometer auf der
    aktuellen Route. Gepaart wird je Art, der nächstgelegene innerhalb der
    Toleranz, jeder höchstens einmal.
    """
    offen = sorted(uebernommen, key=lambda u: u.km)
    fehlend: list[dict[str, Any]] = []
    for halt in sorted(frisch, key=lambda h: h["stop_km"]):
        kandidaten = [
            u for u in offen
            if u.kind == halt["kind"] and abs(u.km - halt["stop_km"]) <= toleranz
        ]
        if kandidaten:
            offen.remove(min(kandidaten, key=lambda u: abs(u.km - halt["stop_km"])))
        else:
            fehlend.append(halt)
    return [u.waypoint_id for u in offen], fehlend


def bleibt_vorschlag(wp: Any, aenderungen: dict[str, Any], neue_lage: tuple[float, float] | None,
                     alte_lage: tuple[float, float] | None) -> bool:
    """Ob ein Wegpunkt nach diesen Änderungen noch ein unberührter Vorschlag ist.

    Ein Formular schickt alle Felder mit, auch unveränderte — verglichen wird
    deshalb der Wert, nicht das Vorkommen.
    """
    if not getattr(wp, "vorschlag_art", None):
        return False
    for feld in FELDER_DES_HALTS:
        if feld in aenderungen and aenderungen[feld] != getattr(wp, feld):
            return False
    # Gerundet: die Koordinaten kommen als Fließkommazahl durch PostGIS zurück.
    if neue_lage is not None and (
        alte_lage is None or tuple(round(x, 6) for x in neue_lage) != tuple(round(x, 6) for x in alte_lage)
    ):
        return False
    return True
