from collections import defaultdict

from fastapi import WebSocket


class TrackingManager:
    """In-process WebSocket connection manager for live vehicle tracking."""

    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)

    async def connect(self, convoy_id: str, ws: WebSocket):
        await ws.accept()
        self._connections[convoy_id].append(ws)

    def disconnect(self, convoy_id: str, ws: WebSocket):
        try:
            self._connections[convoy_id].remove(ws)
        except ValueError:
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
