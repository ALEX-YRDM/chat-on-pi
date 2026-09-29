import asyncio
import anyio
from urllib.parse import urlparse
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws/status")
async def status_socket(websocket: WebSocket):
    origin = websocket.headers.get("origin")
    if origin and urlparse(origin).netloc != websocket.headers.get("host"):
        await websocket.close(code=1008)
        return
    rt = websocket.app.state.runtime
    await websocket.accept()
    queue = rt.hub.subscribe()

    async def sender():
        await websocket.send_json(rt.pipeline.snapshot())
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=20)
            except asyncio.TimeoutError:
                event = rt.pipeline.snapshot()
            await websocket.send_json(event)

    async def receiver():
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return

    tasks = [asyncio.create_task(sender()), asyncio.create_task(receiver())]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except (WebSocketDisconnect, RuntimeError, OSError, asyncio.CancelledError):
        pass
    finally:
        rt.hub.unsubscribe(queue)
        for task in tasks:
            task.cancel()
        with anyio.CancelScope(shield=True):
            await asyncio.gather(*tasks, return_exceptions=True)
