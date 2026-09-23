"""Belegung: welches Gerät für welches Fahrzeug eines Verbands sendet.

Ohne sie konnten zwei Geräte dasselbe Fahrzeug wählen — die App den KdoW, die
Trackingseite im Browser noch einmal den KdoW —, und beide schrieben in dieselbe
Positionszeile. Die Karte sprang zwischen zwei Standorten hin und her, und ein
Status des einen überschrieb den des anderen. Der alte Schutz im Web („ein
Fahrzeug mit Position ist vergeben") war keiner: er stand nur in einer von drei
Oberflächen, und eine Position bleibt in der Datenbank liegen, lange nachdem
niemand mehr sendet.

Die Belegung sitzt deshalb **am Server** und gilt für alle Kanäle zugleich —
Fahrer-Link (App und Web) und angemeldetes Tracking. Ein Gerät weist sich mit
einer selbst erzeugten Kennung aus (Query-Parameter ``client`` am WebSocket),
beansprucht sein Fahrzeug beim **Wählen** (Frame ``belegen``), hält die
Belegung mit jedem Frame für dieses Fahrzeug und gibt sie beim Abwählen frei
(Frame ``freigeben``). Frames eines anderen Geräts für ein belegtes Fahrzeug
werden verworfen, und nur der Absender erfährt davon.

Warum ein Ablauf und kein „solange die Verbindung steht": ein Funkloch trennt
die Verbindung, und das Fahrzeug darf dabei nicht frei werden. Umgekehrt darf
ein abgestürztes Telefon es nicht für immer blockieren. Fünf Minuten ohne jeden
Frame sind länger als jedes Funkloch, das der Keepalive (jede Minute) nicht
überbrückt, und kurz genug, dass eine Besatzung nach einem Gerätetausch nicht
lange wartet. Für den Fall, dass es eilt, gibt die Führung das Fahrzeug mit
„GPS-Freigabe zurücksetzen" sofort frei.

Warum im Speicher und nicht in der Datenbank: Die Belegung lebt so lange wie
die Verbindungen, zu denen sie gehört, und die hält ``tracking_manager`` auch
nur im Speicher. Nach einem Neustart meldet sich jedes sendende Gerät binnen
einer Minute mit seinem Keepalive zurück und hat sein Fahrzeug wieder.

Die Entscheidung steht in :class:`Belegungen`, ohne Netz und ohne Uhr von
außen, und wird von ``tests/test_fahrzeug_belegung.py`` geprüft.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Callable, Literal

from fastapi import WebSocket

from app.services.tracking import tracking_manager

logger = logging.getLogger(__name__)

#: So lange hält eine Belegung ohne jeden Frame ihres Geräts.
ABLAUF_S = 300.0

_KENNUNG = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

Ergebnis = Literal["neu", "erneuert", "fremd"]


def kennung_pruefen(roh: str | None) -> str | None:
    """Die Gerätekennung aus dem Query-Parameter, oder ``None``.

    ``None`` heißt: ein Client von vor der Belegung. Er bekommt eine Kennung je
    Verbindung (:func:`alt_kennung`) und wird **nicht** abgewiesen — eine App aus
    dem Store, die noch nicht aktualisiert ist, soll im Einsatz weiter senden.
    Sichtbar ist er trotzdem: was er sendet, belegt das Fahrzeug für alle
    anderen.
    """
    if roh and _KENNUNG.match(roh):
        return roh
    return None


def alt_kennung() -> str:
    return f"alt-{uuid.uuid4().hex}"


class Belegungen:
    """Wer hält welches Fahrzeug. Je Verband, im Speicher, mit Ablauf."""

    def __init__(self, uhr: Callable[[], float] = time.monotonic, ablauf_s: float = ABLAUF_S):
        self._uhr = uhr
        self._ablauf_s = ablauf_s
        # (convoy_id, vehicle_id) → (Kennung, zuletzt gesehen)
        self._halter: dict[tuple[str, str], tuple[str, float]] = {}

    def beanspruchen(self, convoy_id: str, vehicle_id: str, kennung: str) -> Ergebnis:
        """Beansprucht oder erneuert. ``fremd``: ein anderes Gerät hält das Fahrzeug."""
        jetzt = self._uhr()
        schluessel = (convoy_id, vehicle_id)
        bisher = self._halter.get(schluessel)
        if bisher is not None and bisher[0] != kennung and jetzt - bisher[1] <= self._ablauf_s:
            return "fremd"
        self._halter[schluessel] = (kennung, jetzt)
        if bisher is not None and bisher[0] == kennung:
            return "erneuert"
        return "neu"

    def freigeben(self, convoy_id: str, vehicle_id: str, kennung: str | None) -> bool:
        """Gibt frei. ``kennung=None`` gibt ohne Ansehen des Halters frei (Führung).

        Ein fremdes Gerät kann nichts freigeben, was es nicht hält — sonst reichte
        ein ``freigeben``-Frame, um jemandem sein Fahrzeug wegzunehmen.
        """
        schluessel = (convoy_id, vehicle_id)
        bisher = self._halter.get(schluessel)
        if bisher is None:
            return False
        if kennung is not None and bisher[0] != kennung:
            return False
        del self._halter[schluessel]
        return True

    def ablaufen(self, convoy_id: str) -> list[str]:
        """Räumt abgelaufene Belegungen dieses Verbands ab und nennt ihre Fahrzeuge."""
        grenze = self._uhr() - self._ablauf_s
        weg = [
            s for s, (_, zuletzt) in self._halter.items()
            if s[0] == convoy_id and zuletzt < grenze
        ]
        for s in weg:
            del self._halter[s]
        return [vehicle_id for _, vehicle_id in weg]

    def belegte(self, convoy_id: str, ausser: str | None = None) -> list[str]:
        """Fahrzeuge, die ein Gerät hält — ohne die, die ``ausser`` selbst hält."""
        grenze = self._uhr() - self._ablauf_s
        return sorted(
            vehicle_id
            for (cid, vehicle_id), (kennung, zuletzt) in self._halter.items()
            if cid == convoy_id and zuletzt >= grenze and kennung != ausser
        )

    def gehalten(self, convoy_id: str, kennung: str) -> list[str]:
        """Fahrzeuge, die ``kennung`` selbst hält — für „wer hat quittiert"."""
        grenze = self._uhr() - self._ablauf_s
        return sorted(
            vehicle_id
            for (cid, vehicle_id), (halter, zuletzt) in self._halter.items()
            if cid == convoy_id and zuletzt >= grenze and halter == kennung
        )

    def leeren(self) -> None:
        self._halter.clear()


