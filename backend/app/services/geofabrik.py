"""Anbindung an Geofabrik: URL-Validierung und Größenabfrage für Kartenregionen.

Die validierte URL wandert an einen Container mit Docker-Socket, der sie
herunterlädt. `validate_region_url` ist deshalb eine Sicherheitsgrenze
(Allowlist), keine Formalie.
"""

from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

_HOST = "download.geofabrik.de"
_SUFFIX = "-latest.osm.pbf"
_INDEX_URL = f"https://{_HOST}/index-v1.json"


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

    Ebenso abgelehnt werden Query, Fragment und das rfc3986-Params-Segment
    (`;...` direkt hinter dem letzten Pfadsegment, von `urlparse` separat als
    `.params` gefuehrt statt im Pfad): alle drei laufen am Traversal-Check
    auf `parsed.path` vorbei, und eine kanonische Geofabrik-Extract-URL hat
    keins von ihnen.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("Nur https ist zulässig.")
    if parsed.username or parsed.password:
        raise ValueError("Zugangsdaten in der URL sind nicht zulässig.")
    if parsed.hostname != _HOST:
        raise ValueError(f"Nur {_HOST} ist als Quelle zugelassen.")
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
