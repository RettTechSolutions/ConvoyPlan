import pytest

from app.services.geofabrik import validate_region_url

OK = "https://download.geofabrik.de/europe/dach-latest.osm.pbf"


def test_accepts_canonical_geofabrik_url():
    assert validate_region_url(OK) == OK


@pytest.mark.parametrize("canonical", [
    "https://download.geofabrik.de/europe/dach-latest.osm.pbf",
    "https://download.geofabrik.de/europe/germany/bayern-latest.osm.pbf",
    "https://download.geofabrik.de/north-america/us/california-latest.osm.pbf",
])
def test_returns_canonical_url_unchanged(canonical):
    # Fuer eine kanonische Geofabrik-URL muss die rekonstruierte Rueckgabe
    # bit-identisch mit der Eingabe sein - sonst wuerde die Rekonstruktion
    # in legitimen Faellen unbemerkt etwas veraendern.
    assert validate_region_url(canonical) == canonical


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
    "https://download.geofabrik.de/europe/dach-latest.osm.pbf;..",        # Traversal in params
    "https://download.geofabrik.de/europe/dach-latest.osm.pbf;type=binary", # harmlos aussehendes params-Segment
    "https://download.geofabrik.de:9999/europe/dach-latest.osm.pbf",  # nicht-Standard-Port
    "https://user@download.geofabrik.de/e-latest.osm.pbf",          # Userinfo
    "file:///data/osm/x-latest.osm.pbf",                            # anderes Schema
])
def test_rejects_everything_else(bad):
    with pytest.raises(ValueError):
        validate_region_url(bad)


# --- Fix-Runde 4: die drei Review-Findings -------------------------------

@pytest.mark.parametrize("bad", [
    "https://download.geofabrik.de/europe;x/dach-latest.osm.pbf",
    # ^ ';'-Segment MITTIG im Pfad: urlparse trennt nur hinter dem LETZTEN
    #   Segment nach .params ab, mittig bleibt es unbemerkt im Pfad stehen.
    "https://download.geofabrik.de/a\x00b-latest.osm.pbf",
    # ^ NUL-Byte im Pfad: besteht Endungs-, Prozent- und Traversal-Check und
    #   landet unveraendert im rekonstruierten Rueckgabewert.
])
def test_rejects_paths_outside_character_allowlist(bad):
    with pytest.raises(ValueError):
        validate_region_url(bad)


@pytest.mark.asyncio
async def test_head_size_bytes_requests_the_validated_url(monkeypatch):
    # head_size_bytes darf nicht das rohe Argument anfragen, sondern nur die
    # von validate_region_url rekonstruierte URL.
    import httpx as httpx_module

    from app.services import geofabrik

    requested = []

    class _FakeResponse:
        status_code = 200
        headers = {"content-length": "42"}

    class _FakeAsyncClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def head(self, url):
            requested.append(url)
            return _FakeResponse()

    monkeypatch.setattr(geofabrik.httpx, "AsyncClient", _FakeAsyncClient)

    raw = "https://DOWNLOAD.GEOFABRIK.DE/europe/dach-latest.osm.pbf"
    assert await geofabrik.head_size_bytes(raw) == 42
    assert requested == [validate_region_url(raw)]
    assert requested == ["https://download.geofabrik.de/europe/dach-latest.osm.pbf"]


@pytest.mark.asyncio
async def test_head_size_bytes_translates_connect_error(monkeypatch):
    # Fix-Runde 1, Important 2: ein Verbindungsfehler darf nicht als nackter
    # ValueError/500 durchschlagen, sondern muss eine sprechende Meldung
    # liefern, die die Route als 503 uebersetzen kann.
    import httpx as httpx_module

    from app.services import geofabrik

    class _FakeAsyncClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def head(self, url):
            raise httpx_module.ConnectError("boom")

    monkeypatch.setattr(geofabrik.httpx, "AsyncClient", _FakeAsyncClient)

    with pytest.raises(ConnectionError):
        await geofabrik.head_size_bytes(
            "https://download.geofabrik.de/europe/dach-latest.osm.pbf"
        )


@pytest.mark.asyncio
async def test_head_size_bytes_translates_timeout(monkeypatch):
    import httpx as httpx_module

    from app.services import geofabrik

    class _FakeAsyncClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def head(self, url):
            raise httpx_module.TimeoutException("boom")

    monkeypatch.setattr(geofabrik.httpx, "AsyncClient", _FakeAsyncClient)

    with pytest.raises(ConnectionError):
        await geofabrik.head_size_bytes(
            "https://download.geofabrik.de/europe/dach-latest.osm.pbf"
        )


@pytest.mark.parametrize("real", [
    # Reale Pfadformen aus dem echten Geofabrik-Index (index-v1.json,
    # 555 Regionen) — je Segmenttiefe 1 bis 5 mindestens ein Vertreter.
    # Die Zeichen-Allowlist darf keine davon ablehnen: ein Fehlalarm hier
    # faellt erst auf, wenn jemand genau diese Region auswaehlt.
    "https://download.geofabrik.de/africa-latest.osm.pbf",
    "https://download.geofabrik.de/australia-oceania-latest.osm.pbf",
    "https://download.geofabrik.de/europe/dach-latest.osm.pbf",
    "https://download.geofabrik.de/africa/canary-islands-latest.osm.pbf",
    "https://download.geofabrik.de/europe/azores-latest.osm.pbf",
    "https://download.geofabrik.de/north-america/us/california-latest.osm.pbf",
    "https://download.geofabrik.de/europe/france/alsace-latest.osm.pbf",
    "https://download.geofabrik.de/australia-oceania/australia/act-latest.osm.pbf",
    "https://download.geofabrik.de/north-america/us/california/norcal-latest.osm.pbf",
    "https://download.geofabrik.de/europe/germany/nordrhein-westfalen/arnsberg-regbez-latest.osm.pbf",
    "https://download.geofabrik.de/europe/united-kingdom/england/bedfordshire-latest.osm.pbf",
    "https://download.geofabrik.de/europe/united-kingdom/england/london/enfield-latest.osm.pbf",
])
def test_accepts_all_real_geofabrik_path_shapes(real):
    assert validate_region_url(real) == real


def test_rejects_pathological_dash_run_without_slowdown():
    # CodeQL (py/polynomial-redos) markierte die fruehere Pfad-Allowlist-
    # Regex `(?:/[a-z0-9][a-z0-9.-]*)+` als potenziell quadratisch fuer
    # Strings mit vielen '-'. Empirisch war das Verhalten in CPythons `re`
    # linear (siehe PR-Beschreibung) — die Segmentierung wurde trotzdem aus
    # der Regex herausgenommen (`str.split("/")` + flache Pro-Segment-Regex),
    # damit CodeQLs statische Pruefung das AST-Muster gar nicht mehr sieht.
    # Dieser Test ist der Regressionsschutz: ein absichtlich pathologischer
    # Pfad (50.000 '-', abgeschlossen von einem nicht erlaubten 'X') muss
    # weiterhin klar abgelehnt werden und darf dabei nicht spuerbar langsamer
    # sein als ein normaler Pfad.
    import time

    bad = "https://download.geofabrik.de/a" + "-" * 50_000 + "X-latest.osm.pbf"
    start = time.perf_counter()
    with pytest.raises(ValueError):
        validate_region_url(bad)
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0
