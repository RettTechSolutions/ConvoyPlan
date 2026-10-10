"""Wurzelzertifikate für Tracker: die Instanz verteilt sie, das Gerät probiert sie aus.

Ein Tracker prüft das Zertifikat seiner Instanz gegen die eingebauten Wurzeln
(ISRG Root X1 und X2) und bis zu drei eigene, die der Org-Admin beim Einrichten
per USB mitgibt. Wechselt eine Instanz mit eigener Zertifizierungsstelle die CA,
müsste sonst jedes Gerät im Feld einmal an den Rechner (O10 im Tracker-Plan, jetzt
E13).

Deshalb kann der Betreiber das gewünschte Bündel als PEM-Datei ablegen
(``TRACKER_WURZELN``). Das Gerät meldet in ``hallo`` den Fingerabdruck seiner
eigenen Wurzeln (``wurzeln_sha256``); weicht er ab, hängt die Instanz das Bündel an
die Antwort. Übernommen wird es **vom Gerät**, und zwar erst, wenn eine Verbindung
damit gelungen ist (Probeverbindung, wie beim Einrichten). Ein falsches Bündel
sperrt also kein Gerät aus; die Instanz muss ihr eigenes Zertifikat dafür nicht
kennen, und das liegt ohnehin oft beim Proxy davor.

Der Wechsel geht in zwei Schritten: erst ``{alt, neu}``, bis die Tracker-Liste
alle Geräte als aktuell zeigt, dann das Zertifikat tauschen und das Bündel auf
``{neu}`` kürzen. Vor dem Tausch lehnt ein Gerät ``{neu}`` ab, weil die
Probeverbindung scheitert, und behält ``{alt, neu}``.

Drei Zustände der Einstellung, die man auseinanderhalten muss:

- **nicht gesetzt**: die Instanz verwaltet keine Wurzeln, das Gerät behält, was es
  beim Einrichten bekommen hat (bisheriges Verhalten);
- **Datei ohne Zertifikat**: keine eigenen Wurzeln — Geräte werfen ihre weg, sobald
  sie die Instanz auch ohne erreichen;
- **Datei unlesbar oder ungültig**: es wird **nichts** angeboten und laut geloggt.
  Ein halbes Bündel zu verteilen wäre schlimmer als keines.

Der Fingerabdruck hängt weder an der Reihenfolge noch an der PEM-Schreibweise:
SHA-256 über die sortierten SHA-256 der DER-Kodierungen, je eine Hex-Zeile, mit
``\\n`` verbunden. Ein leeres Bündel hat damit ``sha256("")``. Dieselbe Regel steht
im Protokoll des Tracker-Repos und im Simulator.

Geprüft ohne Datenbank und ohne Netz von ``tests/test_tracker_wurzeln.py``.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding

from app.config import settings

logger = logging.getLogger(__name__)

#: Wie beim Einrichten per USB (``PROTOKOLL.md``): mehr fasst der Schlüsselspeicher nicht.
MAX_WURZELN = 3
MAX_PEM_BYTES = 4096

_PEM = re.compile(
    r"-----BEGIN CERTIFICATE-----\s+[A-Za-z0-9+/=\s]+?-----END CERTIFICATE-----"
)
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_DER = Encoding.DER


@dataclass(frozen=True)
class Buendel:
    pem: tuple[str, ...]
    sha256: str


def fingerabdruck(ders: list[bytes]) -> str:
    zeilen = sorted(hashlib.sha256(der).hexdigest() for der in ders)
    return hashlib.sha256("\n".join(zeilen).encode()).hexdigest()


def lesen(text: str) -> Buendel:
    """PEM-Bündel prüfen. ``ValueError`` mit einer Meldung für den Betreiber."""
    bloecke = _PEM.findall(text)
    rest = _PEM.sub("", text).strip()
    if rest:
        raise ValueError("enthält etwas anderes als Zertifikate (privater Schlüssel?)")
    if len(bloecke) > MAX_WURZELN:
        raise ValueError(f"{len(bloecke)} Zertifikate, höchstens {MAX_WURZELN}")
    pem: list[str] = []
    ders: list[bytes] = []
    for i, block in enumerate(bloecke, start=1):
        if len(block.encode()) > MAX_PEM_BYTES:
            raise ValueError(f"Zertifikat {i} ist größer als {MAX_PEM_BYTES} Bytes")
        try:
            zert = x509.load_pem_x509_certificate(block.encode())
        except ValueError as e:
            raise ValueError(f"Zertifikat {i} ist nicht lesbar") from e
        try:
            ca = zert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
        except x509.ExtensionNotFound:
            ca = False
        if not ca:
            raise ValueError(f"Zertifikat {i} ist keine Zertifizierungsstelle (BasicConstraints CA)")
        der = zert.public_bytes(_DER)
        if der in ders:
            raise ValueError(f"Zertifikat {i} steht doppelt im Bündel")
        ders.append(der)
        pem.append(block.strip() + "\n")
    return Buendel(pem=tuple(pem), sha256=fingerabdruck(ders))


def gemeldet_lesen(daten: dict[str, Any]) -> str | None:
    """Fingerabdruck aus ``hallo``; alles andere als 64 Hex-Zeichen gilt als nicht gemeldet."""
    wert = daten.get("wurzeln_sha256")
    if isinstance(wert, str) and _SHA256_HEX.match(wert.strip().lower()):
        return wert.strip().lower()
    return None


def angebot(gemeldet: str | None, buendel: Buendel | None) -> dict[str, Any] | None:
    """Was ``hallo`` dem Gerät mitgibt. Nur bei Abweichung, und nie an ein Gerät,
    das keinen Fingerabdruck meldet: dessen Firmware kennt das Feld nicht."""
    if buendel is None or gemeldet is None or gemeldet == buendel.sha256:
        return None
    return {"sha256": buendel.sha256, "pem": list(buendel.pem)}


def aktuell(gespeichert: str | None, buendel: Buendel | None) -> bool | None:
    """Für die Tracker-Liste: ``None``, wenn die Instanz keine Wurzeln verwaltet."""
    if buendel is None:
        return None
    return gespeichert == buendel.sha256


# ── Einstellung lesen ───────────────────────────────────────────────────────

_stand: tuple[str, float, int] | None = None
_buendel: Buendel | None = None


def gewuenscht() -> Buendel | None:
    """Das Bündel aus ``TRACKER_WURZELN``, neu gelesen, sobald sich die Datei ändert."""
    global _stand, _buendel
    pfad = (settings.tracker_wurzeln or "").strip()
    if not pfad:
        _stand, _buendel = None, None
        return None
    try:
        info = Path(pfad).stat()
    except OSError as e:
        stand = (pfad, -1.0, -1)
        if stand != _stand:
            logger.error("TRACKER_WURZELN: %s nicht lesbar (%s) — es werden keine Wurzeln verteilt", pfad, e)
        _stand, _buendel = stand, None
        return None
    stand = (pfad, info.st_mtime, info.st_size)
    if stand == _stand:
        return _buendel
    _stand = stand
    try:
        _buendel = lesen(Path(pfad).read_text(encoding="utf-8"))
        logger.info(
            "TRACKER_WURZELN: %d Wurzel(n), Fingerabdruck %s", len(_buendel.pem), _buendel.sha256[:12]
        )
    except (OSError, UnicodeDecodeError, ValueError) as e:
        logger.error("TRACKER_WURZELN: %s — es werden keine Wurzeln verteilt", e)
        _buendel = None
    return _buendel
