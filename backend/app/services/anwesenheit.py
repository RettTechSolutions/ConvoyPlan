"""Wer arbeitet gerade im Portal — für den Updater.

Der Updater hält ein *automatisches* Update zurück, solange Nutzer oder
Demo-Nutzer angemeldet sind (``docker/updater/anwesenheit.sh``). Er hat keine
Datenbank und keinen Zugang zur Aktivitäts-Registry dieses Prozesses; das
Backend schreibt ihm die Zahlen deshalb alle ``INTERVALL_S`` Sekunden in das
geteilte Volume, wie Kanal und Modus (``update_check``).

Fahrer-Links zählen auch, solange ihr Konvoi aktiv ist oder läuft: wer fährt, verliert beim Deploy den
Live-Kanal, und gerade dort fällt das auf. Sie laufen über den WebSocket
``track_ws``, den die Aktivitäts-Middleware nicht sieht, und haben kein Konto —
deshalb ein eigenes kleines Register hier (:class:`FahrerLinks`).

Superadmins zählen nicht: der Betreiber sitzt selbst im Admin-Portal und hielte
sonst sein eigenes Update auf. Der manuelle Trigger („Jetzt updaten") fragt gar
nicht nach.

Umgekehrt meldet der Updater, *dass* er zurückhält (``HOLD_FILE``); das zeigt
das Admin-Panel neben „Update verfügbar" an.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone

from app.services import activity

logger = logging.getLogger(__name__)

ANWESENHEIT_FILE = "/update_status/anwesenheit"
HOLD_FILE = "/update_status/zurueckgehalten"
INTERVALL_S = 30
# Solange der Prozess jünger als das Aktivfenster ist, kennt die Registry noch
# nicht alle, die da sind (sie ist flüchtig, siehe activity). Nach einem Deploy
# stünde sonst sofort „niemand da" in der Datei — und der Nightly-Kanal
# deployte den nächsten Build gleich hinterher. In dieser Zeit gilt deshalb
# das Maximum aus Registry und letzter Meldung.
ANLAUF_S = activity.ACTIVE_WINDOW_SECONDS
# Der Updater schreibt seinen Zustand bei jedem Zyklus (UPDATE_INTERVAL,
# Standard 300 s) neu; was älter ist, stammt von einem Updater, der nicht mehr
# zurückhält oder nicht mehr läuft.
HOLD_FRISCH_S = 900

_gestartet = time.monotonic()


class FahrerLinks:
    """Welche Geräte gerade über einen Fahrer-Link verbunden sind, je Konvoi.

    Gezählt wird je Gerätekennung: jede offene Verbindung und noch
    ``nachlauf_s`` nach der letzten — ein Abriss im Funkloch ist der Normalfall
    (wie bei der Belegung) und kein Feierabend. Mit zählt nur, wessen Konvoi
    gerade läuft (``ortungsgeraet.LAUFEND``, wie beim Tracker): Ein Fahrer-Link,
    der in einem geplanten oder abgeschlossenen Konvoi offen liegt, soll das
    Update nicht bis zur Höchstfrist aufhalten. Den Status kennt das Register
    nicht; :func:`anzahl` bekommt die laufenden Konvois von außen, damit ein
    Statuswechsel während der Verbindung beim nächsten Schreiben gilt.

    Im Speicher wie ``tracking_manager``; nach einem Neustart bauen die Geräte
    die Verbindung von selbst wieder auf, und bis dahin hält der Anlauf
    (``ANLAUF_S``) die zuletzt gemeldete Zahl.
    """

    def __init__(self, uhr=time.monotonic, nachlauf_s: float = activity.ACTIVE_WINDOW_SECONDS):
        self._uhr = uhr
        self._nachlauf_s = nachlauf_s
        self._offen: dict[tuple[str, str], int] = {}
        self._zuletzt: dict[tuple[str, str], float] = {}

    def verbunden(self, kennung: str, convoy_id: str) -> None:
        schluessel = (kennung, convoy_id)
        self._offen[schluessel] = self._offen.get(schluessel, 0) + 1
        self._zuletzt[schluessel] = self._uhr()

    def aktiv(self, kennung: str, convoy_id: str) -> None:
        self._zuletzt[(kennung, convoy_id)] = self._uhr()

    def getrennt(self, kennung: str, convoy_id: str) -> None:
        schluessel = (kennung, convoy_id)
        rest = self._offen.get(schluessel, 0) - 1
        if rest > 0:
            self._offen[schluessel] = rest
        else:
            self._offen.pop(schluessel, None)
        self._zuletzt[schluessel] = self._uhr()

    def _aufraeumen(self) -> set[tuple[str, str]]:
        jetzt = self._uhr()
        for schluessel, zeit in list(self._zuletzt.items()):
            if schluessel not in self._offen and jetzt - zeit > self._nachlauf_s:
                del self._zuletzt[schluessel]
        return self._offen.keys() | self._zuletzt.keys()

    def konvois(self) -> set[str]:
        """Die Konvois, an denen gerade ein Fahrer-Link zählen könnte."""
        return {convoy_id for _, convoy_id in self._aufraeumen()}

    def anzahl(self, laufend: set[str]) -> int:
        """Geräte mit einem Fahrer-Link an einem laufenden Konvoi; jedes einmal."""
        return len({kennung for kennung, convoy_id in self._aufraeumen() if convoy_id in laufend})

    def leeren(self) -> None:
        self._offen.clear()
        self._zuletzt.clear()


fahrer_links = FahrerLinks()


def zaehlen(entries: list[activity.UserActivity]) -> tuple[int, int]:
    """(Nutzer, Demo-Nutzer) aus den aktiven Einträgen — ohne Superadmins."""
    counts = activity.count_by_kind(entries)
    return counts[activity.KIND_MEMBER], counts[activity.KIND_DEMO]


def lesen(text: str) -> dict[str, str]:
    """``name=wert``-Zeilen in ein Dict; Unlesbares fällt still weg."""
    werte: dict[str, str] = {}
    for zeile in text.splitlines():
        name, sep, wert = zeile.partition("=")
        if sep:
            werte[name.strip()] = wert.strip()
    return werte


def _zahl(werte: dict[str, str], name: str) -> int | None:
    wert = werte.get(name, "")
    return int(wert) if wert.isdigit() else None


def meldung(
    nutzer: int,
    demo: int,
    jetzt: int,
    *,
    im_anlauf: bool,
    vorher: str | None,
    fahrer: int = 0,
) -> str:
    """Inhalt von ``ANWESENHEIT_FILE``. Im Anlauf nie weniger als zuletzt gemeldet."""
    if im_anlauf and vorher:
        alt = lesen(vorher)
        nutzer = max(nutzer, _zahl(alt, "nutzer") or 0)
        demo = max(demo, _zahl(alt, "demo") or 0)
        fahrer = max(fahrer, _zahl(alt, "fahrer") or 0)
    return f"stand={jetzt}\nnutzer={nutzer}\ndemo={demo}\nfahrer={fahrer}\n"


async def laufende_konvois(convoy_ids: set[str]) -> set[str]:
    """Welche der Konvois gerade laufen (``ortungsgeraet.LAUFEND``)."""
    if not convoy_ids:
        return set()
    from sqlalchemy import select

    from app.database import AsyncSessionLocal
    from app.models.convoy import Convoy
    from app.services.ortungsgeraet import LAUFEND

    ids = []
    for convoy_id in convoy_ids:
        try:
            ids.append(uuid.UUID(convoy_id))
        except ValueError:
            continue
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(Convoy.id).where(Convoy.id.in_(ids), Convoy.status.in_(LAUFEND))
        )
        return {str(r) for r in rows.scalars()}


def schreiben(laufend: set[str] | None = None) -> None:
    """``laufend``: Konvois mit Status aktiv/läuft; ohne Angabe zählt kein Fahrer-Link."""
    nutzer, demo = zaehlen(activity.active_users())
    vorher = None
    im_anlauf = time.monotonic() - _gestartet < ANLAUF_S
    if im_anlauf:
        try:
            with open(ANWESENHEIT_FILE) as f:
                vorher = f.read()
        except OSError:
            pass
    inhalt = meldung(
        nutzer,
        demo,
        int(time.time()),
        im_anlauf=im_anlauf,
        vorher=vorher,
        fahrer=fahrer_links.anzahl(laufend or set()),
    )
    try:
        with open(ANWESENHEIT_FILE, "w") as f:
            f.write(inhalt)
    except OSError as exc:
        # Ohne Volume (Entwicklung, Tests) gibt es keinen Updater, den es kümmert.
        logger.debug("Kann %s nicht schreiben: %s", ANWESENHEIT_FILE, exc)


async def anwesenheit_loop() -> None:
    while True:
        try:
            # Scheitert die Abfrage, wird in dieser Runde nicht geschrieben: Die
            # Meldung veraltet dann, und der Updater installiert — dieselbe
            # Richtung wie bei einem hängenden Backend.
            schreiben(await laufende_konvois(fahrer_links.konvois()))
        except Exception:  # pragma: no cover — die Schleife darf nicht sterben
            logger.exception("Anwesenheit für den Updater nicht geschrieben")
        await asyncio.sleep(INTERVALL_S)


def zurueckgehalten_aus(text: str, jetzt: int) -> dict | None:
    """Zustand des Updaters fürs Admin-Panel, oder None, wenn er nicht (mehr) hält."""
    werte = lesen(text)
    seit = _zahl(werte, "seit")
    zuletzt = _zahl(werte, "zuletzt")
    if seit is None or zuletzt is None or jetzt - zuletzt > HOLD_FRISCH_S:
        return None
    return {
        "since": datetime.fromtimestamp(seit, tz=timezone.utc).isoformat(),
        "users": _zahl(werte, "nutzer") or 0,
        "demo_users": _zahl(werte, "demo") or 0,
        "drivers": _zahl(werte, "fahrer") or 0,
    }


def zurueckgehalten() -> dict | None:
    try:
        with open(HOLD_FILE) as f:
            text = f.read()
    except OSError:
        return None
    return zurueckgehalten_aus(text, int(time.time()))
