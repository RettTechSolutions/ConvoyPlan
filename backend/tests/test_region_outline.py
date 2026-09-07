"""Tests fuer `region_outline.union_coordinates` — das Zusammenfuehren der
Extract-Umrisse zu einer ueberschneidungsfreien Flaeche.

Hintergrund steht im Modul-Docstring von `app/services/region_outline.py`:
MapLibre trianguliert mit earcut, und earcut setzt disjunkte Loecher voraus.
Ueberlappende Bestandteile ergaben schwarze Keile quer ueber die Karte.
"""
from shapely.geometry import shape
from shapely.ops import unary_union

from app.services.region_outline import union_coordinates


def _als_flaeche(coordinates: list):
    return shape({"type": "MultiPolygon", "coordinates": coordinates})


QUADRAT = {"type": "Polygon", "coordinates": [[[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]]}
UEBERLAPPEND = {
    "type": "Polygon",
    "coordinates": [[[10, 10], [30, 10], [30, 30], [10, 30], [10, 10]]],
}
ENTFERNT = {
    "type": "Polygon",
    "coordinates": [[[40, 40], [60, 40], [60, 60], [40, 60], [40, 40]]],
}


def test_ueberlappende_teile_werden_eine_flaeche():
    """Der Kern: zwei sich schneidende Bestandteile ergeben EIN Polygon.
    Vorher blieben es zwei Ringe, die sich schnitten — und genau daran
    zerbrach earcut."""
    coords = union_coordinates([QUADRAT, UEBERLAPPEND])
    assert len(coords) == 1
    assert _als_flaeche(coords).equals(
        unary_union([shape(QUADRAT), shape(UEBERLAPPEND)])
    )


def test_entfernte_teile_bleiben_getrennt():
    """Kehrseite: Was nicht zusammenhaengt, darf nicht zusammengezogen werden —
    sonst wuerde die Maske Gebiet freigeben, das gar nicht geladen ist."""
    coords = union_coordinates([QUADRAT, ENTFERNT])
    assert len(coords) == 2


def test_flaeche_bleibt_erhalten():
    """Weder verlieren noch erfinden: Die vereinigte Flaeche ist genau die
    Summe der Bestandteile abzueglich ihrer Ueberschneidung."""
    coords = union_coordinates([QUADRAT, UEBERLAPPEND])
    erwartet = unary_union([shape(QUADRAT), shape(UEBERLAPPEND)])
    assert _als_flaeche(coords).symmetric_difference(erwartet).is_empty


def test_kein_ring_schneidet_einen_anderen():
    """Die eigentliche Zusage an das Frontend: `buildMask()` stanzt jeden
    aeusseren Ring als Loch in ein Weltpolygon, und earcut braucht diese
    Loecher disjunkt."""
    coords = union_coordinates([QUADRAT, UEBERLAPPEND, ENTFERNT])
    ringe = [shape({"type": "Polygon", "coordinates": [p[0]]}) for p in coords]
    for i, a in enumerate(ringe):
        for b in ringe[i + 1:]:
            assert not a.intersection(b).area


def test_loecher_bleiben_loecher():
    """Ein Bestandteil mit Enklave behaelt sie. `buildMask()` maskiert
    Innenringe wieder — sie gehoeren nicht zur Region, und dafuer muessen sie
    ueberhaupt erst erhalten bleiben."""
    mit_loch = {
        "type": "Polygon",
        "coordinates": [
            [[0, 0], [30, 0], [30, 30], [0, 30], [0, 0]],
            [[10, 10], [10, 20], [20, 20], [20, 10], [10, 10]],
        ],
    }
    coords = union_coordinates([mit_loch])
    assert len(coords) == 1
    assert len(coords[0]) == 2, "aeusserer Ring plus Loch"
    assert shape({"type": "Polygon", "coordinates": coords[0]}).area == 900 - 100


def test_aeussere_ringe_laufen_gegen_den_uhrzeigersinn():
    """GeoJSON-Konvention (RFC 7946 §3.1.6). earcut braucht das nicht — es geht
    nach Ringreihenfolge — aber die Antwort ist ein oeffentlicher Endpunkt und
    soll auch fuer andere Leser stimmen."""
    coords = union_coordinates([QUADRAT])
    ring = coords[0][0]
    flaeche = sum(
        (ring[i + 1][0] - ring[i][0]) * (ring[i + 1][1] + ring[i][1])
        for i in range(len(ring) - 1)
    )
    assert flaeche < 0, "negative Shoelace-Summe = gegen den Uhrzeigersinn"


def test_multipolygon_wird_flachgeklopft():
    """Ein Bestandteil kann selbst aus mehreren Flaechen bestehen (Festland
    plus Inseln) — jede davon gehoert einzeln in das Ergebnis."""
    multi = {
        "type": "MultiPolygon",
        "coordinates": [QUADRAT["coordinates"], ENTFERNT["coordinates"]],
    }
    assert len(union_coordinates([multi])) == 2


def test_ungueltige_geometrie_wird_repariert():
    """Vereinfachte Umrisse koennen Selbstberuehrungen enthalten. Ohne
    Reparatur braeche `unary_union` ab und die Karte bliebe ohne Maske."""
    sanduhr = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [10, 10], [10, 0], [0, 10], [0, 0]]],
    }
    coords = union_coordinates([sanduhr])
    assert coords
    assert _als_flaeche(coords).is_valid


def test_unlesbare_eintraege_werden_uebersprungen():
    """Ein kaputter Eintrag darf nicht den ganzen Umriss verhindern — die
    uebrigen Bestandteile sind ja brauchbar."""
    coords = union_coordinates([{"type": "Quatsch"}, QUADRAT])
    assert len(coords) == 1
    assert _als_flaeche(coords).equals(shape(QUADRAT))


def test_leere_eingabe_ergibt_leere_liste():
    """Der Aufrufer meldet daraufhin 503 statt eine leere Maske zu zeichnen."""
    assert union_coordinates([]) == []
    assert union_coordinates([{"type": "Polygon", "coordinates": []}]) == []
