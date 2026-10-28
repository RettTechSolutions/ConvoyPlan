"""Fahrhinweise für die Verfolgung: wo auf der Linie ein Abbiegehinweis liegt.

Das Roadbook braucht von einem Hinweis nur die Strecke bis zum nächsten
(``distance_m``). Wer live mitfährt, braucht mehr: die Stelle **auf der Linie**,
an der das Manöver liegt — als Meter ab dem Start. Die Companion-App projiziert
den eigenen Standort auf dieselbe Linie und vergleicht die beiden Zahlen.

Gemessen wird deshalb genau so, wie die App misst: Haversine über die
Stützpunkte der gespeicherten Geometrie. Aus GraphHoppers Teilstrecken
aufsummiert läge der Meter einige Meter daneben, und diese Meter kündigten ein
Manöver zu früh oder zu spät an.
"""

from typing import Any

from app.services.fuel import haversine_m


def cumulative_m(coords: list[list[float]]) -> list[float]:
    """Meter ab dem Start bis zu jedem Stützpunkt. ``[0.0, …]``, gleich lang wie ``coords``."""
    out = [0.0] if coords else []
    for i in range(1, len(coords)):
        (lon1, lat1), (lon2, lat2) = coords[i - 1][:2], coords[i][:2]
        out.append(out[-1] + haversine_m(lon1, lat1, lon2, lat2))
    return out


# Ab dieser Länge ist eine Beschränkung ein Abschnitt und kein Punkt: Die Liste
# nennt die Länge, die Karte zeigt die Teilstrecke. Darunter (Unterführung,
# Brücke) reicht der Punkt. Dieselbe Grenze steht in `$lib/route/abschnitt.ts`.
ABSCHNITT_AB_M = 200
# Höchstens so viele Stützpunkte trägt die Linie eines Abschnitts. Eine
# Lkw-Sperre über 30 km soll die gespeicherte Route nicht aufblähen.
ABSCHNITT_PUNKTE = 60


def abschnitt(coords: list[list[float]], von: int, bis: int) -> list[list[float]]:
    """Die Teilstrecke ``coords[von..bis]`` als Linie, ausgedünnt auf ``ABSCHNITT_PUNKTE``.

    GraphHopper kennt eine Beschränkung je Kante, nicht je Schild. Wo genau auf
    der Kante das Schild steht, weiß niemand — der erste Stützpunkt allein sah
    deshalb aus wie die Stelle selbst. Gemeldet: die Mautzufahrt am
    Karawankentunnel (``maxheight=4`` ab dem Brückenende) erschien als Brücke
    mit 4,0 m. Anfang und Ende bleiben immer erhalten.
    """
    teil = [[round(c[0], 6), round(c[1], 6)] for c in coords[von:bis + 1]]
    if len(teil) <= ABSCHNITT_PUNKTE:
        return teil
    schritt = (len(teil) - 1) / (ABSCHNITT_PUNKTE - 1)
    return [teil[round(i * schritt)] for i in range(ABSCHNITT_PUNKTE)]


def abschnitt_text(laenge_m: Any) -> str:
    """„auf 350 m" bzw. „auf 1,1 km" — leer unter ``ABSCHNITT_AB_M``.

    Derselbe Text steht in `$lib/route/abschnitt.ts`; wer einen ändert, zieht
    den anderen mit.
    """
    if not isinstance(laenge_m, (int, float)) or isinstance(laenge_m, bool) or laenge_m < ABSCHNITT_AB_M:
        return ""
    if laenge_m < 1000:
        return f"auf {round(laenge_m / 10) * 10:.0f} m"
    return f"auf {laenge_m / 1000:.1f} km".replace(".", ",")


def instruction_m(interval: Any, along: list[float]) -> float | None:
    """Meter der Stelle, an der eine Anweisung beginnt — aus GraphHoppers ``interval``.

    ``interval[0]`` ist der Index des Stützpunkts, an dem das Manöver liegt.
    ``None``, wenn das Intervall fehlt oder nicht zur Geometrie passt: lieber
    kein Meter als ein erfundener.
    """
    if not isinstance(interval, (list, tuple)) or not interval:
        return None
    start = interval[0]
    if not isinstance(start, int) or isinstance(start, bool) or not 0 <= start < len(along):
        return None
    return round(along[start], 1)


def track_steps(instructions: list[dict[str, Any]] | None, coords: list[list[float]]) -> list[dict[str, Any]]:
    """Die Hinweise so, wie ``/api/track/{slug}`` sie als ``route_steps`` ausliefert.

    Hinweise, die berechnet wurden, bevor ``compact_instructions`` den Meter
    mitschrieb, tragen kein ``m``. Für sie wird der
    Meter aus den Teilstrecken aufsummiert und auf die Länge der Linie
    gestreckt — ungenauer, aber besser als eine Route ohne Hinweise, bis sie
    jemand neu berechnet. Sobald auch nur ein Eintrag keinen Meter hat, gilt
    der Rückfall für alle: gemischt ergäbe das keine aufsteigende Folge.
    """
    if not instructions or len(coords) < 2:
        return []

    if all(isinstance(ins.get("m"), (int, float)) for ins in instructions):
        positions = [float(ins["m"]) for ins in instructions]
    else:
        sums, km = [], 0.0
        for ins in instructions:
            sums.append(km)
            km += float(ins.get("distance_m") or 0.0)
        line_m = cumulative_m(coords)[-1]
        scale = line_m / km if km > 0 else 0.0
        positions = [round(s * scale, 1) for s in sums]

    steps = []
    for ins, m in zip(instructions, positions):
        steps.append({
            "m": m,
            "sign": int(ins.get("sign", 0)),
            "text": ins.get("text") or None,
            # Die App zeigt einen Namen. Eine Bundesstrasse ohne Namen heisst
            # bei GraphHopper nur über ihre Nummer — dann eben die.
            "street_name": ins.get("street_name") or ins.get("street_ref") or None,
            "exit_number": ins.get("exit_number"),
        })
    # Aufsteigend nach Meter; `sorted` ist stabil und lässt gleiche Meter
    # (Zwischenziel und das Manöver dahinter) in GraphHoppers Folge.
    return sorted(steps, key=lambda s: s["m"])
