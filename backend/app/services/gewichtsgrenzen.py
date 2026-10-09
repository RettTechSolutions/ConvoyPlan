"""Gewichtsgrenzen entlang der Route — gesperrt beim Routing, gezeigt danach.

Wie bei der Höhe (``durchfahrtshoehe.py``) sperrt das Custom Model in
``routing.calculate_route``: jede Kante mit ``max_weight`` unter dem schwersten
Fahrzeug fällt heraus. Ausgenommen ist „Anlieger frei"
(``max_weight_except=destination``) — dort wird nur stark gemieden, sonst gäbe
es zu einem Ziel hinter so einer Grenze keine Route. Lieferverkehr und Forst
sperren, ein Konvoi ist keins von beidem.

Was in ``max_weight`` steht, ist nicht nur die Tragfähigkeit einer Brücke.
GraphHopper liest ``maxweight``, ``maxweightrating``, ``maxweightrating:hgv`` und
macht aus ``hgv:conditional=no @ (weight>7.5)`` ebenfalls 7,5 t — ein
Lkw-Durchfahrtsverbot steht also genauso in der Liste. Auf dem Schild gilt das
tatsächliche Gewicht; verglichen wird mit dem eingetragenen Fahrzeuggewicht.

Achslasten (``max_axle_load``, Zeichen 263, OSM ``maxaxleload``) stehen in
derselben Liste mit ``art="achslast"``, verglichen mit der größten Achslast im
Verband (``vehicles.axle_load_kg``). Eine Ausnahme kennt der Graph dafür nicht.

GraphHopper speichert das Gewicht in 0,1-t-Schritten bis 51,1 t
(``MaxWeight.create``), die Achslast in 0,5-t-Schritten bis 63,5 t
(``MaxAxleLoad.create``, beide 10.2); der höchste Wert steht jeweils für
„unbegrenzt", der zweithöchste fasst alles darüber. Weil die Achslast gröber
gerundet ist, gilt sie früher als knapp.
"""

from __future__ import annotations

import math
from typing import Any

from app.services import route_steps as route_steps_svc

# Reserve, unter der eine Grenze als knapp gilt. Das eingetragene Gewicht ist
# selten auf die Tonne genau, und Beladung, Besatzung und Betriebsstoff kommen
# dazu.
KNAPP_T = 2.0
# Achslast: Raster 0,5 t, Schild selten auf die Tonne genau ausgenutzt.
KNAPP_ACHSE_T = 1.0

_OBERGRENZE_T = 51.0
_OBERGRENZE_ACHSE_T = 63.0

AUSNAHMEN = {"delivery": "Lieferverkehr frei", "destination": "Anlieger frei", "forestry": "Forstverkehr frei"}


def _tonnen(wert: Any, obergrenze: float = _OBERGRENZE_T) -> float | None:
    """Wert des Path-Details in Tonnen; None für „keine Grenze" (null)."""
    if wert is None or isinstance(wert, bool):
        return None
    try:
        t = float(wert)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(t) or t <= 0 or t > obergrenze:
        return None
    return round(t, 1)


def stufe(reserve_t: float | None, knapp_t: float = KNAPP_T) -> str:
    """``ueberschritten`` | ``knapp`` | ``frei`` — oder ``unbekannt`` ohne Fahrzeuggewicht.

    ``ueberschritten`` gibt es nur bei „Anlieger frei": überall sonst hat das
    Routing die Kante gesperrt.
    """
    if reserve_t is None:
        return "unbekannt"
    if reserve_t < 0:
        return "ueberschritten"
    if reserve_t < knapp_t:
        return "knapp"
    return "frei"


def _ausnahme_je_stuetzpunkt(except_details: list, n: int) -> list[str | None]:
    out: list[str | None] = [None] * n
    for eintrag in except_details or []:
        try:
            von, bis, wert = int(eintrag[0]), int(eintrag[1]), eintrag[2]
        except (TypeError, ValueError, IndexError):
            continue
        name = str(wert).lower() if wert else None
        if name not in AUSNAHMEN:
            continue
        for i in range(max(0, von), min(max(bis, von + 1), n)):
            out[i] = name
    return out


