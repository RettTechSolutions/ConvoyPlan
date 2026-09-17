"""Anbindung an Geofabrik: URL-Validierung und Größenabfrage für Kartenregionen.

Die validierte URL wandert an einen Container mit Docker-Socket, der sie
herunterlädt. `validate_region_url` ist deshalb eine Sicherheitsgrenze
(Allowlist), keine Formalie.
"""

import asyncio
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx

_HOST = "download.geofabrik.de"
_SUFFIX = "-latest.osm.pbf"
_INDEX_URL = f"https://{_HOST}/index-v1.json"
_MAX_REDIRECTS = 5
# 301/302/303/307/308 — die von RFC 7231/7238 definierten Redirect-Codes mit
# `Location`-Header. Bewusst eine eigene, feste Menge statt `httpx`s
# `Response.is_redirect` (das jeden Code 300-399 als Redirect zaehlt, auch
# 300 "Multiple Choices" und 304 "Not Modified" ohne sinnvolles
# Umleitungsziel) — hier soll ausschliesslich echten Weiterleitungen gefolgt
# werden.
_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}

# ── Wiederholungen ──────────────────────────────────────────────────────────
# Jede Abfrage hier haengt an einem fremden Server, und `-latest.osm.pbf` wird
# grundsaetzlich auf einen Spiegel weitergeleitet (siehe head_size_bytes) —
# die Kette ist also laenger als ein Aufruf und entsprechend anfaellig. Ohne
# Wiederholung riss ein einzelner Aussetzer die ganze Vorab-Rechnung ab: bei
# einer kombinierten Region aus sechs Bestandteilen genuegte EINE hakende
# Abfrage, und im Panel stand „Geofabrik ist gerade nicht erreichbar" ueber
# einer Karte, der nichts fehlte (genau so im Betrieb am 16.09.2026 gesehen).
_RETRY_ATTEMPTS = 3
# Pausen ZWISCHEN den Versuchen, also eine weniger als Versuche. Tests setzen
# sie auf (0, 0) (autouse-Fixture in tests/conftest.py) — ein Test, der die
# Wartezeit selbst prueft, setzt sie zurueck.
_RETRY_BACKOFF_SECONDS = (1.0, 3.0)
# Statuscodes, hinter denen kein dauerhaftes Problem DIESER URL steckt,
# sondern eine Drosselung oder ein hakender Spiegel. Alles andere (404, 403,
# 410 …) ist eine Aussage ueber die angefragte Region selbst und wird nicht
# wiederholt — dreimal dieselbe 404 zu holen macht sie nicht wahrer.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
# Wieviele Groessenabfragen gleichzeitig laufen duerfen (siehe head_sizes).
_MAX_PARALLEL_HEADS = 4


class _TransientError(Exception):
    """Intern: ein Fehlversuch, der einen weiteren Versuch rechtfertigt.

    Bewusst NICHT nach aussen sichtbar: Aufrufer sehen am Ende entweder das
    Ergebnis, einen `ValueError` (die Anfrage selbst taugt nicht) oder einen
    `ConnectionError` (Geofabrik taugt gerade nicht) — dieselben zwei Faelle
    wie bisher, die die Route in 400 bzw. 503 uebersetzt.
    """


async def _with_retry(einmal, beschreibung: str):
    """Ruft `einmal()` bis zu `_RETRY_ATTEMPTS` mal auf.

    Wiederholt wird ausschliesslich bei `_TransientError`. Ein `ValueError`
    (Allowlist, unbrauchbare Antwort) und ein direkt geworfener
    `ConnectionError` kommen unveraendert durch — sie werden von einem
    zweiten Versuch nicht besser.

    Die Meldung nennt am Ende den letzten Grund. Das ist der Unterschied zur
    frueheren Fassung: Dort hiess jede Stoerung gleich, und bei sechs
    Bestandteilen stand im Panel nicht, welcher von ihnen gehakt hat.
    """
    letzter = "unbekannt"
    for versuch in range(_RETRY_ATTEMPTS):
        try:
            return await einmal()
        except _TransientError as exc:
            letzter = str(exc)
            if versuch + 1 >= _RETRY_ATTEMPTS:
                break
            pause = _RETRY_BACKOFF_SECONDS[
                min(versuch, len(_RETRY_BACKOFF_SECONDS) - 1)
            ]
            if pause:
                await asyncio.sleep(pause)
    raise ConnectionError(
        f"{beschreibung} ({_RETRY_ATTEMPTS} Versuche, zuletzt: {letzter}). "
        f"Bitte später erneut versuchen."
    )


