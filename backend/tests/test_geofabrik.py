import os

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


# --- Fix-Runde 5: Produktionsfehler "Extract nicht abrufbar (HTTP 302)" ---
#
# Ursache: Geofabrik beantwortet "-latest.osm.pbf" grundsaetzlich mit 302 auf
# die tagesaktuelle, datierte Datei - fuer JEDE Region, nicht nur boesartige
# Eingaben. Das bisherige `follow_redirects=False` mit "alles ausser 200 ist
# ein Fehler" hat die Vorab-Groessenschaetzung (Kernversprechen des
# Features) deshalb nie funktionieren lassen. Genau dieser Fehler ist
# entstanden, weil ALLE bisherigen Tests fuer head_size_bytes eine sofortige
# 200-Antwort gemockt haben - keiner hat je einen echten Geofabrik-302
# nachgebildet.

class _FakeRedirectResponse:
    def __init__(self, status_code, headers):
        self.status_code = status_code
        self.headers = headers


class _FakeRedirectClient:
    """Fake-httpx-Client, der eine Liste vorbereiteter Antworten der Reihe
    nach ausliefert - eine pro `head()`-Aufruf - und jede angefragte URL
    mitschreibt."""

    def __init__(self, responses, requested):
        self._responses = iter(responses)
        self._requested = requested

    def __call__(self, *a, **kw):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def head(self, url):
        self._requested.append(url)
        return next(self._responses)


@pytest.mark.asyncio
async def test_head_size_bytes_follows_redirect_chain_to_final_size(monkeypatch):
    # Simuliert exakt die in Produktion gemessene Kette: Sprung 1 auf
    # demselben Host (datierte Datei), Sprung 2 auf einen Spiegelserver
    # (anderer Host - legitim, da Geofabrik selbst die Weiterleitung waehlt).
    # Die Groesse muss aus der FINALEN (dritten) Antwort kommen, nicht aus
    # der ersten oder zweiten.
    from app.services import geofabrik

    requested = []
    responses = [
        _FakeRedirectResponse(
            302,
            {"location": "https://download.geofabrik.de/europe/dach-260903.osm.pbf"},
        ),
        _FakeRedirectResponse(
            302,
            {
                "location": "https://ftp5.gwdg.de/pub/misc/openstreetmap/"
                "dach-260903.osm.pbf"
            },
        ),
        _FakeRedirectResponse(200, {"content-length": "123456789"}),
    ]
    monkeypatch.setattr(
        geofabrik.httpx,
        "AsyncClient",
        _FakeRedirectClient(responses, requested),
    )

    canonical = "https://download.geofabrik.de/europe/dach-latest.osm.pbf"
    size = await geofabrik.head_size_bytes(canonical)

    assert size == 123456789
    assert len(requested) == 3
    assert requested[0] == canonical


@pytest.mark.asyncio
async def test_head_size_bytes_rejects_redirect_to_http(monkeypatch):
    # Jeder Sprung muss https bleiben - eine Weiterleitung auf http wird
    # abgelehnt, unabhaengig davon, ob ein spaeterer Sprung wieder zu https
    # zurueckkehren wuerde.
    from app.services import geofabrik

    requested = []
    responses = [
        _FakeRedirectResponse(
            302,
            {
                "location": "http://download.geofabrik.de/europe/"
                "dach-260903.osm.pbf"
            },
        ),
    ]
    monkeypatch.setattr(
        geofabrik.httpx,
        "AsyncClient",
        _FakeRedirectClient(responses, requested),
    )

    with pytest.raises(ValueError, match="unverschlüsselte"):
        await geofabrik.head_size_bytes(
            "https://download.geofabrik.de/europe/dach-latest.osm.pbf"
        )


@pytest.mark.asyncio
async def test_head_size_bytes_aborts_after_too_many_redirects(monkeypatch):
    # Hoechstens 5 Spruenge werden gefolgt. Eine Kette, die auch nach dem
    # 6. Request (5 gefolgte Weiterleitungen + die urspruengliche Anfrage)
    # noch immer weiterleitet, bricht mit einer sprechenden Fehlermeldung ab
    # statt endlos weiterzulaufen.
    from app.services import geofabrik

    requested = []
    # 7 Redirect-Antworten vorbereitet, damit ein Fehler in der
    # Abbruchbedingung (z.B. "6 statt 5" oder Off-by-one) auffiele, statt
    # dass der Test mangels weiterer Antworten mit StopIteration abbricht.
    responses = [
        _FakeRedirectResponse(
            302,
            {"location": "https://download.geofabrik.de/x-latest.osm.pbf"},
        )
        for _ in range(7)
    ]
    monkeypatch.setattr(
        geofabrik.httpx,
        "AsyncClient",
        _FakeRedirectClient(responses, requested),
    )

    with pytest.raises(ValueError, match="Zu viele Weiterleitungen"):
        await geofabrik.head_size_bytes(
            "https://download.geofabrik.de/europe/dach-latest.osm.pbf"
        )
    # Urspruengliche Anfrage + hoechstens 5 gefolgte Weiterleitungen = 6.
    assert len(requested) == 6


