import pytest

from app.services.geofabrik import validate_region_url

OK = "https://download.geofabrik.de/europe/dach-latest.osm.pbf"


def test_accepts_canonical_geofabrik_url():
    assert validate_region_url(OK) == OK


@pytest.mark.parametrize("bad", [
    "http://download.geofabrik.de/europe/dach-latest.osm.pbf",      # kein TLS
    "https://evil.example/europe/dach-latest.osm.pbf",              # fremder Host
    "https://download.geofabrik.de.evil.example/x-latest.osm.pbf",  # Suffix-Trick
    "https://download.geofabrik.de/europe/dach-latest.osm.bz2",     # falsche Endung
    "https://download.geofabrik.de/../etc/passwd-latest.osm.pbf",   # Traversal
    "https://download.geofabrik.de/%2e%2e/x-latest.osm.pbf",        # Traversal, prozent-kodiert
    "https://download.geofabrik.de/%25252525252e%25252525252e/x-latest.osm.pbf",
    # ^ Traversal, 6-fach prozent-kodiert (".." braucht 6x unquote(),
    #   das alte Iterationslimit von 5 gab hier stillschweigend auf)
    "https://download.geofabrik.de/%2525252525252e%2525252525252e/x-latest.osm.pbf",
    # ^ Traversal, 7-fach prozent-kodiert (noch tiefer als der 6-fach-Fall)
    "https://download.geofabrik.de/x-latest.osm.pbf?../../etc/passwd",  # Traversal im Query
    "https://download.geofabrik.de/x-latest.osm.pbf#../../etc/passwd",  # Traversal im Fragment
    "https://download.geofabrik.de/europe/dach-latest.osm.pbf?foo=bar", # harmloser Query
    "https://download.geofabrik.de/europe/dach-latest.osm.pbf#section", # harmloses Fragment
    "https://user@download.geofabrik.de/e-latest.osm.pbf",          # Userinfo
    "file:///data/osm/x-latest.osm.pbf",                            # anderes Schema
])
def test_rejects_everything_else(bad):
    with pytest.raises(ValueError):
        validate_region_url(bad)