def grenzen(
    weight_details: list,
    except_details: list,
    coords: list,
    fahrzeuggewicht_t: float | None,
) -> list[dict[str, Any]]:
    """Die Gewichtsgrenzen entlang der Route, in Fahrtrichtung.

    ``weight_details``/``except_details`` sind GraphHoppers Path-Details
    ``max_weight`` und ``max_weight_except`` (``[von, bis, wert]``, Indizes in
    ``coords``). ``fahrzeuggewicht_t`` ist das schwerste Fahrzeug — dieselbe Zahl,
    mit der gesperrt wurde —, ``None``, wenn keines ein Gewicht hat.
    """
    if not weight_details or len(coords) < 2:
        return []
    along = route_steps_svc.cumulative_m(coords)
    letzter = len(coords) - 1
    ausnahme = _ausnahme_je_stuetzpunkt(except_details, len(coords))
    out: list[dict[str, Any]] = []
    for eintrag in weight_details:
        try:
            von, bis, wert = int(eintrag[0]), int(eintrag[1]), eintrag[2]
        except (TypeError, ValueError, IndexError):
            continue
        t = _tonnen(wert)
        if t is None:
            continue
        von = max(0, min(von, letzter))
        bis = max(von, min(bis, letzter))
        reserve = None if fahrzeuggewicht_t is None else round(t - fahrzeuggewicht_t, 1)
        out.append({
            "km": round(along[von] / 1000, 1),
            "m": round(along[von]),
            "lat": coords[von][1],
            "lon": coords[von][0],
            "laenge_m": round(along[bis] - along[von]),
            "grenze_t": t,
            "reserve_t": reserve,
            "ausnahme": ausnahme[von],
            "stufe": stufe(reserve),
            "art": "gewicht",
        })
    return out


def achslasten(
    axle_details: list,
    coords: list,
    achslast_t: float | None,
) -> list[dict[str, Any]]:
    """Die Achslastgrenzen entlang der Route — dieselbe Form wie ``grenzen()``.

    ``achslast_t`` ist die größte Achslast im Verband, mit der gesperrt wurde.
    ``ueberschritten`` gibt es hier nicht: ohne Ausnahme sperrt jede Grenze.
    """
    if not axle_details or len(coords) < 2:
        return []
    along = route_steps_svc.cumulative_m(coords)
    letzter = len(coords) - 1
    out: list[dict[str, Any]] = []
    for eintrag in axle_details:
        try:
            von, bis, wert = int(eintrag[0]), int(eintrag[1]), eintrag[2]
        except (TypeError, ValueError, IndexError):
            continue
        t = _tonnen(wert, _OBERGRENZE_ACHSE_T)
        if t is None:
            continue
        von = max(0, min(von, letzter))
        bis = max(von, min(bis, letzter))
        reserve = None if achslast_t is None else round(t - achslast_t, 1)
        out.append({
            "km": round(along[von] / 1000, 1),
            "m": round(along[von]),
            "lat": coords[von][1],
            "lon": coords[von][0],
            "laenge_m": round(along[bis] - along[von]),
            "grenze_t": t,
            "reserve_t": reserve,
            "ausnahme": None,
            "stufe": stufe(reserve, KNAPP_ACHSE_T),
            "art": "achslast",
        })
    return out


def zusammen(*listen: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Gewichts- und Achslastgrenzen in Fahrtrichtung, Gewicht vor Achslast an derselben Stelle."""
    return sorted((e for liste in listen for e in liste), key=lambda e: (e["m"], e["art"] != "gewicht"))


def hinweispflichtig(eintraege: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Was in den Marschbefehl gehört: alles außer ``frei``."""
    return [e for e in eintraege if e.get("stufe") != "frei"]
