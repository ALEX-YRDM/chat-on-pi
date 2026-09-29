"""Small bounded queues prevent slow/disconnected browsers blocking inference."""
import asyncio


class StatusHub:
    def __init__(self):
        self.loop = asyncio.get_running_loop()
        self.queues: set[asyncio.Queue] = set()

    def publish(self, event: dict) -> None:
        if not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self._enqueue, event)

    def _enqueue(self, event: dict) -> None:
        for queue in tuple(self.queues):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)

    def subscribe(self) -> asyncio.Queue:
        queue = asyncio.Queue(maxsize=16)
        self.queues.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self.queues.discard(queue)
