import asyncio
import logging
import time
from collections import defaultdict
from typing import Callable

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class TrackingManager:
    """In-process WebSocket connection manager for live vehicle tracking."""

    # After an admin clears a position, ignore late position updates for the same
    # vehicle for this many seconds. Covers the driver's in-flight GPS tick that is
    # sent before its app receives the position_cleared event and stops.
    _CLEAR_SUPPRESS_S = 8.0

    # So lange erkennt der Server eine wiederholte Meldung wieder. Ein Fahrer im
    # Funkloch schickt nach, sobald der Kanal steht — das ist eine Sache von
    # Minuten, nicht von Stunden.
    _ACK_TTL_S = 600.0
    # Obergrenze, damit ein Client mit immer neuen Kennungen den Speicher nicht
    # füllen kann. Bei Überlauf gehen die ältesten zuerst.
    _ACK_MAX = 5000

    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)
        self._cleared: dict[tuple[str, str], float] = {}
        # Zusätzliche Interessenten an jedem Broadcast, die keine WebSocket
        # sind. Eingeführt für die MCP-Subscriptions: die brauchen dieselben
        # Ereignisse, aber dieses Modul soll nichts von MCP wissen — es läuft
        # auch auf Instanzen, auf denen MCP abgeschaltet ist.
        self._listeners: list[Callable[[str, dict], None]] = []
        # Verbindungen, die sich mit einer Gerätekennung gemeldet haben. Nur sie
        # bekommen Belegungsnachrichten (``broadcast_belegung``): ältere Clients
        # kennen den Typ nicht, und die angemeldete Weboberfläche las jede
        # unbekannte Nachricht als Position.
        self._mit_kennung: set[WebSocket] = set()
        # Quittungen nach (convoy_id, client_id). Ein Future statt des Werts,
        # damit ein Duplikat, das eintrifft, während das Original noch in der
        # Datenbank steckt, auf dessen Ergebnis wartet, statt es zu wiederholen.
        self._acks: dict[tuple[str, str], tuple[float, asyncio.Future]] = {}

    def add_broadcast_listener(self, listener: "Callable[[str, dict], None]") -> None:
        """Einen Beobachter für jeden Broadcast anmelden.

        Der Beobachter läuft synchron auf der Event-Loop und darf deshalb
        weder blockieren noch werfen — ein Fehler dort würde sonst die
        Live-Verfolgung mitreißen, und die ist der Teil, bei dem ein Ausfall
        im Einsatz unmittelbar weh tut.

        Derselbe Beobachter lässt sich nicht zweimal anmelden: die Montage
        des MCP-Servers läuft in Tests mehrfach gegen denselben Prozess, und
        doppelte Zustellung wäre dort ein Fehler, der erst später auffiele."""
        if listener not in self._listeners:
            self._listeners.append(listener)

    def reset_listeners(self) -> None:
        self._listeners.clear()

    def claim_ack(self, key: tuple[str, str]) -> "asyncio.Future | None":
        """Reserviert eine Kennung — oder liefert die Quittung, die schon dafür läuft.

        ``None`` heißt: neu, der Aufrufer verarbeitet den Frame und meldet das
        Ergebnis über ``settle_ack`` (oder gibt die Kennung mit ``forget_ack``
        wieder frei).
        """
        now = time.monotonic()
        entry = self._acks.get(key)
        if entry is not None and now - entry[0] <= self._ACK_TTL_S:
            return entry[1]
        self._prune_acks(now)
        self._acks[key] = (now, asyncio.get_running_loop().create_future())
        return None

    def settle_ack(self, key: tuple[str, str], ack: dict) -> None:
        entry = self._acks.get(key)
        if entry is not None and not entry[1].done():
            entry[1].set_result(ack)

    def forget_ack(self, key: tuple[str, str], ack: dict) -> None:
        """Gibt eine Kennung frei, ohne ihr Ergebnis zu merken.

        Wer schon auf sie wartet, bekommt ``ack`` — dieselbe Antwort wie das
        Original — und darf danach erneut versuchen.
        """
        entry = self._acks.pop(key, None)
        if entry is not None and not entry[1].done():
            entry[1].set_result(ack)

    def _prune_acks(self, now: float) -> None:
        expired = [k for k, (at, _) in self._acks.items() if now - at > self._ACK_TTL_S]
        for k in expired:
            del self._acks[k]
        # dict hält die Einfügereihenfolge — vorne stehen die ältesten.
        while len(self._acks) >= self._ACK_MAX:
            del self._acks[next(iter(self._acks))]

    async def connect(self, convoy_id: str, ws: WebSocket, mit_kennung: bool = False):
        await ws.accept()
        self._connections[convoy_id].append(ws)
        if mit_kennung:
            self._mit_kennung.add(ws)

    def disconnect(self, convoy_id: str, ws: WebSocket):
        self._mit_kennung.discard(ws)
        try:
            self._connections[convoy_id].remove(ws)
        except ValueError:
            pass

    def mark_cleared(self, convoy_id: str, vehicle_id: str) -> None:
        """Remember that a vehicle's GPS sharing was just reset by an admin."""
        self._cleared[(convoy_id, vehicle_id)] = time.monotonic()

    def is_recently_cleared(self, convoy_id: str, vehicle_id: str) -> bool:
        ts = self._cleared.get((convoy_id, vehicle_id))
        if ts is None:
            return False
        if time.monotonic() - ts > self._CLEAR_SUPPRESS_S:
            self._cleared.pop((convoy_id, vehicle_id), None)
            return False
        return True

    async def revoke_connections(self, convoy_id: str) -> None:
        """Close all active WebSocket connections for a convoy when its share link is revoked."""
        for ws in list(self._connections.pop(convoy_id, [])):
            try:
                await ws.close(code=4403)
            except Exception:
                logger.debug(
                    "Ignoring WebSocket close failure during revoke_connections for convoy_id=%s",
                    convoy_id,
                    exc_info=True,
                )

    async def broadcast(self, convoy_id: str, data: dict):
        # Zuerst die Beobachter, jeder für sich abgeschirmt: ein MCP-Abonnent,
        # dessen Zustellung scheitert, darf die WebSocket-Verteilung an die
        # Fahrzeuge nicht aufhalten.
        for listener in self._listeners:
            try:
                listener(convoy_id, data)
            except Exception:
                logger.warning(
                    "Broadcast-Beobachter hat geworfen (convoy_id=%s) — ignoriert",
                    convoy_id, exc_info=True,
                )

        dead: list[WebSocket] = []
        for ws in list(self._connections.get(convoy_id, [])):
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(convoy_id, ws)

    async def broadcast_belegung(self, convoy_id: str, data: dict):
        """Wie ``broadcast``, aber nur an Verbindungen mit Gerätekennung.

        Ohne die Beobachter: eine Belegung ist Bedienzustand der Fahrzeugwahl,
        kein Ereignis im Verband."""
        dead: list[WebSocket] = []
        for ws in list(self._connections.get(convoy_id, [])):
            if ws not in self._mit_kennung:
                continue
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(convoy_id, ws)


tracking_manager = TrackingManager()
