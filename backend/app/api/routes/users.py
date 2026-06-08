import asyncio
import json
import uuid

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
import jwt as _jwt
from jwt.exceptions import InvalidTokenError

from app.config import settings

router = APIRouter(prefix="/users", tags=["users"])

# Identity (user id) -> set of that user's active SSE connection queues.
# A user counts as "online" while they hold at least one open connection, so
# extra tabs or page reloads collapse onto the same identity instead of
# inflating the count.
_connections: dict[str, set[asyncio.Queue]] = {}
# Every connection's queue, used purely to fan out count updates.
_listeners: set[asyncio.Queue] = set()


def _identity(token: str | None) -> str:
    """Resolve a stable identity for a connection.

    Authenticated users are keyed by their user id, so multiple tabs and page
    reloads collapse to a single online user. Connections without a valid token
    fall back to a random per-connection id."""
    if token:
        try:
            payload = _jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
            sub = payload.get("sub")
            if sub:
                return f"user:{sub}"
        except InvalidTokenError:
            pass
    return f"anon:{uuid.uuid4()}"


def _online_count() -> int:
    return len(_connections)


async def _broadcast() -> None:
    msg = f"data: {json.dumps({'count': _online_count()})}\n\n"
    for q in list(_listeners):
        await q.put(msg)


@router.get("/online")
async def online_users(token: str | None = Query(default=None)) -> StreamingResponse:
    identity = _identity(token)
    queue: asyncio.Queue = asyncio.Queue()
    _listeners.add(queue)
    conns = _connections.setdefault(identity, set())
    is_newly_online = not conns
    conns.add(queue)
    # Only a user coming online (not a reconnecting one) changes the count.
    if is_newly_online:
        await _broadcast()

    async def stream():
        try:
            yield f"data: {json.dumps({'count': _online_count()})}\n\n"
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield msg
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except (GeneratorExit, asyncio.CancelledError):
            pass
        finally:
            _listeners.discard(queue)
            remaining = _connections.get(identity)
            if remaining is not None:
                remaining.discard(queue)
                # User is fully offline only once their last connection closes.
                if not remaining:
                    del _connections[identity]
                    await _broadcast()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