@pytest.mark.asyncio
async def test_head_size_bytes_missing_content_length_is_error(monkeypatch):
    # Fehlt Content-Length in der finalen Antwort, ist das ein Fehler mit
    # sprechender Meldung - kein stillschweigendes 0.
    from app.services import geofabrik

    requested = []
    responses = [_FakeRedirectResponse(200, {})]
    monkeypatch.setattr(
        geofabrik.httpx,
        "AsyncClient",
        _FakeRedirectClient(responses, requested),
    )

    with pytest.raises(ValueError, match="Content-Length"):
        await geofabrik.head_size_bytes(
            "https://download.geofabrik.de/europe/dach-latest.osm.pbf"
        )


@pytest.mark.asyncio
async def test_head_size_bytes_never_forwards_redirect_target_as_url(monkeypatch):
    # Bedingung, unter der das Folgen von Weiterleitungen ueberhaupt sicher
    # ist: der Rueckgabewert ist ausschliesslich eine Groesse (int), niemals
    # eine URL - der Spiegelserver-Pfad aus der Umleitung verlaesst
    # head_size_bytes an keiner Stelle. Die URL, die separat (per erneutem
    # validate_region_url-Aufruf) an den Updater weitergereicht wird, bleibt
    # deshalb unveraendert die rekonstruierte kanonische Adresse.
    from app.services import geofabrik

    mirror_url = "https://ftp5.gwdg.de/pub/misc/openstreetmap/dach-260903.osm.pbf"
    requested = []
    responses = [
        _FakeRedirectResponse(302, {"location": mirror_url}),
        _FakeRedirectResponse(200, {"content-length": "999"}),
    ]
    monkeypatch.setattr(
        geofabrik.httpx,
        "AsyncClient",
        _FakeRedirectClient(responses, requested),
    )

    canonical = "https://download.geofabrik.de/europe/dach-latest.osm.pbf"
    result = await geofabrik.head_size_bytes(canonical)

    assert result == 999
    assert not isinstance(result, str)
    # Der zweite (interne) Request ging an den Spiegelserver - aber das ist
    # eine rein lokale Angelegenheit von head_size_bytes.
    assert requested[1] == mirror_url
    # Die URL, die an den Updater geht, bleibt unveraendert die
    # rekonstruierte kanonische Adresse, nicht die Spiegelserver-Adresse.
    assert validate_region_url(canonical) == canonical
    assert validate_region_url(canonical) != mirror_url


@pytest.mark.skipif(
    os.environ.get("GEOFABRIK_LIVE_TEST") != "1",
    reason="Kontaktiert das echte download.geofabrik.de; nur mit "
    "GEOFABRIK_LIVE_TEST=1 gesetzt aktiv (kein Netz in CI).",
)
@pytest.mark.asyncio
async def test_head_size_bytes_against_real_geofabrik():
    # Genau der hier behobene Produktionsfehler ist entstanden, weil
    # AUSNAHMSLOS alle Tests den Netzaufruf gemockt haben - der 302 auf die
    # tagesaktuelle Datei kam erst live auf web.convoyplan.de zutage. Dieser
    # Test kontaktiert bewusst das echte Geofabrik, damit ein aehnlicher
    # Fehler (z.B. eine von Geofabrik geaenderte Redirect-Kette) kuenftig
    # schon lokal auffallen kann, statt erst in Produktion.
    from app.services import geofabrik

    # Liechtenstein ist der kleinste Geofabrik-Extract - schnell genug fuer
    # einen Testlauf, aber real genug, um die tatsaechliche 302-Kette zu
    # durchlaufen.
    size = await geofabrik.head_size_bytes(
        "https://download.geofabrik.de/europe/liechtenstein-latest.osm.pbf"
    )
    assert size > 0
