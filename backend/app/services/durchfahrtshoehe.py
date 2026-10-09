"""Höhenbeschränkungen entlang der Route — als Hinweis, nicht als Sperre.

Gesperrt wird schon beim Routing: das Custom Model in ``routing.calculate_route``
nimmt jede Kante mit ``max_height`` unter dem höchsten Fahrzeug aus dem Graphen.
Das geschieht still. Wer plant, erfuhr bisher nicht, dass die Route unter einer
Brücke mit 4,00 m hindurchführt, während das höchste Fahrzeug 3,85 m misst. Hier
entsteht die Liste dieser Stellen aus dem Path-Detail ``max_height``.

Zwei Grenzen der Daten, die die Stufen erklären:

- **OSM-Abdeckung.** Die Höhe stammt aus ``maxheight``/``maxheight:physical``
  an der *unterführten* Straße. Wo das Tag fehlt, ist die Kante für
  GraphHopper unbegrenzt — eine Brücke ohne Angabe steht in dieser Liste nicht.
- **10 cm Raster.** GraphHopper speichert ``max_height`` in Schritten von
  0,1 m und rundet dabei (9.1, ``MaxHeight.create``: Faktor 0,1,
  ``Math.round``). Aus „3,85 m" auf dem Schild wird „3,9 m" im Graphen. Unter
  ``ENG_M`` Spielraum kann die Rundung den Rest auffressen, deshalb ist das
  eine eigene Stufe.
"""

from __future__ import annotations

import math
from typing import Any

from app.services import route_steps as route_steps_svc

# Spielraum, unter dem die Rundung im Graphen (± 5 cm) die Lage offen lässt.
ENG_M = 0.10
# Spielraum, unter dem eine Stelle im Marschbefehl auftaucht.
KNAPP_M = 0.30

# Ab hier steht im Graphen kein Schild mehr, sondern das Ende des Wertebereichs
# (7 Bit × 0,1 m; der höchste Wert ist für „unbegrenzt" reserviert, der
# zweithöchste fasst alles darüber). Eine Höhe von 12,6 m ist kein Hinweis.
_OBERGRENZE_M = 12.5


def _hoehe(wert: Any) -> float | None:
    """Wert des Path-Details in Metern; None für „keine Beschränkung".

    GraphHopper liefert für unbegrenzte Kanten ``null`` (``DecimalDetails``,
    JSON kennt kein Infinity). Text wird zur Sicherheit mitgelesen.
    """
    if wert is None or isinstance(wert, bool):
        return None
    try:
        h = float(wert)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(h) or h <= 0 or h > _OBERGRENZE_M:
        return None
    return round(h, 1)


def stufe(spielraum_m: float | None) -> str:
    """``eng`` | ``knapp`` | ``frei`` — oder ``unbekannt`` ohne Fahrzeughöhe."""
    if spielraum_m is None:
        return "unbekannt"
    if spielraum_m < ENG_M:
        return "eng"
    if spielraum_m < KNAPP_M:
        return "knapp"
    return "frei"


def engstellen(
    details: list,
    coords: list,
    fahrzeughoehe_m: float | None,
) -> list[dict[str, Any]]:
    """Die Höhenbeschränkungen entlang der Route, in Fahrtrichtung.

    ``details`` ist GraphHoppers ``max_height``-Detail: ``[von, bis, wert]``
    mit Indizes in ``coords``. Aufeinanderfolgende Abschnitte mit demselben
    Wert fasst GraphHopper schon zusammen; zwei Brücken mit derselben Höhe
    hintereinander bleiben getrennt, weil dazwischen ein unbegrenzter liegt.

    ``fahrzeughoehe_m`` ist das höchste Fahrzeug im Verband (dieselbe Zahl, mit
    der das Routing sperrt), ``None``, wenn kein Fahrzeug eine Höhe hat.
    """
    if not details or len(coords) < 2:
        return []
    along = route_steps_svc.cumulative_m(coords)
    letzter = len(coords) - 1
    out: list[dict[str, Any]] = []
    for eintrag in details:
        try:
            von, bis, wert = int(eintrag[0]), int(eintrag[1]), eintrag[2]
        except (TypeError, ValueError, IndexError):
            continue
        h = _hoehe(wert)
        if h is None:
            continue
        von = max(0, min(von, letzter))
        bis = max(von, min(bis, letzter))
        spielraum = None if fahrzeughoehe_m is None else round(h - fahrzeughoehe_m, 2)
        lon, lat = coords[von][0], coords[von][1]
        out.append({
            "km": round(along[von] / 1000, 1),
            # Meter auf der Linie — der Abgleich mit Brücken ohne Angabe
            # (services/bruecken.py) braucht mehr als die 100 m des km-Werts.
            "m": round(along[von]),
            "lat": lat,
            "lon": lon,
            "laenge_m": round(along[bis] - along[von]),
            "hoehe_m": h,
            "spielraum_m": spielraum,
            "stufe": stufe(spielraum),
        })
    return out


def hinweispflichtig(eintraege: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Was in den Marschbefehl gehört: alles außer ``frei``.

    Ohne Fahrzeughöhe ist jede Stelle ``unbekannt`` und steht deshalb drin —
    beurteilen lässt sie sich dann nur vor Ort.
    """
    return [e for e in eintraege if e.get("stufe") != "frei"]
