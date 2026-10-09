"""Firmware für Tracker: die Instanz holt das Manifest, prüft das Image und verteilt es.

Die Ablage (E9 im Plan des Tracker-Repos) ist ein **statisches HTTPS-Verzeichnis
je Kanal**: ``<TRACKER_FIRMWARE_URL>/<kanal>/manifest.json`` nennt Version,
SHA-256, Größe und Image; das Image liegt daneben. Vorgesehen ist
``https://firmware.convoyplan.de``, gefüllt von der CI des Tracker-Repos; eine
Instanz kann mit ``TRACKER_FIRMWARE_URL`` eine eigene Ablage nennen oder mit
leerem Wert ganz verzichten.

Die **Geräte laden nicht aus der Ablage, sondern von ihrer Instanz**:
``GET /api/geraete/firmware/<kanal>/<version>.bin`` mit ihrem Gerätetoken. Drei
Gründe, alle aus dem Einsatz: Ein Tracker mit IoT-SIM erreicht oft nur eine
Positivliste von Hosts, und seine Instanz steht darauf ohnehin. Die Instanz hat
das Image geprüft, bevor sie es anbietet (SHA-256 aus dem Manifest, Größe), und
einen Fehler in der Ablage sieht ein Mensch im Log statt dreißig Geräte im
Feld. Und ein Bündel-Download über eine schon offene TLS-Sitzung kostet das
Gerät weniger Strom als ein zweiter Host.

Angeboten wird nur, was **neuer** ist als der Stand, den das Gerät meldet, und
nur für seine Hardware, wenn das Manifest eine nennt. Was das Gerät damit tut
— nur im Stand, nur mit Akku, Rückfall bei fehlendem Kontakt —, steht im
Tracker-Repo (``docs/PLAN.md``, „Einspielen im Gerät"). Die Echtheit des Images
prüft am Ende der Bootloader des Geräts (MCUboot-Signatur); die Instanz prüft,
dass sie bekommen hat, was das Manifest versprach.

Das Manifest wird eine Stunde zwischengespeichert; ist die Ablage nicht
erreichbar, bleibt der letzte Stand gültig — ein Ausfall der Ablage darf kein
Gerät betreffen. Images liegen unter ``/uploads/firmware/<kanal>/<version>.bin``
(dasselbe Volume wie Logos und Bildschirmfotos) und werden einmal geholt.

Die Entscheidungen (``manifest_lesen``, ``angebot``) kommen ohne Netz aus und
werden von ``tests/test_firmware_angebot.py`` geprüft; die Ablage dort mit einem
``httpx.MockTransport``.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

KANAELE = ("stable", "beta", "nightly")
#: So lange gilt ein geholtes Manifest, bevor die Ablage erneut gefragt wird.
MANIFEST_TTL_S = 3600.0
#: Nach einem Fehler so lange nicht erneut fragen — ein Tracker fragt alle 30 s.
FEHLER_TTL_S = 300.0
#: Größer ist kein Tracker-Image. Schützt den Speicher vor einem falschen Link.
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MANIFEST_MAX_BYTES = 64 * 1024
TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=5.0, pool=5.0)
FIRMWARE_DIR = Path("/uploads/firmware")

_VERSION = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_HARDWARE = re.compile(r"^[A-Za-z0-9._-]{1,40}$")


def version_tupel(v: str) -> tuple:
    """``1.2.3`` < ``1.2.4-beta.1`` < ``1.2.4``; Unbekanntes sortiert ganz unten.

    Dieselbe Ordnung wie in der Referenz-Instanz des Simulators im Tracker-Repo —
    wer eine ändert, zieht die andere mit."""
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.]+))?", v.strip())
    if not m:
        return (-1,)
    kern = tuple(int(x) for x in m.groups()[:3])
    vor = m.group(4)
    if vor is None:
        return (*kern, 1, ())
    teile = tuple((0, int(x), "") if x.isdigit() else (1, 0, x) for x in vor.split("."))
    return (*kern, 0, teile)


@dataclass(frozen=True)
class Manifest:
    version: str
    sha256: str
    groesse: int
    #: Absolute HTTPS-Adresse des Images in der Ablage.
    url: str
    #: Hardware-Kennungen, für die das Image gilt; ``None`` = alle.
    hardware: tuple[str, ...] | None = None


def manifest_lesen(roh: Any, basis: str) -> Manifest | None:
    """Ein Manifest aus der Ablage, oder ``None``, wenn es nicht zu gebrauchen ist.

    *basis* ist das Kanalverzeichnis (``…/stable/``); ein relativer ``image``-Pfad
    gilt relativ dazu. Außerhalb von HTTPS gibt es nichts — ein Image über HTTP
    könnte unterwegs ersetzt werden, und der Bootloader merkt es zwar, aber
    erst nach dem Download.
    """
    if not isinstance(roh, dict):
        return None
    version = roh.get("version")
    sha = roh.get("sha256")
    groesse = roh.get("groesse")
    image = roh.get("image") or roh.get("url")
    if not isinstance(version, str) or not _VERSION.match(version.strip()):
        return None
    if not isinstance(sha, str) or not _SHA256.match(sha.strip().lower()):
        return None
    if isinstance(groesse, bool) or not isinstance(groesse, int) or not (0 < groesse <= MAX_IMAGE_BYTES):
        return None
    if not isinstance(image, str) or not image.strip():
        return None
    url = urljoin(basis if basis.endswith("/") else basis + "/", image.strip())
    if not url.startswith("https://"):
        return None
    hardware: tuple[str, ...] | None = None
    roh_hw = roh.get("hardware")
    if roh_hw is not None:
        if isinstance(roh_hw, str):
            roh_hw = [roh_hw]
        if not isinstance(roh_hw, list) or not roh_hw:
            return None
        if not all(isinstance(h, str) and _HARDWARE.match(h) for h in roh_hw):
            return None
        hardware = tuple(roh_hw)
    return Manifest(version.strip(), sha.strip().lower(), groesse, url, hardware)


def angebot(
    manifest: Manifest | None,
    geraete_firmware: str | None,
    geraete_hardware: str | None,
    instanz: str,
    kanal: str,
) -> dict[str, Any] | None:
    """Das ``firmware``-Feld der Anweisung: ein Angebot oder ``None``.

    Neuer als der gemeldete Stand, passend zur Hardware (wenn das Manifest eine
    nennt), und die Adresse zeigt auf **diese Instanz**, nicht in die Ablage.
    Ohne gemeldeten Stand wird nichts angeboten: Ein Gerät, das seine Fassung
    nicht kennt, soll nicht blind flashen."""
    if manifest is None or not geraete_firmware:
        return None
    if version_tupel(manifest.version) <= version_tupel(geraete_firmware):
        return None
    if manifest.hardware is not None and geraete_hardware not in manifest.hardware:
        return None
    return {
        "version": manifest.version,
        "url": f"{instanz.rstrip('/')}/api/geraete/firmware/{kanal}/{manifest.version}.bin",
        "sha256": manifest.sha256,
        "groesse": manifest.groesse,
    }


class Ablage:
    """Manifest je Kanal, zwischengespeichert; Images geprüft auf der Platte."""

    def __init__(
        self,
        basis: str,
        verzeichnis: Path = FIRMWARE_DIR,
        uhr: Callable[[], float] = time.monotonic,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.basis = basis.strip().rstrip("/")
        self.verzeichnis = verzeichnis
        self._uhr = uhr
        self._transport = transport
        # kanal → (Manifest oder None, gültig bis)
        self._cache: dict[str, tuple[Manifest | None, float]] = {}
        self._sperren: dict[str, asyncio.Lock] = {}

    @property
    def aktiv(self) -> bool:
        return bool(self.basis)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True, transport=self._transport)

    def bekannt(self, kanal: str) -> Manifest | None:
        """Nur aus dem Zwischenspeicher — für Listen, die nichts nachladen sollen."""
        eintrag = self._cache.get(kanal)
        return eintrag[0] if eintrag else None

    async def manifest(self, kanal: str) -> Manifest | None:
        if not self.aktiv or kanal not in KANAELE:
            return None
        eintrag = self._cache.get(kanal)
        if eintrag is not None and self._uhr() < eintrag[1]:
            return eintrag[0]
        basis = f"{self.basis}/{kanal}/"
        try:
            async with self._client() as client:
                antwort = await client.get(basis + "manifest.json", headers={"Accept": "application/json"})
            if antwort.status_code == 404:
                neu = None  # Kanal hat (noch) kein Image — kein Fehler.
            else:
                antwort.raise_for_status()
                if len(antwort.content) > MANIFEST_MAX_BYTES:
                    raise ValueError("Manifest zu groß")
                neu = manifest_lesen(antwort.json(), basis)
                if neu is None:
                    raise ValueError("Manifest unbrauchbar")
        except Exception as exc:
            # Der letzte bekannte Stand bleibt; ein Ausfall der Ablage darf kein
            # Gerät betreffen.
            logger.warning("Firmware-Manifest %s nicht geholt: %s", kanal, exc)
            alt = eintrag[0] if eintrag else None
            self._cache[kanal] = (alt, self._uhr() + FEHLER_TTL_S)
            return alt
        self._cache[kanal] = (neu, self._uhr() + MANIFEST_TTL_S)
        return neu

    def pfad(self, kanal: str, version: str) -> Path:
        return self.verzeichnis / kanal / f"{version}.bin"

    async def datei(self, kanal: str, version: str) -> Path | None:
        """Das geprüfte Image zu Kanal und Version — holt es beim ersten Mal.

        Nur, was das aktuelle Manifest nennt: Eine beliebige Version ließe sich
        sonst zum Download fremder Adressen missbrauchen."""
        manifest = await self.manifest(kanal)
        if manifest is None or manifest.version != version:
            return None
        ziel = self.pfad(kanal, version)
        if ziel.exists() and ziel.stat().st_size == manifest.groesse:
            return ziel
        sperre = self._sperren.setdefault(f"{kanal}/{version}", asyncio.Lock())
        async with sperre:
            if ziel.exists() and ziel.stat().st_size == manifest.groesse:
                return ziel
            return await self._laden(manifest, ziel)

    async def _laden(self, manifest: Manifest, ziel: Path) -> Path | None:
        ziel.parent.mkdir(parents=True, exist_ok=True)
        zwischen = ziel.with_suffix(".teil")
        pruefer = hashlib.sha256()
        gelesen = 0
        try:
            async with self._client() as client, client.stream("GET", manifest.url) as antwort:
                antwort.raise_for_status()
                with zwischen.open("wb") as f:
                    async for stueck in antwort.aiter_bytes():
                        gelesen += len(stueck)
                        if gelesen > manifest.groesse:
                            raise ValueError("Image größer als im Manifest")
                        pruefer.update(stueck)
                        f.write(stueck)
            if gelesen != manifest.groesse:
                raise ValueError(f"Image hat {gelesen} Bytes, Manifest nennt {manifest.groesse}")
            if pruefer.hexdigest() != manifest.sha256:
                raise ValueError("SHA-256 stimmt nicht mit dem Manifest überein")
        except Exception as exc:
            logger.warning("Firmware %s %s nicht geholt: %s", ziel.parent.name, manifest.version, exc)
            zwischen.unlink(missing_ok=True)
            return None
        zwischen.replace(ziel)
        logger.info("Firmware %s %s bereitgestellt (%d Bytes)", ziel.parent.name, manifest.version, gelesen)
        return ziel

    def leeren(self) -> None:
        self._cache.clear()


ablage = Ablage(settings.tracker_firmware_url)


async def fuer_geraet(kanal: str, firmware: str | None, hardware: str | None) -> dict[str, Any] | None:
    """Das Angebot für ein Gerät — oder ``None``."""
    return angebot(await ablage.manifest(kanal), firmware, hardware, settings.app_base_url, kanal)


def angebot_bekannt(kanal: str, firmware: str | None, hardware: str | None) -> str | None:
    """Die Version, die der Zwischenspeicher für dieses Gerät anböte — für den Org-Admin."""
    a = angebot(ablage.bekannt(kanal), firmware, hardware, settings.app_base_url, kanal)
    return a["version"] if a else None
