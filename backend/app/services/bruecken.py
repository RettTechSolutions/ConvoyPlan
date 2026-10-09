"""Brücken über der Route, für die keine Durchfahrtshöhe bekannt ist.

Stufe 1 (``durchfahrtshoehe.py``) weist aus, was GraphHopper weiß: ``maxheight``
an der unterführten Straße. Fehlt das Tag, ist die Kante für GraphHopper
unbegrenzt, und die Brücke darüber taucht nirgends auf. Hier wird sie gesucht:
alle Wege mit ``bridge=*`` im schmalen Korridor um die Route (Overpass), davon
die, die die Route tatsächlich *kreuzen*.

Was keine Kreuzung ist, fällt heraus:

- **Die Route fährt selbst über die Brücke.** GraphHopper baut die Linie aus
  denselben OSM-Knoten; die Schnittmenge ist dann ein Linienstück.
- **Die Brücke schließt nur an.** Ein Abzweig, dessen Brücke an einem Knoten der
  Route beginnt, berührt sie in einem Stützpunkt des Brückenwegs. Eine echte
  Überführung teilt keinen Knoten mit der Straße darunter.
- **Die Höhe ist bekannt.** Liegt die Kreuzung in einem Abschnitt aus Stufe 1,
  steht sie dort schon mit Zahl.

Bleibt die Ebene: Fährt die Route auf einer Brücke über eine andere Brücke
hinweg (Straßenbrücke über eine Bahnbrücke über einen Fluss), sieht das hier
aus wie eine Unterführung. Das ist selten und steht deshalb nur im Hinweistext.

Abschnitte auf Autobahn und Kraftfahrstraße werden gezählt, nicht aufgelistet:
dort kreuzt alle paar hundert Meter eine Überführung, und eine Liste mit achtzig
Einträgen liest niemand.
"""

from __future__ import annotations

from bisect import bisect_right
from math import hypot
from typing import Any

import shapely
from shapely.geometry import LineString, Point

from app.services import route_steps as route_steps_svc

# Korridor der Overpass-Abfrage um die vereinfachte Linie. Die Vereinfachung
# weicht höchstens ~5 m ab; eine kreuzende Brücke liegt auf der echten Linie.
KORRIDOR_M = 25
_VEREINFACHUNG_GRAD = 0.00005
# Stützpunkte je around-Filter — eine Abfrage mit Tausenden Punkten in einem
# Filter lehnen manche Overpass-Spiegel ab.
_STUECK = 400

# Kreuzungen näher beieinander sind ein Bauwerk (zwei Richtungsfahrbahnen,
# mehrere Gleise).
ZUSAMMEN_M = 40
# Abstand, in dem eine bekannte Höhe aus Stufe 1 die Kreuzung abdeckt.
BEKANNT_M = 30
# Toleranzen in Grad. GraphHopper und Overpass liefern dieselben OSM-Knoten,
# aber nicht zwingend bitgleich gerundet — exakte Vergleiche fänden statt
# „Route fährt darüber" eine Kette von Schnittpunkten.
# Ein Schnittpunkt so nah an einem Stützpunkt des Brückenwegs (~0,5 m) ist ein
# gemeinsamer Knoten: Anschluss, keine Überführung.
_KNOTEN_GRAD = 5e-6
# Zwei aufeinanderfolgende Stützpunkte so nah an der Route (~2 m): die Route
# fährt auf dem Brückenweg.
_AUF_DER_ROUTE_GRAD = 2e-5

SCHNELLSTRASSEN = {"motorway", "trunk"}

_FUSSWEGE = {"footway", "path", "cycleway", "pedestrian", "steps", "bridleway"}


def abfrage(coords: list) -> str:
    """Overpass-QL: alle Brückenwege im Korridor um die Route ``[[lon, lat], …]``."""
    linie = LineString([c[:2] for c in coords]).simplify(_VEREINFACHUNG_GRAD)
    punkte = list(linie.coords)
    filter_ = []
    for i in range(0, max(len(punkte) - 1, 1), _STUECK):
        stueck = punkte[i:i + _STUECK + 1]  # ein Punkt Überlappung, keine Lücke
        kette = ",".join(f"{lat:.6f},{lon:.6f}" for lon, lat in stueck)
        filter_.append(f'  way["bridge"]["bridge"!="no"](around:{KORRIDOR_M},{kette});')
    return "[out:json][timeout:90];\n(\n" + "\n".join(filter_) + "\n);\nout tags geom;\n"


def schnellstrassen(road_class_details: list, coords: list) -> list[list[int]]:
    """Meterbereiche ``[von, bis]`` auf Autobahn und Kraftfahrstraße.

    Aus GraphHoppers ``road_class``-Detail bei der Berechnung; die Brückensuche
    läuft später und hat es nicht mehr.
    """
    if not road_class_details or len(coords) < 2:
        return []
    along = route_steps_svc.cumulative_m(coords)
    letzter = len(coords) - 1
    out: list[list[int]] = []
    for eintrag in road_class_details:
        try:
            von, bis, klasse = int(eintrag[0]), int(eintrag[1]), str(eintrag[2]).lower()
        except (TypeError, ValueError, IndexError):
            continue
        if klasse not in SCHNELLSTRASSEN:
            continue
        a, b = round(along[max(0, min(von, letzter))]), round(along[max(0, min(bis, letzter))])
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _art(tags: dict) -> str:
    if tags.get("railway"):
        return "Eisenbahnbrücke"
    hw = tags.get("highway")
    if hw in _FUSSWEGE:
        return "Fuß-/Radwegbrücke"
    if hw:
        return "Straßenbrücke"
    if tags.get("waterway"):
        return "Kanalbrücke"
    return "Brücke"


