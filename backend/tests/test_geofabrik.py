import asyncio
import os

import pytest

from app.services import geofabrik
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


# ── Umriss-Geometrien (region_outlines / path_from_pbf_url) ─────────────────


def test_path_from_pbf_url_liefert_den_vollen_pfad():
    """Die Zuordnung laeuft ueber `urls.pbf`, nicht ueber `properties.id`: Die
    id ist im Index kontextfrei ("dach"), waehrend `.region` und das Panel
    durchgehend mit dem vollen Pfad arbeiten ("europe/dach")."""
    assert geofabrik.path_from_pbf_url(
        "https://download.geofabrik.de/europe/dach-latest.osm.pbf"
    ) == "europe/dach"
    assert geofabrik.path_from_pbf_url(
        "https://download.geofabrik.de/africa-latest.osm.pbf"
    ) == "africa"
    assert geofabrik.path_from_pbf_url(
        "https://download.geofabrik.de/north-america/us/california/norcal-latest.osm.pbf"
    ) == "north-america/us/california/norcal"


def test_path_from_pbf_url_lehnt_fremden_host_und_fehlendes_suffix_ab():
    """Der Index fuehrt neben `urls.pbf` auch Varianten auf
    osm-internal.download.geofabrik.de und ohne `-latest.osm.pbf`. Sie duerfen
    keinen Pfad ergeben, der zufaellig auf eine ausgewaehlte Region passt."""
    assert geofabrik.path_from_pbf_url(
        "https://osm-internal.download.geofabrik.de/europe/dach-latest-internal.osm.pbf"
    ) == ""
    assert geofabrik.path_from_pbf_url(
        "https://download.geofabrik.de/europe/dach-latest-free.shp.zip"
    ) == ""


def _index_client(features):
    class _FakeResponse:
        # `status_code` statt `raise_for_status()`: _index_once prueft den Code
        # selbst, weil es 429/5xx (wiederholen) von 404/403 (nicht wiederholen)
        # unterscheiden muss — `raise_for_status()` wirft fuer beide dasselbe.
        status_code = 200

        def json(self):
            return {"type": "FeatureCollection", "features": features}

    class _FakeAsyncClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return _FakeResponse()

    return _FakeAsyncClient


@pytest.mark.asyncio
async def test_region_outlines_ordnet_ueber_die_pbf_url_zu(monkeypatch):
    features = [
        {
            "properties": {
                "id": "dach",
                "name": "DACH",
                "urls": {"pbf": "https://download.geofabrik.de/europe/dach-latest.osm.pbf"},
            },
            "geometry": {"type": "MultiPolygon", "coordinates": [[[[0, 0]]]]},
        },
        {
            "properties": {
                "id": "italy",
                "name": "Italy",
                "urls": {"pbf": "https://download.geofabrik.de/europe/italy-latest.osm.pbf"},
            },
            "geometry": {"type": "Polygon", "coordinates": [[[9, 45]]]},
        },
    ]
    monkeypatch.setattr(geofabrik.httpx, "AsyncClient", _index_client(features))

    out = await geofabrik.region_outlines(["europe/italy"])

    # Nur die angefragte Region — die Geometrien der uebrigen 554 Eintraege
    # bleiben ungehalten (siehe Kommentar an region_outlines).
    assert list(out) == ["europe/italy"]
    assert out["europe/italy"]["type"] == "Polygon"


@pytest.mark.asyncio
async def test_region_outlines_ueberspringt_eintraege_ohne_geometrie(monkeypatch):
    """Ein Eintrag ohne `geometry` (oder ohne `urls.pbf`) darf den Aufruf nicht
    abbrechen — der Aufrufer merkt das Fehlen daran, dass der Pfad im Ergebnis
    fehlt, und entscheidet dann selbst."""
    features = [
        {
            "properties": {
                "id": "dach",
                "urls": {"pbf": "https://download.geofabrik.de/europe/dach-latest.osm.pbf"},
            },
            # kein "geometry"
        },
        {
            "properties": {"id": "shp-only", "urls": {"shp": "https://download.geofabrik.de/x.zip"}},
            "geometry": {"type": "Polygon", "coordinates": [[[0, 0]]]},
        },
    ]
    monkeypatch.setattr(geofabrik.httpx, "AsyncClient", _index_client(features))

    assert await geofabrik.region_outlines(["europe/dach"]) == {}


