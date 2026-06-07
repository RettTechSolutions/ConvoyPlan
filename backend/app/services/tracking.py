import time
from collections import defaultdict

from fastapi import WebSocket


class TrackingManager:
    """In-process WebSocket connection manager for live vehicle tracking."""

    # After an admin clears a position, ignore late position updates for the same
    # vehicle for this many seconds. Covers the driver's in-flight GPS tick that is
    # sent before its app receives the position_cleared event and stops.
    _CLEAR_SUPPRESS_S = 8.0

    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)
        self._cleared: dict[tuple[str, str], float] = {}

    async def connect(self, convoy_id: str, ws: WebSocket):
        await ws.accept()
        self._connections[convoy_id].append(ws)

    def disconnect(self, convoy_id: str, ws: WebSocket):
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
                pass

    async def broadcast(self, convoy_id: str, data: dict):
        dead: list[WebSocket] = []
        for ws in list(self._connections.get(convoy_id, [])):
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(convoy_id, ws)


tracking_manager = TrackingManager()