def _name(tags: dict) -> str | None:
    for key in ("bridge:name", "name", "ref"):
        if tags.get(key):
            return str(tags[key])[:80]
    return None


class _Meterlinie:
    """Meter ab Start für einen Punkt auf der Route (Haversine, wie Stufe 1)."""

    def __init__(self, coords: list) -> None:
        self.linie = LineString([c[:2] for c in coords])
        self.grad = [0.0]
        for (x1, y1), (x2, y2) in zip(self.linie.coords, list(self.linie.coords)[1:]):
            self.grad.append(self.grad[-1] + hypot(x2 - x1, y2 - y1))
        self.meter = route_steps_svc.cumulative_m(coords)

    def __call__(self, punkt: Point) -> float:
        d = self.linie.project(punkt)
        i = max(0, min(bisect_right(self.grad, d) - 1, len(self.grad) - 2))
        seg = self.grad[i + 1] - self.grad[i]
        f = (d - self.grad[i]) / seg if seg else 0.0
        return self.meter[i] + f * (self.meter[i + 1] - self.meter[i])


def _bekannt(m: float, bekannte: list[dict]) -> bool:
    for e in bekannte or []:
        if e.get("m") is not None:
            von, toleranz = float(e["m"]), BEKANNT_M
        else:  # Eintrag von vor 0056: nur der km-Wert, auf 100 m gerundet
            von, toleranz = float(e.get("km", 0)) * 1000, 100
        bis = von + float(e.get("laenge_m") or 0)
        if von - toleranz <= m <= bis + toleranz:
            return True
    return False


def kreuzungen(
    coords: list,
    elemente: list[dict],
    bekannte: list[dict] | None = None,
    schnell: list[list[int]] | None = None,
) -> list[dict[str, Any]]:
    """Brücken über der Route ohne bekannte Höhe, in Fahrtrichtung.

    ``elemente`` sind Overpass-Wege mit ``geometry`` (``out geom``),
    ``bekannte`` die Einträge aus Stufe 1, ``schnell`` die Meterbereiche aus
    ``schnellstrassen()``.
    """
    if len(coords) < 2:
        return []
    meter = _Meterlinie(coords)
    route = meter.linie
    shapely.prepare(route)

    kandidaten: list[dict[str, Any]] = []
    for el in elemente or []:
        if el.get("type") != "way":
            continue
        punkte = [(g["lon"], g["lat"]) for g in el.get("geometry") or [] if g]
        if len(punkte) < 2:
            continue
        bruecke = LineString(punkte)
        if not route.intersects(bruecke):
            continue
        schnitt = route.intersection(bruecke)
        teile = getattr(schnitt, "geoms", [schnitt])
        if any(t.geom_type == "LineString" and t.length > 0 for t in teile):
            continue  # die Route fährt darüber
        nah = [route.distance(Point(p)) < _AUF_DER_ROUTE_GRAD for p in punkte]
        if any(a and b for a, b in zip(nah, nah[1:])):
            continue  # dasselbe, nur nicht bitgleich
        tags = el.get("tags") or {}
        for t in teile:
            if t.geom_type != "Point":
                continue
            if any(abs(t.x - x) < _KNOTEN_GRAD and abs(t.y - y) < _KNOTEN_GRAD for x, y in punkte):
                continue  # gemeinsamer Knoten: Anschluss, keine Überführung
            kandidaten.append({
                "m": meter(t), "lat": t.y, "lon": t.x,
                "art": _art(tags), "name": _name(tags), "osm_id": el.get("id"),
            })

    kandidaten.sort(key=lambda k: k["m"])
    gruppen: list[list[dict[str, Any]]] = []
    for k in kandidaten:
        if gruppen and k["m"] - gruppen[-1][0]["m"] <= ZUSAMMEN_M:
            gruppen[-1].append(k)
        else:
            gruppen.append([k])

    out: list[dict[str, Any]] = []
    for g in gruppen:
        erste = g[0]
        m = erste["m"]
        if _bekannt(m, bekannte or []):
            continue
        arten = list(dict.fromkeys(k["art"] for k in g))
        out.append({
            "km": round(m / 1000, 1),
            "m": round(m),
            "lat": erste["lat"],
            "lon": erste["lon"],
            "art": " / ".join(arten),
            "name": next((k["name"] for k in g if k["name"]), None),
            "osm_ids": list(dict.fromkeys(k["osm_id"] for k in g if k["osm_id"] is not None)),
            "schnellstrasse": any(von <= m <= bis for von, bis in schnell or []),
        })
    return out