# Zeichen-Allowlist fuer den Pfad: ein oder mehrere Segmente, jedes
# beginnend mit Kleinbuchstabe oder Ziffer, danach zusaetzlich "-" und ".".
# Gegen den echten Geofabrik-Index geprueft (555 Regionen, Zeichenmenge des
# Pfades ausschliesslich a-z, "/", "-", "."; Segmenttiefen 1 bis 5) — kein
# einziger realer Pfad wird abgelehnt. Ziffern sind vorsorglich erlaubt,
# obwohl heute kein realer Pfad eine enthaelt.
#
# Frueher eine einzige Regex `(?:/[a-z0-9][a-z0-9.-]*)+` mit `fullmatch`.
# CodeQL (py/polynomial-redos) markiert genau dieses AST-Muster als
# potenziell polynomiell: eine mit `+` wiederholte Gruppe, deren Inhalt
# selbst mit einem unbeschraenkten Quantor (`*`) endet. Empirische Messung
# (siehe PR-Beschreibung) zeigt fuer CPythons `re`-Engine lineares Wachstum
# bei wachsender Zahl von '-' — weil "/" aus der inneren Zeichenklasse
# ausgeschlossen ist, gibt es nur eine moegliche Segmentierung, also kein
# Backtracking ueber mehrere Aufteilungen. CodeQLs statische Pruefung
# bewertet das AST-Muster jedoch unabhaengig von dieser Disjunktheit — sie
# stuft die reine Form als riskant ein. Statt uns auf eine fuer uns nicht
# ueberpruefbare Sanitizer-Erkennung (z. B. eine Laengenpruefung als
# CodeQL-Barriere) zu verlassen, wird die Segmentierung strukturell aus der
# Regex herausgenommen: `str.split("/")` (kein Backtracking moeglich, da
# ohne Quantoren) uebernimmt die Aufteilung, eine flache Regex ohne aeussere
# Wiederholung prueft danach jedes Segment einzeln. Damit verschwindet das
# von CodeQL erkannte Muster strukturell, unabhaengig vom Messergebnis.
_PATH_SEGMENT = re.compile(r"[a-z0-9][a-z0-9.-]*")


def _path_matches_allowlist(path: str) -> bool:
    """Ersetzt das fruehere `_PATH_ALLOWLIST.fullmatch(path)`.

    Semantik identisch zur alten Regex `(?:/[a-z0-9][a-z0-9.-]*)+` mit
    `fullmatch`: der Pfad muss aus einem oder mehreren "/"-Segmenten
    bestehen, jedes Segment nicht leer und `_PATH_SEGMENT`-konform. Kein
    Segment (auch nicht das erste vor dem ersten "/") darf etwas anderes
    als das enthalten — `str.split("/")` liefert bei einem mit "/"
    beginnenden Pfad als erstes Element immer "", das hier explizit
    verlangt wird.
    """
    segments = path.split("/")
    if len(segments) < 2 or segments[0] != "":
        return False
    return all(_PATH_SEGMENT.fullmatch(segment) for segment in segments[1:])


