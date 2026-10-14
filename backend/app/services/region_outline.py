"""Zusammenführen der Extract-Umrisse zu EINER überschneidungsfreien Fläche.

Warum das nicht ohne Geometrie-Bibliothek geht — der Befund, der dieses Modul
ausgelöst hat: In #444 wurden die äußeren Ringe der Bestandteile einfach
aneinandergehängt und im Frontend jeder davon als Loch in ein Weltpolygon
gestanzt. Die Begründung dort lautete, überlappende Löcher ergäben dieselbe
Aussparung wie ein echter Union. Das ist falsch.

MapLibre trianguliert Flächen mit earcut, und earcut setzt voraus, dass die
Löcher eines Polygons einander nicht schneiden. Nachgemessen mit earcut selbst
(`deviation()`, das Verhältnis von Dreiecks- zu Polygonfläche — 0 heißt
korrekt):

    disjunkte Loecher    : 14 Dreiecke, Abweichung 0.000e+0
    ueberlappende Loecher: 10 Dreiecke, Abweichung 5.381e-2

Bei einem einfachen Rechteckpaar bleibt es bei etwas zu wenig Fläche; bei
hunderten Ringen echter Landesumrisse zerfällt die Triangulierung und wirft
Dreiecke quer über die Karte. Genau so beobachtet: schwarze Keile von der
italienischen Ostküste über die Adria bis nach Albanien.

Dass sich die Bestandteile überhaupt überlappen, ist kein Sonderfall, sondern
die Regel. Geofabrik schneidet seine Extracts mit einem Puffer über die
Verwaltungsgrenze hinaus, damit Wege an der Grenze nicht zerrissen werden —
benachbarte Regionen greifen deshalb immer ineinander, und `europe/dach`
überlappt zusätzlich großflächig mit `europe/germany`, `europe/austria` und
`europe/switzerland`.

Die Aufgabe gehört ins Backend: shapely liegt dort ohnehin (`geometry.py`), und
das Frontend bleibt bei seiner einfachen Regel "erster Ring außen, Rest sind
Löcher" — die stimmt, sobald die Löcher disjunkt sind.

Der zweite Befund, nach der Vereinigung: Dunkle Dreiecke mitten in der Adria
(zwischen Italien und Kroatien, vor Albanien, bei Korfu). Das war kein Fehler
der Triangulierung mehr — die Geometrie war gültig. Es waren echte Lücken:
Geofabrik schneidet Extracts auf See entlang grober Linien, und zwischen den
Umrissen von Italien, Kroatien und Albanien bleibt offenes Meer, das keiner
davon abdeckt. Die Maske zeigte das korrekt als "nicht geladen", nur hat es
keine Bedeutung — auf See wird nicht geroutet. `wasserluecken_schliessen`
füllt deshalb, was ein morphologisches Schließen zwischen den Teilen ergänzt,
aber nur über Wasser. Land außerhalb der Region (Kosovo, Griechenland) bleibt
maskiert, die Region selbst wird nie kleiner.
"""
import gzip
import json
import logging
import pathlib
from functools import lru_cache

from shapely.errors import ShapelyError
from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient
from shapely.ops import unary_union
from shapely.strtree import STRtree

logger = logging.getLogger(__name__)

# Natural Earth 1:50m Land (gemeinfrei), auf drei Nachkommastellen gerundet.
# 1:50m statt 1:110m: Dort fehlen Inseln wie Malta oder die dalmatinischen,
# und eine fehlende Insel ausserhalb der Region wuerde als Wasser freigegeben.
_LANDFLAECHE = pathlib.Path(__file__).parent.parent / "data" / "landflaeche.geojson.gz"

# Radius des Schliessens in Grad. Die Luecken in der Adria sind bis gut 70 km
# breit (Strasse von Otranto); 1 Grad schliesst sie, ohne die Region ins
# offene Meer hinaus wachsen zu lassen — Schliessen fuellt nur Einbuchtungen.
SCHLIESS_RADIUS = 1.0
# Abstand, den gefuelltes Wasser von fremdem Land haelt (~2 km). Die Kueste
# aus 1:50m ist grob; lieber ein Streifen Meer zu viel maskiert als ein
# Streifen fremder Kueste freigegeben.
LAND_ABSTAND = 0.02
# Kleinere Stuecke sind Rechenrauschen entlang der Grenze, keine Luecke.
_MIN_LUECKE = 1e-3