belegungen = Belegungen()


async def _melden(convoy_id: str, vehicle_id: str, belegt: bool) -> None:
    await tracking_manager.broadcast_belegung(
        convoy_id, {"type": "belegung", "vehicle_id": vehicle_id, "belegt": belegt}
    )


async def _abgelaufene_melden(convoy_id: str) -> None:
    for vehicle_id in belegungen.ablaufen(convoy_id):
        await _melden(convoy_id, vehicle_id, False)


async def pruefen(
    convoy_id: str,
    vehicle_id: str,
    kennung: str,
    ws: WebSocket | None,
    durchsetzen: bool,
) -> bool:
    """Darf dieses Gerät für dieses Fahrzeug senden? Beansprucht dabei.

    ``durchsetzen=False`` für Clients ohne Kennung: ihr Frame geht immer durch,
    belegt aber ein freies Fahrzeug. Wird ein Frame abgewiesen, erfährt es nur
    der Absender (``belegung_abgelehnt``) — alle anderen haben nichts verpasst.
    """
    await _abgelaufene_melden(convoy_id)
    ergebnis = belegungen.beanspruchen(convoy_id, vehicle_id, kennung)
    if ergebnis == "neu":
        await _melden(convoy_id, vehicle_id, True)
        return True
    if ergebnis == "erneuert":
        return True
    if not durchsetzen:
        return True
    if ws is not None:
        try:
            await ws.send_json({"type": "belegung_abgelehnt", "vehicle_id": vehicle_id})
        except Exception:
            # Die Verbindung ist schon weg — verworfen ist der Frame trotzdem,
            # und das Gerät bekommt beim Wiederverbinden den Stand.
            logger.debug("belegung_abgelehnt nicht zustellbar (convoy_id=%s)", convoy_id, exc_info=True)
    return False


async def freigeben(convoy_id: str, vehicle_id: str, kennung: str | None) -> None:
    """Gibt frei und meldet es — nur, wenn wirklich etwas frei wurde."""
    if belegungen.freigeben(convoy_id, vehicle_id, kennung):
        await _melden(convoy_id, vehicle_id, False)


async def stand_senden(convoy_id: str, kennung: str, ws: WebSocket) -> None:
    """Schickt einer neuen Verbindung, was andere Geräte gerade halten."""
    await _abgelaufene_melden(convoy_id)
    try:
        await ws.send_json({
            "type": "belegungen",
            "vehicle_ids": belegungen.belegte(convoy_id, ausser=kennung),
        })
    except Exception:
        # Gleich nach dem Aufbau wieder getrennt — der nächste Aufbau schickt ihn neu.
        logger.debug("Belegungsstand nicht zustellbar (convoy_id=%s)", convoy_id, exc_info=True)
