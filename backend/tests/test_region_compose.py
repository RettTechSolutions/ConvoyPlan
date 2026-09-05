from app.services.region_compose import (
    compose_hash, merged_filename, sources_value, parse_sources, overlapping,
    path_from_url,
)

DE, PL, CZ = "europe/germany", "europe/poland", "europe/czech-republic"
BY = "europe/germany/bayern"


def test_hash_ignoriert_die_reihenfolge():
    """Gleiche Auswahl, andere Reihenfolge -> gleicher Hash, kein Neubau."""
    assert compose_hash([DE, PL]) == compose_hash([PL, DE])


def test_hash_aendert_sich_bei_anderer_zusammensetzung():
    assert compose_hash([DE, PL]) != compose_hash([DE, CZ])


def test_hash_ist_acht_zeichen_und_stabil():
    h = compose_hash([DE, PL])
    assert len(h) == 8 and h == compose_hash([DE, PL])


def test_dateiname_traegt_den_hash():
    assert merged_filename([DE, PL]) == f"merged-{compose_hash([DE, PL])}.osm.pbf"


def test_sources_wird_sortiert_geschrieben_und_gelesen():
    v = sources_value([PL, DE, CZ])
    assert v == "|".join(sorted([DE, PL, CZ]))
    assert parse_sources(v) == sorted([DE, PL, CZ])


def test_parse_sources_leer_ergibt_leere_liste():
    assert parse_sources("") == []


def test_ueberlappung_wird_erkannt():
    """Deutschland und Bayern zusammen ist erlaubt, aber verschwenderisch."""
    assert overlapping([DE, BY]) == [(DE, BY)]
    assert overlapping([DE, PL]) == []


def test_namenspraefix_ohne_echte_hierarchie_wird_nicht_erkannt():
    """"europe/german" ist ein String-Praefix von "europe/germany", aber keine
    echte Unterregion davon -- ohne den "/"-Trenner wuerde ein naiver
    Praefixvergleich (str.startswith(a) statt str.startswith(a + "/")) hier
    faelschlich eine Ueberlappung melden. Vom Brief nicht abgedeckter Fall,
    hier ergaenzt."""
    assert overlapping(["europe/german", "europe/germany"]) == []


def test_pfad_aus_url():
    assert path_from_url(
        "https://download.geofabrik.de/europe/germany-latest.osm.pbf"
    ) == "europe/germany"


def test_pfad_aus_url_mehrstufig():
    assert path_from_url(
        "https://download.geofabrik.de/europe/germany/bayern-latest.osm.pbf"
    ) == "europe/germany/bayern"


def test_pfad_und_hash_hangen_zusammen():
    """Der Rundlauf, auf dem das ganze Verfahren beruht: aus URLs werden Pfade,
    aus sortierten Pfaden der Hash, aus dem Hash der Dateiname."""
    urls = [
        "https://download.geofabrik.de/europe/poland-latest.osm.pbf",
        "https://download.geofabrik.de/europe/germany-latest.osm.pbf",
    ]
    paths = [path_from_url(u) for u in urls]
    assert merged_filename(paths) == merged_filename(["europe/germany", "europe/poland"])
