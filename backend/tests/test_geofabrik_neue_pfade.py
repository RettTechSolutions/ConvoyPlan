"""Geofabriks neue Ablage: jede Region in ihrem eigenen Verzeichnis.

Seit November 2026 liefert Geofabrik `europe/germany/berlin-latest.osm.pbf`
nicht mehr aus (404), sondern `europe/germany/berlin/berlin-latest.osm.pbf`.
Zwei Zusagen haengen daran:

- Adressen im alten Schema — aus `.region`, `.env` oder einer gespeicherten
  Planung — werden gehoben statt abgelehnt; sonst stuende jede Bestands-
  installation beim naechsten Regionswechsel vor einer 404.
- Der Regionspfad bleibt derselbe. Er steckt im Hash der zusammengesetzten
  Region und damit im Dateinamen und im Graph-Fingerprint; aenderte er sich,
  baute jede Installation mit Kombination ihren Graphen neu.
"""

import pytest

from app.services import geofabrik, region_compose

ALT_NEU = [
    (
        "https://download.geofabrik.de/europe/dach-latest.osm.pbf",
        "https://download.geofabrik.de/europe/dach/dach-latest.osm.pbf",
        "europe/dach",
    ),
    (
        "https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf",
        "https://download.geofabrik.de/europe/germany/berlin/berlin-latest.osm.pbf",
        "europe/germany/berlin",
    ),
    (
        "https://download.geofabrik.de/europe/germany/bayern/oberbayern-latest.osm.pbf",
        "https://download.geofabrik.de/europe/germany/bayern/oberbayern/oberbayern-latest.osm.pbf",
        "europe/germany/bayern/oberbayern",
    ),
    # Kontinente lagen frueher direkt in der Wurzel.
    (
        "https://download.geofabrik.de/europe-latest.osm.pbf",
        "https://download.geofabrik.de/europe/europe-latest.osm.pbf",
        "europe",
    ),
    (
        "https://download.geofabrik.de/north-america/us/district-of-columbia-latest.osm.pbf",
        "https://download.geofabrik.de/north-america/us/district-of-columbia/district-of-columbia-latest.osm.pbf",
        "north-america/us/district-of-columbia",
    ),
]


@pytest.mark.parametrize("alt,neu,pfad", ALT_NEU)
def test_alte_adresse_wird_gehoben(alt, neu, pfad):
    assert geofabrik.validate_region_url(alt) == neu


@pytest.mark.parametrize("alt,neu,pfad", ALT_NEU)
def test_neue_adresse_bleibt_wie_sie_ist(alt, neu, pfad):
    assert geofabrik.validate_region_url(neu) == neu


@pytest.mark.parametrize("alt,neu,pfad", ALT_NEU)
def test_pfad_ist_in_beiden_schemata_derselbe(alt, neu, pfad):
    assert geofabrik.path_from_pbf_url(alt) == pfad
    assert geofabrik.path_from_pbf_url(neu) == pfad
    assert region_compose.path_from_url(alt) == pfad
    assert region_compose.path_from_url(neu) == pfad


@pytest.mark.parametrize("alt,neu,pfad", ALT_NEU)
def test_adresse_aus_pfad_ist_die_neue(alt, neu, pfad):
    assert geofabrik.pbf_url(pfad) == neu


def test_hash_einer_kombination_aendert_sich_nicht():
    alt = [
        "https://download.geofabrik.de/europe/germany-latest.osm.pbf",
        "https://download.geofabrik.de/europe/poland-latest.osm.pbf",
    ]
    neu = [
        "https://download.geofabrik.de/europe/germany/germany-latest.osm.pbf",
        "https://download.geofabrik.de/europe/poland/poland-latest.osm.pbf",
    ]
    pfade_alt = [region_compose.path_from_url(u) for u in alt]
    pfade_neu = [region_compose.path_from_url(u) for u in neu]
    assert pfade_alt == pfade_neu == ["europe/germany", "europe/poland"]
    assert region_compose.compose_hash(pfade_alt) == region_compose.compose_hash(pfade_neu)


@pytest.mark.parametrize(
    "url",
    [
        # Heben darf die Schranke nicht aufweichen: dieselben Ablehnungen wie zuvor.
        "https://download.geofabrik.de/europe/../dach-latest.osm.pbf",
        "https://download.geofabrik.de/europe/%2e%2e/dach-latest.osm.pbf",
        "https://download.geofabrik.de/Europe/dach-latest.osm.pbf",
        "https://evil.example/europe/dach/dach-latest.osm.pbf",
        "http://download.geofabrik.de/europe/dach/dach-latest.osm.pbf",
    ],
)
def test_schranke_bleibt(url):
    with pytest.raises(ValueError):
        geofabrik.validate_region_url(url)