@pytest.mark.asyncio
async def test_region_outlines_ohne_pfade_fragt_nicht_an(monkeypatch):
    """Kein Netzwerkverkehr fuer eine leere Anfrage."""
    def _explode(*a, **k):
        raise AssertionError("Es darf kein HTTP-Aufruf stattfinden.")

    monkeypatch.setattr(geofabrik.httpx, "AsyncClient", _explode)
    assert await geofabrik.region_outlines([]) == {}


@pytest.mark.asyncio
async def test_region_outlines_meldet_connectionerror_bei_netzfehler(monkeypatch):
    class _FailingClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            raise geofabrik.httpx.ConnectError("kein Netz")

    monkeypatch.setattr(geofabrik.httpx, "AsyncClient", _FailingClient)

    with pytest.raises(ConnectionError):
        await geofabrik.region_outlines(["europe/dach"])


# ── Wiederholungen und Sammelabfrage ────────────────────────────────────────
#
# Befund aus dem Betrieb (16.09.2026): Im Panel stand „Geofabrik ist gerade
# nicht erreichbar" ueber einer Karte, der nichts fehlte. Ursache war keine
# echte Stoerung, sondern eine einzelne hakende Abfrage von sechs — ohne
# Wiederholung, und mit einer Meldung, die nicht sagte, welche.