def union_coordinates(
    geometries: list[dict], *, land: BaseGeometry | None = None
) -> list:
    """GeoJSON-Geometrien -> Koordinaten EINES MultiPolygons, überschneidungsfrei.

    `unary_union` verschmilzt alle Bestandteile und löst dabei jede Überlappung
    auf. Das Ergebnis kann weniger Ringe haben als die Eingabe (zwei Nachbarn
    werden zu einer Fläche) oder mehr (eine Überlappung kann eine Enklave
    einschließen) — beides ist richtig und beides verträgt das Frontend.

    Ungültige Eingaben werden vorher repariert (`buffer(0)`): Geofabriks
    Umrisse sind vereinfachte Polygone, und Vereinfachung kann
    Selbstberührungen erzeugen. Ohne die Reparatur bricht `unary_union` mit
    einer TopologyException ab und die Karte stünde ganz ohne Maske da.

    `orient` erzwingt zum Schluss die GeoJSON-Konvention (RFC 7946, §3.1.6):
    äußere Ringe gegen den Uhrzeigersinn, Löcher im Uhrzeigersinn. earcut
    braucht das nicht — es geht nach Ringreihenfolge, nicht nach Drehsinn —
    aber die Antwort ist damit auch für jeden anderen Leser korrekt.

    Mit `land` werden zusätzlich die Lücken über Wasser geschlossen (siehe
    `wasserluecken_schliessen`). Ohne bleibt es bei der reinen Vereinigung.
    """
    flaechen = []
    for geometry in geometries:
        try:
            geom = shape(geometry)
        except (ShapelyError, ValueError, AttributeError, KeyError, TypeError):
            # Ein Eintrag, den shapely nicht als Geometrie lesen kann, wird
            # uebersprungen statt den ganzen Umriss scheitern zu lassen. Der
            # Aufrufer bemerkt einen leeren Rueckgabewert und meldet 503.
            #
            # `ShapelyError` gehoert ausdruecklich dazu: Ein unbekannter
            # `type` wirft `GeometryTypeError`, und die erbt NICHT von
            # ValueError oder TypeError, sondern direkt von Exception. Ohne
            # sie schlug ein einziger unerwarteter Eintrag im Geofabrik-Index
            # als 500 bis zum Browser durch — dabei ist der Index Fremddaten,
            # deren Form wir nicht in der Hand haben.
            continue
        if geom.is_empty:
            continue
        if not geom.is_valid:
            geom = geom.buffer(0)
            if geom.is_empty:
                continue
        flaechen.append(geom)

    if not flaechen:
        return []

    vereinigt = unary_union(flaechen)
    if vereinigt.is_empty:
        return []
    if land is not None:
        vereinigt = wasserluecken_schliessen(vereinigt, land)

    if isinstance(vereinigt, Polygon):
        polygone = [vereinigt]
    elif isinstance(vereinigt, MultiPolygon):
        polygone = list(vereinigt.geoms)
    else:
        # GeometryCollection: kann entstehen, wenn sich Bestandteile nur in
        # einer Linie oder einem Punkt beruehren. Nur die Flaechen zaehlen —
        # eine Linie hat keine Ausdehnung und ergaebe kein Loch.
        polygone = [g for g in getattr(vereinigt, "geoms", []) if isinstance(g, Polygon)]
        if not polygone:
            return []

    return [_ring_coordinates(orient(p, sign=1.0)) for p in polygone]


def _ring_coordinates(polygon: Polygon) -> list:
    """Aeusserer Ring zuerst, dann die Loecher — die GeoJSON-Reihenfolge, auf
    die sich `buildMask()` im Frontend verlaesst."""
    return [
        list(map(list, polygon.exterior.coords)),
        *(list(map(list, ring.coords)) for ring in polygon.interiors),
    ]


def wasserluecken_schliessen(flaeche: BaseGeometry, land: BaseGeometry) -> BaseGeometry:
    """Füllt Einbuchtungen und Löcher der Region, soweit sie über Wasser liegen.

    Schließen (erst `buffer(+r)`, dann `buffer(-r)`) ergänzt genau das, was
    schmaler ist als 2r und zwischen Teilen der Region liegt — Löcher und
    Buchten, nicht das offene Meer davor. Davon bleibt nur, was nicht auf Land
    liegt: fremdes Land bleibt maskiert, denn dort fehlen tatsächlich Daten.
    Die Region selbst wird nur vergrößert, nie beschnitten.
    """
    try:
        geschlossen = flaeche.buffer(SCHLIESS_RADIUS, quad_segs=4).buffer(
            -SCHLIESS_RADIUS, quad_segs=4
        )
        nah = land.intersection(flaeche.envelope.buffer(2 * SCHLIESS_RADIUS))
        dazu = geschlossen.difference(flaeche).difference(nah.buffer(LAND_ABSTAND, quad_segs=2))
    except ShapelyError:
        # Reine Anzeige: lieber die Luecken zeigen als gar keine Maske.
        logger.warning("Wasserluecken im Regionsumriss nicht schliessbar", exc_info=True)
        return flaeche
    stuecke = [g for g in getattr(dazu, "geoms", [dazu]) if g.area >= _MIN_LUECKE]
    if not stuecke:
        return flaeche
    return unary_union([flaeche, *stuecke])


@lru_cache(maxsize=1)
def _alle_landflaechen() -> STRtree | None:
    try:
        with gzip.open(_LANDFLAECHE, "rt", encoding="utf-8") as f:
            geometrie = shape(json.load(f))
    except (OSError, ValueError, ShapelyError):
        logger.warning("Landflaechen nicht lesbar: %s", _LANDFLAECHE, exc_info=True)
        return None
    return STRtree(list(getattr(geometrie, "geoms", [geometrie])))


def landflaeche(geometries: list[dict]) -> BaseGeometry | None:
    """Landflächen im Umkreis der Bestandteile, oder None, wenn die Datei
    fehlt — dann bleibt es bei der reinen Vereinigung."""
    baum = _alle_landflaechen()
    if baum is None:
        return None
    rahmen = []
    for geometry in geometries:
        try:
            rahmen.append(shape(geometry).envelope)
        except (ShapelyError, ValueError, AttributeError, KeyError, TypeError):
            continue
    if not rahmen:
        return None
    suche = unary_union(rahmen).envelope.buffer(2 * SCHLIESS_RADIUS)
    treffer = baum.query(suche)
    return unary_union(baum.geometries.take(treffer))
