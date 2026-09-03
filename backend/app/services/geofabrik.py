"""Anbindung an Geofabrik: URL-Validierung und Größenabfrage für Kartenregionen.

Die validierte URL wandert an einen Container mit Docker-Socket, der sie
herunterlädt. `validate_region_url` ist deshalb eine Sicherheitsgrenze
(Allowlist), keine Formalie.
"""

from dataclasses import dataclass
from urllib.parse import unquote, urlparse

import httpx

_HOST = "download.geofabrik.de"
_SUFFIX = "-latest.osm.pbf"
_INDEX_URL = f"https://{_HOST}/index-v1.json"


def _fully_unquote(path: str) -> str:
    """Dekodiert Prozent-Escapes vollstaendig, auch mehrfach kodierte.

    `urlparse` dekodiert den Pfad nicht — ohne diesen Schritt wuerde
    z. B. `%2e%2e` (oder doppelt kodiert `%252e%252e`) den naiven
    Traversal-Check umgehen, obwohl er nach dem Dekodieren `..` ergibt.
    """
    previous = None
    current = path
    for _ in range(5):
        if current == previous:
            break
        previous = current
        current = unquote(current)
    return current


def validate_region_url(url: str) -> str:
    """Laesst ausschliesslich kanonische Geofabrik-Extract-URLs durch.

    Die URL wandert zum Updater, der sie mit Docker-Socket herunterlaedt —
    ohne diese Schranke waere das ein Primitiv fuer beliebige Downloads.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("Nur https ist zulässig.")
    if parsed.username or parsed.password:
        raise ValueError("Zugangsdaten in der URL sind nicht zulässig.")
    if parsed.hostname != _HOST:
        raise ValueError(f"Nur {_HOST} ist als Quelle zugelassen.")
    if not parsed.path.endswith(_SUFFIX):
        raise ValueError(f"Der Pfad muss auf {_SUFFIX} enden.")
    if ".." in _fully_unquote(parsed.path):
        raise ValueError("Der Pfad darf keine Rückwärtsverweise enthalten.")
    return url


def head_size_bytes(url: str) -> int:
    """Groesse des Extracts, ohne es zu laden. Folgt bewusst keinen Redirects."""
    validate_region_url(url)
    with httpx.Client(follow_redirects=False, timeout=15) as client:
        resp = client.head(url)
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
