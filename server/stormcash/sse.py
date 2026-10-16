"""Server-sent events (spec §12.3): an in-process broadcaster and GET /v1/stream.

`publish` is safe to call from sync route handlers (FastAPI's threadpool) and
background threads; each subscriber gets its own bounded asyncio queue.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from .jsonutil import jsonable

QUEUE_SIZE = 1000


class Broker:
    def __init__(self) -> None:
        self._subscribers: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = set()
        self._lock = threading.Lock()

    def publish(self, event: str, data) -> None:
        message = {"event": event, "data": json.dumps(jsonable(data))}
        with self._lock:
            subscribers = list(self._subscribers)
        for loop, queue in subscribers:
            try:
                loop.call_soon_threadsafe(_offer, queue, message)
            except RuntimeError:  # loop closed
                self._remove(loop, queue)

    def _remove(self, loop, queue) -> None:
        with self._lock:
            self._subscribers.discard((loop, queue))

    async def subscribe(self) -> AsyncIterator[dict]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        with self._lock:
            self._subscribers.add((loop, queue))
        try:
            while True:
                yield await queue.get()
        finally:
            self._remove(loop, queue)


def _offer(queue: asyncio.Queue, message: dict) -> None:
    if not queue.full():  # a stalled dashboard drops events rather than blocking money paths
        queue.put_nowait(message)


router = APIRouter()


@router.get("/v1/stream")
async def stream(request: Request) -> EventSourceResponse:
    broker: Broker = request.app.state.deps.events
    return EventSourceResponse(broker.subscribe(), ping=15)