def validate_region_url(url: str) -> str:
    """Laesst ausschliesslich kanonische Geofabrik-Extract-URLs durch.

    Die URL wandert zum Updater, der sie mit Docker-Socket herunterlaedt —
    ohne diese Schranke waere das ein Primitiv fuer beliebige Downloads.

    Prozent-Kodierung im Pfad wird grundsaetzlich abgelehnt statt dekodiert.
    Ein frueherer Ansatz dekodierte den Pfad mehrfach (mit festem Iterations-
    limit) und prüfte danach auf "..". Das ist umgehbar: Bei tief genug
    verschachtelter Kodierung (z. B. sechsfach kodiertes "..") konvergiert
    die Dekodierung innerhalb des Limits nicht, die Schleife bricht dennoch
    "sauber" ab und der Rest-String enthält kein literales ".." mehr — die
    URL würde durchgelassen. Jedes Limit ist so mit einer tief genug
    verschachtelten Kodierung unterlaufbar. Eine kanonische
    Geofabrik-Extract-URL besteht ausschliesslich aus Kleinbuchstaben,
    Ziffern, "/", "-" und "." und braucht daher niemals eine
    Prozent-Kodierung — jedes "%" im Pfad ist folglich verdächtig und wird
    fail-closed abgelehnt, ohne ueberhaupt zu dekodieren.

    Ebenso abgelehnt werden Query, Fragment, das rfc3986-Params-Segment
    (`;...` direkt hinter dem letzten Pfadsegment, von `urlparse` separat als
    `.params` gefuehrt statt im Pfad) und ein expliziter Port: alle laufen am
    Traversal-Check auf `parsed.path` vorbei, und eine kanonische
    Geofabrik-Extract-URL hat keins von ihnen.

    Der Pfad muss zusaetzlich einer Zeichen-Allowlist genuegen
    (`_path_matches_allowlist`). Grund: Einzelverbote decken den Pfad nur
    stichprobenartig ab. Zwei Beispiele, die alle bisherigen Einzelpruefungen
    bestanden haben: ein *mittig* platziertes ';'-Segment
    (".../europe;x/dach-latest.osm.pbf") — `urlparse` trennt nur hinter dem
    *letzten* Segment nach `.params` ab, mittig bleibt es unbemerkt im Pfad —
    und ein NUL-Byte (0x00) mitten im Pfad, das Endungs-,
    Prozent- und Traversal-Check uebersteht und unveraendert in der
    rekonstruierten URL landet. Statt beide einzeln nachzuziehen (das Muster
    der Runden 1 bis 3), erlaubt die Allowlist nur noch, was reale
    Geofabrik-Pfade tatsaechlich enthalten. Alles andere — auch kuenftige
    Sonderzeichen, an die heute niemand denkt — faellt automatisch heraus.

    Rueckgabewert: nicht die unveraenderte Eingabe, sondern eine aus den
    geprueften Bestandteilen rekonstruierte URL (Schema + `_HOST` + Pfad).
    Grund: drei Runden in Folge haben je einen anderen `urlparse`-Bestandteil
    gefunden, der ungeprueft durchgereicht wurde (erst Query/Fragment, dann
    Params, dann Port) — jede neue Einzelpruefung haette nur die naechste
    Instanz dieses Musters verschoben. Die Rekonstruktion macht das
    strukturell unmoeglich: das Ergebnis kann nur Schema, `_HOST` und den
    bereits geprueften Pfad enthalten, unabhaengig davon, ob ein zukuenftiger
    URL-Bestandteil, an den heute niemand gedacht hat, durch eine
    Einzelpruefung rutscht. Die Einzelpruefungen bleiben trotzdem bestehen —
    sie liefern eine konkrete, sprechende Fehlermeldung statt nur eine andere
    (rekonstruierte) URL kommentarlos zurueckzugeben. Fuer eine kanonische
    Geofabrik-URL ist die Rekonstruktion bit-identisch mit der Eingabe.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("Nur https ist zulässig.")
    if parsed.username or parsed.password:
        raise ValueError("Zugangsdaten in der URL sind nicht zulässig.")
    if parsed.hostname != _HOST:
        raise ValueError(f"Nur {_HOST} ist als Quelle zugelassen.")
    if parsed.port is not None:
        raise ValueError("Ein Port in der URL ist nicht zulässig.")
    if parsed.query:
        raise ValueError("Query-Parameter in der URL sind nicht zulässig.")
    if parsed.fragment:
        raise ValueError("Ein Fragment in der URL ist nicht zulässig.")
    if parsed.params:
        raise ValueError("Ein Params-Segment (';...') in der URL ist nicht zulässig.")
    if not parsed.path.endswith(_SUFFIX):
        raise ValueError(f"Der Pfad muss auf {_SUFFIX} enden.")
    if "%" in parsed.path:
        raise ValueError("Prozent-kodierte Zeichen im Pfad sind nicht zulässig.")
    if ".." in parsed.path:
        raise ValueError("Der Pfad darf keine Rückwärtsverweise enthalten.")
    if not _path_matches_allowlist(parsed.path):
        raise ValueError(
            "Der Pfad darf nur Kleinbuchstaben, Ziffern, '/', '-' und '.' "
            "enthalten."
        )
    return f"https://{_HOST}{parsed.path}"


async def _head_final_response(client, url: str):
    """Folgt der Weiterleitungskette und liefert die LETZTE Antwort.

    Weiterleitungen (Fix-Runde 5, Produktionsfehler): Geofabrik beantwortet
    `-latest.osm.pbf` grundsaetzlich mit `302` auf die tagesaktuelle,
    datierte Datei — teils auf demselben Host, teils (bei groesseren
    Regionen wie `europe` oder `europe/germany`) auf einen Spiegelserver
    (z. B. `ftp5.gwdg.de`). Ein striktes `follow_redirects=False` mit
    "alles ausser 200 ist ein Fehler" — das Ergebnis der Sicherheitsrunden
    in Task 2 — hat damit **jede** Region unbrauchbar gemacht, nicht nur
    boesartige Eingaben: Die Vorab-Groessenschaetzung, die zentrale Zusage
    dieses Features, hat nie funktioniert.

    Das frueher gehaertete Prinzip bleibt bestehen, wird aber praeziser
    gefasst: nicht "keine Weiterleitung", sondern "nur eine Weiterleitung,
    die WEITERHIN nichts als Groesseninformation zurueckgibt und deren Ziel
    kontrolliert bleibt". Konkret:
      - Jeder Sprung wird einzeln mit `client.head()` (kein automatisches
        `follow_redirects=True` von httpx, das den Pfad verschleiern wuerde)
        nachvollzogen, hoechstens `_MAX_REDIRECTS` (5) davon — genug fuer
        jede reale Geofabrik/Spiegel-Kette, aber keine Endlosschleife.
      - Jedes Sprungziel (`Location`-Header) muss selbst wieder `https`
        sein; ein Sprung auf `http` wird abgelehnt, auch wenn ein
        nachfolgender Sprung wieder zu `https` zurueckkehren wuerde — sonst
        koennte ein kompromittierter oder falsch konfigurierter Zwischen-
        schritt den Rest der Kette unverschluesselt weiterreichen.
      - Der ZielHOST darf dagegen wechseln (Spiegelserver wie `ftp5.gwdg.de`
        sind Geofabriks legitime Wahl fuer grosse Extracts, nicht die des
        Nutzers) — die Umleitung waehlt Geofabrik selbst, nicht die von
        `validate_region_url` bereits auf `download.geofabrik.de`
        eingegrenzte Nutzereingabe. Eine Host-Allowlist fuer Sprungziele
        wuerde bedeuten, jeden aktuellen und kuenftigen Geofabrik-Spiegel
        zu kennen und zu pflegen — genau die Bruechigkeit, die
        `validate_region_url` an anderer Stelle bewusst vermeidet.
      - Es wird niemals ein Body geholt (`HEAD` bleibt durchgaengig) und
        niemals die tatsaechlich kontaktierte URL zurueckgegeben oder
        geloggt: `current_url` unten ist eine rein lokale Variable, die
        diese Funktion nie verlaesst. Die URL, die an den Updater geht,
        bleibt unveraendert die von `validate_region_url` rekonstruierte
        `https://download.geofabrik.de/…`-Adresse — der Updater bekommt nie
        einen Spiegelserver-Pfad zu Gesicht. Genau diese Trennung
        (Umleitungsweg nur fuer die Groessenabfrage nutzen, niemals fuer den
        Download-Auftrag) ist die Bedingung, unter der das Folgen von
        Weiterleitungen hier sicher ist, ohne die urspruengliche
        Sicherheitsabsicht (kein Primitiv fuer beliebige Downloads) zu
        unterlaufen.

    Ein Transportfehler wird als `_TransientError` gemeldet, damit
    `_with_retry` es noch einmal versuchen kann. Gefangen wird
    `httpx.HTTPError`, nicht nur `ConnectError`/`TimeoutException`: Deren
    Geschwister `ReadError`, `RemoteProtocolError` und `ProxyError` traten
    frueher als nackter 500 samt Stacktrace nach aussen — beobachtbar
    ausgerechnet dann, wenn ein Spiegel mitten in der Antwort abbricht.
    """
    current_url = url
    for _ in range(_MAX_REDIRECTS + 1):
        try:
            resp = await client.head(current_url)
        except httpx.HTTPError as exc:
            raise _TransientError(f"{type(exc).__name__}: {exc}") from exc
        if resp.status_code not in _REDIRECT_STATUS_CODES:
            return resp
        location = resp.headers.get("location")
        if not location:
            raise ValueError(
                "Weiterleitung ohne Ziel-Adresse (Location-Header fehlt)."
            )
        next_url = urljoin(current_url, location)
        if urlparse(next_url).scheme != "https":
            raise ValueError(
                "Weiterleitung auf eine unverschlüsselte Adresse "
                "(kein https) ist nicht zulässig."
            )
        current_url = next_url
    raise ValueError(f"Zu viele Weiterleitungen (mehr als {_MAX_REDIRECTS}).")


async def _head_size_once(url: str) -> int:
    """Ein Versuch: Groesse des Extracts hinter der (bereits validierten) URL."""
    async with httpx.AsyncClient(follow_redirects=False, timeout=15) as client:
        resp = await _head_final_response(client, url)
    if resp.status_code in _RETRYABLE_STATUS:
        # Kein Urteil ueber die Region, sondern ueber den Moment: Drosselung
        # oder ein hakender Spiegel. Frueher wurde daraus sofort ein 400
        # ("Extract nicht abrufbar (HTTP 502)") — eine Fehlermeldung, die dem
        # Bediener seine Auswahl vorwarf, obwohl an ihr nichts falsch war.
        raise _TransientError(f"HTTP {resp.status_code}")
    if resp.status_code != 200:
        raise ValueError(f"Extract nicht abrufbar (HTTP {resp.status_code}).")
    content_length = resp.headers.get("content-length")
    if content_length is None:
        raise ValueError(
            "Antwort enthält keine Content-Length; Extract-Größe nicht "
            "ermittelbar."
        )
    try:
        size = int(content_length)
    except ValueError as exc:
        # `int()` wuerde hier einen ValueError mit der rohen Python-Meldung
        # werfen ("invalid literal for int() with base 10: …"), und die Route
        # reicht jeden ValueError als 400 mit genau diesem Text durch.
        raise ValueError(
            f"Content-Length ist keine Zahl: {content_length!r}."
        ) from exc
    if size < 0:
        raise ValueError(f"Content-Length ist negativ: {size}.")
    return size


async def head_size_bytes(url: str) -> int:
    """Groesse des Extracts, ohne es zu laden. Folgt Weiterleitungen kontrolliert.

    Angefragt wird ausschliesslich die von `validate_region_url`
    rekonstruierte URL, niemals das rohe Argument. Das rohe `url` wird
    deshalb direkt ueberschrieben — so ist es unterhalb dieser Zeile gar
    nicht mehr erreichbar und kann nicht versehentlich weiterverwendet
    werden. Frueher wurde der Rueckgabewert verworfen und `client.head(url)`
    mit dem Originalstring aufgerufen; die Rekonstruktion aus Runde 3 wirkte
    damit an der einzigen Stelle nicht, an der sie gebraucht wird.

    Async (Fix-Runde 1 zu Task 4): der bisherige synchrone `httpx.Client`
    blockierte den Event-Loop bis zu `timeout` Sekunden lang — und damit
    saemtliche anderen gleichzeitigen Anfragen des Backends, nicht nur diese.
    `httpx.AsyncClient` ist im Rest des Backends ohnehin der durchgaengige
    Standard (siehe z. B. app/services/weather.py, routing.py, geocoding.py).

    Die Weiterleitungskette steht in `_head_final_response`, die Wiederholung
    bei Stoerungen in `_with_retry`. Die Meldung nennt die Region: Bei einer
    kombinierten Karte laufen sechs dieser Abfragen, und „Geofabrik ist
    gerade nicht erreichbar" ohne Angabe, welche davon, half niemandem.
    """
    url = validate_region_url(url)
    region = path_from_pbf_url(url) or url
    return await _with_retry(
        lambda: _head_size_once(url),
        f"Geofabrik ist gerade nicht erreichbar ({region})",
    )


async def head_sizes(urls: list[str]) -> list[int]:
    """Groessen mehrerer Extracts — in der Reihenfolge der Eingabe.

    Bis zu `_MAX_PARALLEL_HEADS` Abfragen laufen gleichzeitig. Der Grund ist
    nicht Eleganz, sondern eine Zeitgrenze: Nacheinander summierten sich bei
    sechs Bestandteilen sechs Ketten aus Anfrage, Weiterleitung und
    Spiegel-Antwort — in Summe bis zu 90 Sekunden Zeitlimit, und mit den
    Wiederholungen von `_with_retry` noch mehr. Ein Panel, das eine halbe
    Minute nichts sagt, sieht kaputt aus, und der Browser gibt irgendwann von
    selbst auf.

    Der Deckel ist Absicht: 555 Regionen sind auswaehlbar, und ohne ihn
    riefe eine mutwillige Auswahl hunderte gleichzeitige Verbindungen gegen
    einen fremden Server auf.

    Scheitert ein Bestandteil, scheitert die ganze Abfrage — die Summe ueber
    fuenf von sechs Extracts waere eine falsche Zahl, kein Teilergebnis. Die
    Ausnahme des ERSTEN Bestandteils in Eingabereihenfolge wird geworfen,
    damit die Meldung nicht davon abhaengt, welche Abfrage zufaellig zuerst
    fertig war.
    """
    if not urls:
        return []
    sperre = asyncio.Semaphore(_MAX_PARALLEL_HEADS)

    async def _eine(u: str) -> int:
        async with sperre:
            return await head_size_bytes(u)

    ergebnisse = await asyncio.gather(
        *(_eine(u) for u in urls), return_exceptions=True
    )
    for ergebnis in ergebnisse:
        if isinstance(ergebnis, BaseException):
            raise ergebnis
    return list(ergebnisse)


@dataclass(frozen=True)
class RegionEntry:
    id: str
    name: str
    path: str        # "Europe › Germany › Bayern"
    url: str
    size_bytes: int | None


# Prozessweiter Cache des Geofabrik-Index (siehe list_regions()). Bewusst ein
# einfaches Modul-Attribut statt z. B. functools.lru_cache: der Index aendert
# sich praktisch nie, ein TTL waere unnoetige Komplexitaet, und Tests koennen
# das Attribut direkt zuruecksetzen (monkeypatch.setattr(geofabrik,
# "_region_index_cache", None)).
_region_index_cache: list[RegionEntry] | None = None


async def _index_once() -> list[dict]:
    """Ein Versuch: `index-v1.json` holen und die Feature-Liste herausgeben."""
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(_INDEX_URL)
        except httpx.HTTPError as exc:
            raise _TransientError(f"{type(exc).__name__}: {exc}") from exc
    if resp.status_code in _RETRYABLE_STATUS:
        raise _TransientError(f"HTTP {resp.status_code}")
    if resp.status_code != 200:
        # Kein Wiederholungsfall: Ein 404 oder 403 auf den Index bleibt auch
        # beim dritten Versuch einer. Trotzdem ein ConnectionError und kein
        # ValueError — an der Anfrage liegt es nicht, die Adresse ist eine
        # Konstante dieses Moduls.
        raise ConnectionError(
            f"Geofabrik-Index ist gerade nicht abrufbar (HTTP "
            f"{resp.status_code})."
        )
    try:
        daten = resp.json()
        features = daten["features"]
    except (ValueError, KeyError, TypeError) as exc:
        # Eine Fehlerseite eines Proxys, eine halbe Antwort, ein geaendertes
        # Format: Frueher schlug das als nackter 500 mit Stacktrace durch,
        # weil `resp.json()["features"]` ungeprueft blieb. Ein zweiter Versuch
        # ist es wert — eine abgeschnittene Antwort ist der haeufigste Grund.
        raise _TransientError(f"Antwort unbrauchbar ({type(exc).__name__})") from exc
    if not isinstance(features, list):
        raise _TransientError("Antwort unbrauchbar (features ist keine Liste)")
    return features


async def _fetch_index_features() -> list[dict]:
    """Die Feature-Liste des Geofabrik-Index, mit Wiederholung bei Stoerungen.

    Gemeinsame Grundlage von `list_regions()` (wertet `properties` aus) und
    `region_outlines()` (wertet `geometry` aus). Vorher stand derselbe
    Abruf zweimal im Modul — und mit ihm zweimal dieselbe Luecke: ein
    `resp.json()`, das jede nicht-JSON-Antwort in einen 500 verwandelte.
    """
    return await _with_retry(_index_once, "Geofabrik-Index ist gerade nicht abrufbar")


async def list_regions() -> list["RegionEntry"]:
    """Liste aller Regionen aus dem Geofabrik-Index, mit Pfad aus der Eltern-Kette.

    Der Index (`index-v1.json`, eine GeoJSON-FeatureCollection mit 555
    Eintraegen) wird beim ersten Aufruf per HTTP geholt und danach
    prozessweit im Speicher gehalten (~3,8 MB JSON) — sich das bei jedem
    Panel-Aufruf neu zu holen waere unnoetiger Traffic fuer eine Liste, die
    sich praktisch nie aendert.

    Jeder Eintrag traegt neben `urls.pbf` weitere URL-Varianten (u. a.
    `urls.shp`, `urls.pbf-internal`, `urls.history`, `urls.taginfo`,
    `urls.updates`). `urls.pbf-internal` und `urls.history` zeigen auf einen
    ANDEREN Host (osm-internal.download.geofabrik.de), den
    `validate_region_url()` zu Recht ablehnt — es wird deshalb ausschliesslich
    `urls.pbf` verwendet. Ein Eintrag ohne `urls.pbf` wird uebersprungen statt
    mit einer fremden URL aufzutauchen, die beim Ausloesen ohnehin an der
    Allowlist scheitern wuerde.
    """
    global _region_index_cache
    if _region_index_cache is not None:
        return _region_index_cache

    features = await _fetch_index_features()
    # Eintraege ohne `properties.id` werden uebergangen statt den ganzen Abruf
    # zu sprengen: Vorher war das ein KeyError und damit ein 500 ueber der
    # gesamten Regionsliste — wegen eines einzigen unvollstaendigen Features
    # haette niemand mehr eine Region auswaehlen koennen.
    by_id: dict[str, dict] = {}
    for f in features:
        props = f.get("properties") if isinstance(f, dict) else None
        if isinstance(props, dict) and isinstance(props.get("id"), str):
            by_id[props["id"]] = props

    def _path(entry_id: str) -> str:
        # Lauft die parent-Kette hoch bis zum Kontinent. `seen` schuetzt vor
        # einer Endlosschleife, falls der Index jemals einen Zyklus enthaelt
        # (heute nicht der Fall, aber billig abzusichern).
        names: list[str] = []
        seen: set[str] = set()
        current = by_id.get(entry_id)
        while current is not None and current["id"] not in seen:
            names.append(str(current.get("name") or current["id"]))
            seen.add(current["id"])
            current = by_id.get(current.get("parent"))
        return " › ".join(reversed(names))

    entries = [
        RegionEntry(
            id=props["id"],
            name=str(props.get("name") or props["id"]),
            path=_path(props["id"]),
            url=props["urls"]["pbf"],
            size_bytes=None,
        )
        for props in by_id.values()
        if isinstance(props.get("urls"), dict)
        and isinstance(props["urls"].get("pbf"), str)
    ]
    # Kein Dead Code, auch wenn eine statische Analyse das Modul-Attribut
    # sonst nirgends verwendet sieht: Es wird ueber `global` (Zeile oben,
    # `global _region_index_cache`) in dieser Funktion geschrieben und beim
    # naechsten Aufruf gelesen (Fruehausstieg direkt danach, `if
    # _region_index_cache is not None: return _region_index_cache`).
    # Statische Checks, die Funktionskoerper nicht auswerten, sehen nur die
    # Modulebene und halten die Zuweisung faelschlich fuer unbenutzt.
    _region_index_cache = entries
    return entries


# Umrisse (siehe region_outlines()). Bewusst NICHT zusammen mit
# `_region_index_cache` gehalten: Die Geometrien machen den Loewenanteil der
# 3,8 MB des Index aus, waehrend die Auswahlliste im Panel nur Namen und URLs
# braucht. Sie prozessweit vorzuhalten hiesse, in jedem Uvicorn-Worker ein paar
# Megabyte fuer 554 Umrisse zu halten, von denen genau einer je gebraucht wird.
# Der Aufrufer cacht stattdessen das fertige Ergebnis (siehe
# `region.py:region_outline`), sodass dieser Weg pro Prozess und Region genau
# einmal laeuft.
async def region_outlines(paths: list[str]) -> dict[str, dict]:
    """Umriss-Geometrien der genannten Regionspfade, `{pfad: geometry}`.

    `index-v1.json` ist eine echte GeoJSON-FeatureCollection: Jedes Feature
    traegt neben den `properties` (die `list_regions()` auswertet) auch die
    `geometry` des Extract-Umrisses — genau der Bereich, den Geofabrik in diese
    Datei schneidet. Das ist die einzige Quelle, die immer zur tatsaechlich
    geladenen Karte passt; ein mitgeliefertes GeoJSON kann das nicht, weil es
    den Regionswechsel im Panel nicht mitbekommt.

    Zugeordnet wird ueber `urls.pbf`, NICHT ueber `properties.id`: Die id ist
    im Index kontextfrei ("dach", "bayern"), waehrend `.region` und das Panel
    durchgehend mit dem vollen Pfad arbeiten ("europe/dach"). Die URL ist der
    einzige Wert, aus dem sich dieser Pfad eindeutig ableiten laesst.

    Fehlende Pfade fehlen im Ergebnis — der Aufrufer entscheidet, ob ein
    unvollstaendiger Umriss noch taugt.
    """
    wanted = set(paths)
    if not wanted:
        return {}

    features = await _fetch_index_features()

    out: dict[str, dict] = {}
    for feature in features:
        # Durchgaengig defensiv: `feature["properties"]` kann im JSON auch
        # `null` sein, und `.get("properties", {})` liefert dann None statt
        # eines Dicts — der naechste `.get()` waere ein AttributeError und
        # damit ein 500 fuer die ganze Kartenmaske.
        props = feature.get("properties") if isinstance(feature, dict) else None
        urls = props.get("urls") if isinstance(props, dict) else None
        pbf = urls.get("pbf") if isinstance(urls, dict) else None
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
        if not isinstance(pbf, str) or not geometry:
            continue
        path = path_from_pbf_url(pbf)
        if path in wanted:
            out[path] = geometry
    return out


def path_from_pbf_url(url: str) -> str:
    """`https://download.geofabrik.de/europe/dach-latest.osm.pbf` -> `europe/dach`.

    Dieselbe Abbildung wie `region_compose.path_from_url()`, hier noch einmal
    ohne dessen Import: `region_compose` beschreibt das Zusammenfuehren
    mehrerer Regionen und haette in einem reinen Geofabrik-Adapter nichts zu
    suchen — die Abhaengigkeit liefe der Schichtung entgegen. Die Fassung hier
    ist strenger, weil sie ausschliesslich auf Index-URLs angewandt wird: Sie
    verlangt Host und Suffix und liefert sonst einen leeren Pfad, der in
    keiner Auswahl vorkommt.
    """
    parsed = urlparse(url)
    if parsed.netloc != _HOST:
        return ""
    path = parsed.path.lstrip("/")
    if not path.endswith(_SUFFIX):
        return ""
    return path[: -len(_SUFFIX)]
