import asyncio
import json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/users", tags=["users"])

_connections: set[asyncio.Queue] = set()


async def _broadcast(count: int) -> None:
    msg = f"data: {json.dumps({'count': count})}\n\n"
    for q in list(_connections):
        await q.put(msg)


@router.get("/online")
async def online_users() -> StreamingResponse:
    queue: asyncio.Queue = asyncio.Queue()
    _connections.add(queue)
    await _broadcast(len(_connections))

    async def stream():
        try:
            yield f"data: {json.dumps({'count': len(_connections)})}\n\n"
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield msg
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except (GeneratorExit, asyncio.CancelledError):
            pass
        finally:
            _connections.discard(queue)
            await _broadcast(len(_connections))

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