class _ScriptedHeadClient:
    """Fake-Client, der je `head()`-Aufruf das naechste Element der Liste
    abarbeitet: eine Exception wird geworfen, alles andere zurueckgegeben."""

    def __init__(self, script, calls):
        self._script = list(script)
        self._calls = calls

    def __call__(self, *a, **k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def head(self, url):
        self._calls.append(url)
        naechste = self._script.pop(0)
        if isinstance(naechste, BaseException):
            raise naechste
        return naechste


class _Resp:
    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.headers = headers or {}


@pytest.mark.asyncio
async def test_head_size_bytes_wiederholt_nach_transportfehler(monkeypatch):
    """Ein Aussetzer beim ersten Versuch darf die Vorab-Rechnung nicht kippen."""
    import httpx as httpx_module

    from app.services import geofabrik

    calls = []
    monkeypatch.setattr(
        geofabrik.httpx, "AsyncClient",
        _ScriptedHeadClient(
            [httpx_module.ReadError("abgebrochen"), _Resp(200, {"content-length": "42"})],
            calls,
        ),
    )

    assert await geofabrik.head_size_bytes(
        "https://download.geofabrik.de/europe/dach-latest.osm.pbf"
    ) == 42
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_head_size_bytes_faengt_auch_readerror_ab(monkeypatch):
    """`ReadError`, `RemoteProtocolError` und `ProxyError` sind KEINE
    Unterklassen von `ConnectError`/`TimeoutException`.

    Frueher wurden nur diese beiden gefangen — ein Spiegel, der mitten in der
    Antwort abbricht, schlug damit als nackter 500 samt Stacktrace durch."""
    import httpx as httpx_module

    from app.services import geofabrik

    calls = []
    monkeypatch.setattr(
        geofabrik.httpx, "AsyncClient",
        _ScriptedHeadClient(
            [httpx_module.RemoteProtocolError("halbe Antwort")] * geofabrik._RETRY_ATTEMPTS,
            calls,
        ),
    )

    with pytest.raises(ConnectionError):
        await geofabrik.head_size_bytes(
            "https://download.geofabrik.de/europe/dach-latest.osm.pbf"
        )
    assert len(calls) == geofabrik._RETRY_ATTEMPTS


@pytest.mark.asyncio
async def test_head_size_bytes_wiederholt_nach_502_vom_spiegel(monkeypatch):
    """Ein 502 ist kein Urteil ueber die gewaehlte Region.

    Vorher wurde daraus sofort ein ValueError ("Extract nicht abrufbar
    (HTTP 502)") und damit ein 400 — eine Fehlermeldung, die dem Bediener
    seine Auswahl vorwarf, obwohl an ihr nichts falsch war."""
    from app.services import geofabrik

    calls = []
    monkeypatch.setattr(
        geofabrik.httpx, "AsyncClient",
        _ScriptedHeadClient(
            [_Resp(502), _Resp(200, {"content-length": "7"})], calls
        ),
    )

    assert await geofabrik.head_size_bytes(
        "https://download.geofabrik.de/europe/dach-latest.osm.pbf"
    ) == 7
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_head_size_bytes_wiederholt_404_nicht(monkeypatch):
    """Eine entfallene Region bleibt auch beim dritten Versuch entfallen —
    und der Fehler gehoert dem Aufrufer als 400, nicht als 503."""
    from app.services import geofabrik

    calls = []
    monkeypatch.setattr(
        geofabrik.httpx, "AsyncClient", _ScriptedHeadClient([_Resp(404)], calls)
    )

    with pytest.raises(ValueError):
        await geofabrik.head_size_bytes(
            "https://download.geofabrik.de/europe/dach-latest.osm.pbf"
        )
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_fehlermeldung_nennt_die_betroffene_region(monkeypatch):
    """Bei sechs Bestandteilen ist „Geofabrik nicht erreichbar" ohne Angabe,
    welcher gehakt hat, keine Auskunft."""
    import httpx as httpx_module

    from app.services import geofabrik

    monkeypatch.setattr(
        geofabrik.httpx, "AsyncClient",
        _ScriptedHeadClient(
            [httpx_module.ConnectError("weg")] * geofabrik._RETRY_ATTEMPTS, []
        ),
    )

    with pytest.raises(ConnectionError) as exc:
        await geofabrik.head_size_bytes(
            "https://download.geofabrik.de/europe/montenegro-latest.osm.pbf"
        )
    assert "europe/montenegro" in str(exc.value)


@pytest.mark.asyncio
async def test_head_size_bytes_lehnt_unlesbare_content_length_ab(monkeypatch):
    from app.services import geofabrik

    monkeypatch.setattr(
        geofabrik.httpx, "AsyncClient",
        _ScriptedHeadClient([_Resp(200, {"content-length": "viele"})], []),
    )

    with pytest.raises(ValueError) as exc:
        await geofabrik.head_size_bytes(
            "https://download.geofabrik.de/europe/dach-latest.osm.pbf"
        )
    # Nicht die rohe Python-Meldung ("invalid literal for int() ..."), die die
    # Route ungefiltert als 400-Text weiterreichen wuerde.
    assert "Content-Length" in str(exc.value)


@pytest.mark.asyncio
async def test_head_sizes_haelt_die_eingabereihenfolge(monkeypatch):
    """Die Abfragen laufen gleichzeitig, das Ergebnis folgt trotzdem der
    Eingabe — sonst landete die Groesse der einen Region bei der anderen."""
    from app.services import geofabrik

    groessen = {
        "https://download.geofabrik.de/europe/dach-latest.osm.pbf": 3,
        "https://download.geofabrik.de/europe/italy-latest.osm.pbf": 2,
        "https://download.geofabrik.de/europe/albania-latest.osm.pbf": 1,
    }

    async def _size(url):
        # Die kleinste Region antwortet zuerst — ohne Ordnung im Ergebnis
        # faenden sich die Werte vertauscht wieder.
        await asyncio.sleep(0.01 * groessen[url])
        return groessen[url]

    monkeypatch.setattr(geofabrik, "head_size_bytes", _size)

    assert await geofabrik.head_sizes(list(groessen)) == [3, 2, 1]


@pytest.mark.asyncio
async def test_head_sizes_laeuft_gleichzeitig(monkeypatch):
    """Nacheinander summierten sich bei sechs Bestandteilen sechs Zeitlimits."""
    from app.services import geofabrik

    laufend = 0
    hoechststand = 0

    async def _size(url):
        nonlocal laufend, hoechststand
        laufend += 1
        hoechststand = max(hoechststand, laufend)
        await asyncio.sleep(0.02)
        laufend -= 1
        return 1

    monkeypatch.setattr(geofabrik, "head_size_bytes", _size)

    urls = [f"https://download.geofabrik.de/europe/r{i}-latest.osm.pbf" for i in range(4)]
    assert await geofabrik.head_sizes(urls) == [1, 1, 1, 1]
    assert hoechststand > 1


@pytest.mark.asyncio
async def test_head_sizes_deckelt_die_gleichzeitigkeit(monkeypatch):
    """555 Regionen sind auswaehlbar — ohne Deckel liefe eine mutwillige
    Auswahl als hunderte gleichzeitige Verbindungen gegen einen fremden
    Server."""
    from app.services import geofabrik

    laufend = 0
    hoechststand = 0

    async def _size(url):
        nonlocal laufend, hoechststand
        laufend += 1
        hoechststand = max(hoechststand, laufend)
        await asyncio.sleep(0.01)
        laufend -= 1
        return 1

    monkeypatch.setattr(geofabrik, "head_size_bytes", _size)

    urls = [f"https://download.geofabrik.de/europe/r{i}-latest.osm.pbf" for i in range(20)]
    await geofabrik.head_sizes(urls)
    assert hoechststand <= geofabrik._MAX_PARALLEL_HEADS


@pytest.mark.asyncio
async def test_head_sizes_meldet_den_ersten_fehlschlag_der_eingabe(monkeypatch):
    """Sonst haengt die Meldung davon ab, welche Abfrage zufaellig zuerst
    fertig wurde — bei jedem Aufruf eine andere."""
    from app.services import geofabrik

    async def _size(url):
        if "italy" in url:
            await asyncio.sleep(0.02)
            raise ConnectionError("Italien hakt")
        if "albania" in url:
            raise ConnectionError("Albanien hakt")
        return 1

    monkeypatch.setattr(geofabrik, "head_size_bytes", _size)

    with pytest.raises(ConnectionError) as exc:
        await geofabrik.head_sizes([
            "https://download.geofabrik.de/europe/dach-latest.osm.pbf",
            "https://download.geofabrik.de/europe/italy-latest.osm.pbf",
            "https://download.geofabrik.de/europe/albania-latest.osm.pbf",
        ])
    assert "Italien" in str(exc.value)


@pytest.mark.asyncio
async def test_head_sizes_ohne_urls_fragt_nicht_an(monkeypatch):
    from app.services import geofabrik

    async def _size(url):  # pragma: no cover — darf nicht aufgerufen werden
        raise AssertionError("keine Abfrage erwartet")

    monkeypatch.setattr(geofabrik, "head_size_bytes", _size)
    assert await geofabrik.head_sizes([]) == []


# ── Index: unbrauchbare Antworten ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_index_wiederholt_nach_unbrauchbarer_antwort(monkeypatch):
    """Eine Proxy-Fehlerseite statt JSON war frueher ein 500 mit Stacktrace:
    `resp.json()["features"]` stand ungeprueft da."""
    from app.services import geofabrik

    monkeypatch.setattr(geofabrik, "_region_index_cache", None)
    versuche = []

    class _Resp:
        def __init__(self, kaputt):
            self.status_code = 200
            self._kaputt = kaputt

        def json(self):
            if self._kaputt:
                raise ValueError("kein JSON")
            return {"features": [{
                "properties": {
                    "id": "dach", "name": "DACH",
                    "urls": {"pbf": "https://download.geofabrik.de/europe/dach-latest.osm.pbf"},
                },
            }]}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            versuche.append(url)
            return _Resp(len(versuche) == 1)

    monkeypatch.setattr(geofabrik.httpx, "AsyncClient", _Client)

    entries = await geofabrik.list_regions()
    monkeypatch.setattr(geofabrik, "_region_index_cache", None)
    assert len(versuche) == 2
    assert [e.id for e in entries] == ["dach"]


@pytest.mark.asyncio
async def test_list_regions_uebergeht_unvollstaendige_eintraege(monkeypatch):
    """Ein einzelnes Feature ohne `properties.id` war ein KeyError — und damit
    ein 500 ueber der GESAMTEN Auswahlliste."""
    from app.services import geofabrik

    monkeypatch.setattr(geofabrik, "_region_index_cache", None)
    features = [
        {"properties": None},
        {"properties": {"name": "ohne id"}},
        {"properties": {"id": "leer", "name": "ohne urls"}},
        {"properties": {
            "id": "dach", "name": "DACH",
            "urls": {"pbf": "https://download.geofabrik.de/europe/dach-latest.osm.pbf"},
        }},
    ]
    monkeypatch.setattr(geofabrik.httpx, "AsyncClient", _index_client(features))

    entries = await geofabrik.list_regions()
    monkeypatch.setattr(geofabrik, "_region_index_cache", None)
    assert [e.id for e in entries] == ["dach"]
