"""Wer arbeitet gerade im Portal — für den Updater.

Der Updater hält ein *automatisches* Update zurück, solange Nutzer oder
Demo-Nutzer angemeldet sind (``docker/updater/anwesenheit.sh``). Er hat keine
Datenbank und keinen Zugang zur Aktivitäts-Registry dieses Prozesses; das
Backend schreibt ihm die Zahlen deshalb alle ``INTERVALL_S`` Sekunden in das
geteilte Volume, wie Kanal und Modus (``update_check``).

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
    nutzer: int, demo: int, jetzt: int, *, im_anlauf: bool, vorher: str | None
) -> str:
    """Inhalt von ``ANWESENHEIT_FILE``. Im Anlauf nie weniger als zuletzt gemeldet."""
    if im_anlauf and vorher:
        alt = lesen(vorher)
        nutzer = max(nutzer, _zahl(alt, "nutzer") or 0)
        demo = max(demo, _zahl(alt, "demo") or 0)
    return f"stand={jetzt}\nnutzer={nutzer}\ndemo={demo}\n"


def schreiben() -> None:
    nutzer, demo = zaehlen(activity.active_users())
    vorher = None
    im_anlauf = time.monotonic() - _gestartet < ANLAUF_S
    if im_anlauf:
        try:
            with open(ANWESENHEIT_FILE) as f:
                vorher = f.read()
        except OSError:
            pass
    inhalt = meldung(nutzer, demo, int(time.time()), im_anlauf=im_anlauf, vorher=vorher)
    try:
        with open(ANWESENHEIT_FILE, "w") as f:
            f.write(inhalt)
    except OSError as exc:
        # Ohne Volume (Entwicklung, Tests) gibt es keinen Updater, den es kümmert.
        logger.debug("Kann %s nicht schreiben: %s", ANWESENHEIT_FILE, exc)


async def anwesenheit_loop() -> None:
    while True:
        try:
            schreiben()
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
    }


def zurueckgehalten() -> dict | None:
    try:
        with open(HOLD_FILE) as f:
            text = f.read()
    except OSError:
        return None
    return zurueckgehalten_aus(text, int(time.time()))
