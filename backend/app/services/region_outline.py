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
"""
from shapely.errors import ShapelyError
from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.geometry.polygon import orient
from shapely.ops import unary_union


def union_coordinates(geometries: list[dict]) -> list:
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
