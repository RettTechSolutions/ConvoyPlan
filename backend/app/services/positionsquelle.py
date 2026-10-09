"""Positionsquelle: sendet ein Tracker, schweigt das Telefon — bei der Position.

Die Belegung (``services/belegung.py``) sagt, welches **Gerät der Besatzung**
ein Fahrzeug hält: Status, Stärke, Betriebsstoff, Quittung. Ein fester Tracker
(``services/ortungsgeraet.py``) gehört nicht in diese Reihe — er meldet nur,
wo das Fahrzeug ist, und soll der Besatzung ihr Telefon nicht wegnehmen. Also
wird die Belegung aufgeteilt, nicht erweitert (E5 im Plan des Tracker-Repos):

- **Meldungen** gehören weiter dem Gerät, das das Fahrzeug belegt hat.
- **Die Position** gehört dem Tracker, solange er sendet. Positionsframes eines
  Telefons für dasselbe Fahrzeug werden verworfen, und nur der Absender erfährt
  es (``position_abgelehnt``, Grund ``tracker``), damit seine App sagen kann
  „Position kommt vom Fahrzeugtracker" statt still nichts zu tun.

Zwei Entscheidungen, die man kennen muss:

- **„Solange er sendet" heißt: ein Bündel in den letzten fünf Minuten.** Ein
  Tracker, der ausfällt, darf das Fahrzeug nicht für immer stumm machen; ein
  Rückfall bei jedem einzelnen Frame brächte dagegen das Springen zurück, das die
  Belegung abgestellt hat. Fünf Minuten sind dieselbe Frist wie dort — länger als
  jedes Funkloch, das das Gerät nicht selbst puffert, und kurz genug, dass eine
  Besatzung nach einem Ausfall nicht lange ohne Punkt auf der Karte steht.
- **Die Führung kann übersteuern** (``tracker_uebersteuert_at`` am
  ``ConvoyVehicle``, Migration ``0058``): dann gilt das Telefon, und was der
  Tracker schickt, wird verworfen. In der Datenbank und nicht im Speicher, weil
  ein Neustart (Nightly, mehrmals täglich) eine Entscheidung der Führung mitten
  im Marsch nicht stillschweigend zurücknehmen darf.

Wer sendet, steht im Speicher (:class:`Positionsquellen`), wie die Belegung und
die Verbindungen in ``tracking_manager``: nach einem Neustart ist der Tracker mit
seinem nächsten Bündel (alle 30 s) wieder da. Die Entscheidung selbst
(:func:`entscheiden`) kommt ohne Uhr und Netz aus und wird von
``tests/test_positionsquelle.py`` geprüft; die drei Telefonpfade ziehen sie über
:func:`telefon_erlaubt`, der Tracker meldet sich über :func:`tracker_sendet`.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime
from typing import Literal

from fastapi import WebSocket

logger = logging.getLogger(__name__)

#: So lange nach seinem letzten Bündel hat der Tracker Vorrang vor dem Telefon.
VORRANG_S = 300.0

Quelle = Literal["tracker", "telefon"]
Entscheidung = Literal["annehmen", "tracker-hat-vorrang", "uebersteuert"]


def entscheiden(quelle: Quelle, tracker_sendet: bool, uebersteuert: bool) -> Entscheidung:
    """Ob eine Position dieser Quelle in den Konvoi darf.

    Übersteuert gewinnt immer das Telefon; sonst der Tracker, solange er sendet.
    """
    if uebersteuert:
        return "annehmen" if quelle == "telefon" else "uebersteuert"
    if quelle == "telefon" and tracker_sendet:
        return "tracker-hat-vorrang"
    return "annehmen"


class Positionsquellen:
    """Welche Tracker gerade senden. Je Konvoi und Fahrzeug, im Speicher, mit Ablauf."""

    def __init__(self, uhr: Callable[[], float] = time.monotonic, vorrang_s: float = VORRANG_S):
        self._uhr = uhr
        self._vorrang_s = vorrang_s
        self._zuletzt: dict[tuple[str, str], float] = {}

    def tracker_gesehen(self, convoy_id: str, vehicle_id: str) -> None:
        self._zuletzt[(convoy_id, vehicle_id)] = self._uhr()

    def tracker_sendet(self, convoy_id: str, vehicle_id: str) -> bool:
        zuletzt = self._zuletzt.get((convoy_id, vehicle_id))
        if zuletzt is None:
            return False
        if self._uhr() - zuletzt > self._vorrang_s:
            del self._zuletzt[(convoy_id, vehicle_id)]
            return False
        return True

    def vergessen(self, convoy_id: str, vehicle_id: str) -> None:
        """Nach „GPS-Freigabe zurücksetzen": der Tracker fängt von vorn an."""
        self._zuletzt.pop((convoy_id, vehicle_id), None)

    def leeren(self) -> None:
        self._zuletzt.clear()


positionsquellen = Positionsquellen()


def tracker_sendet(convoy_id: str, vehicle_id: str, uebersteuert_at: datetime | None) -> bool:
    """Für den Tracker: darf sein Bündel in diesen Konvoi? Merkt ihn sich dabei."""
    if entscheiden("tracker", True, uebersteuert_at is not None) != "annehmen":
        return False
    positionsquellen.tracker_gesehen(convoy_id, vehicle_id)
    return True


async def telefon_erlaubt(
    convoy_id: str,
    vehicle_id: str,
    uebersteuert_at: datetime | None,
    ws: WebSocket | None,
    mit_kennung: bool,
) -> bool:
    """Für Fahrer-Link, REST und WebSocket: darf das Telefon diese Position schreiben?

    Wird sie verworfen, erfährt es nur der Absender — und nur, wenn er eine
    Gerätekennung hat: Der Store der angemeldeten Ansicht älterer Fassung las
    jede unbekannte Nachricht als Position, wie bei der Belegung.
    """
    ergebnis = entscheiden(
        "telefon", positionsquellen.tracker_sendet(convoy_id, vehicle_id), uebersteuert_at is not None
    )
    if ergebnis == "annehmen":
        return True
    if ws is not None and mit_kennung:
        try:
            await ws.send_json({"type": "position_abgelehnt", "vehicle_id": vehicle_id, "grund": "tracker"})
        except Exception:
            logger.debug("position_abgelehnt nicht zustellbar (convoy_id=%s)", convoy_id, exc_info=True)
    return False
