"""Anbindung an Geofabrik: URL-Validierung und Größenabfrage für Kartenregionen.

Die validierte URL wandert an einen Container mit Docker-Socket, der sie
herunterlädt. `validate_region_url` ist deshalb eine Sicherheitsgrenze
(Allowlist), keine Formalie.
"""

import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

_HOST = "download.geofabrik.de"
_SUFFIX = "-latest.osm.pbf"
_INDEX_URL = f"https://{_HOST}/index-v1.json"

# Zeichen-Allowlist fuer den Pfad: ein oder mehrere Segmente, jedes
# beginnend mit Kleinbuchstabe oder Ziffer, danach zusaetzlich "-" und ".".
# Gegen den echten Geofabrik-Index geprueft (555 Regionen, Zeichenmenge des
# Pfades ausschliesslich a-z, "/", "-", "."; Segmenttiefen 1 bis 5) — kein
# einziger realer Pfad wird abgelehnt. Ziffern sind vorsorglich erlaubt,
# obwohl heute kein realer Pfad eine enthaelt.
_PATH_ALLOWLIST = re.compile(r"(?:/[a-z0-9][a-z0-9.-]*)+")


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
    (`_PATH_ALLOWLIST`). Grund: Einzelverbote decken den Pfad nur
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
    if not _PATH_ALLOWLIST.fullmatch(parsed.path):
        raise ValueError(
            "Der Pfad darf nur Kleinbuchstaben, Ziffern, '/', '-' und '.' "
            "enthalten."
        )
    return f"https://{_HOST}{parsed.path}"


async def head_size_bytes(url: str) -> int:
    """Groesse des Extracts, ohne es zu laden. Folgt bewusst keinen Redirects.

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
    `follow_redirects=False` und die Validierung am Anfang bleiben unveraendert
    bestehen — beide sind Ergebnis eigener Sicherheitsrunden in Task 2.
    """
    url = validate_region_url(url)
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=15) as client:
            resp = await client.head(url)
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        raise ConnectionError(
            "Geofabrik ist gerade nicht erreichbar. Bitte spaeter erneut "
            "versuchen."
        ) from exc
    if resp.status_code != 200:
        raise ValueError(f"Extract nicht abrufbar (HTTP {resp.status_code}).")
    return int(resp.headers.get("content-length", 0))


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

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(_INDEX_URL)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise ConnectionError(
            "Geofabrik-Index ist gerade nicht abrufbar. Bitte spaeter erneut "
            "versuchen."
        ) from exc

    features = resp.json()["features"]
    by_id = {f["properties"]["id"]: f["properties"] for f in features}

    def _path(entry_id: str) -> str:
        # Lauft die parent-Kette hoch bis zum Kontinent. `seen` schuetzt vor
        # einer Endlosschleife, falls der Index jemals einen Zyklus enthaelt
        # (heute nicht der Fall, aber billig abzusichern).
        names: list[str] = []
        seen: set[str] = set()
        current = by_id.get(entry_id)
        while current is not None and current["id"] not in seen:
            names.append(current["name"])
            seen.add(current["id"])
            current = by_id.get(current.get("parent"))
        return " › ".join(reversed(names))

    entries = [
        RegionEntry(
            id=props["id"],
            name=props["name"],
            path=_path(props["id"]),
            url=props["urls"]["pbf"],
            size_bytes=None,
        )
        for props in by_id.values()
        if "pbf" in props.get("urls", {})
    ]
    _region_index_cache = entries
    return entries
