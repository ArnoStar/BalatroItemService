"""The casino's live streams, in this process.

Use cases publish from the server's worker threads once their transaction is
done; each stream reads on the event loop it was opened on
(``call_soon_threadsafe`` hands events over). A stream that falls
``queue_size`` events behind is closed: its client opens a new one, whose first
event has everything again. One process only: a second one would need a shared
feed (PostgreSQL LISTEN/NOTIFY, for example)."""

from __future__ import annotations

import asyncio
import logging
import threading

from balatro_items.application.dto import CasinoEvent

log = logging.getLogger(__name__)


class FeedStream:
    def __init__(self, feed: LocalFeed, loop: asyncio.AbstractEventLoop, size: int) -> None:
        self.feed = feed
        self.loop = loop
        self.queue: asyncio.Queue[CasinoEvent | None] = asyncio.Queue(maxsize=size)
        self.closed = False

    def deliver(self, event: CasinoEvent) -> None:
        """(On the stream's loop.)"""
        if self.closed:
            return
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            log.warning("a live stream of the casino fell behind: it is closed (its client opens another)")
            self.close()
            while not self.queue.empty():
                self.queue.get_nowait()
            self.queue.put_nowait(None)  # (wakes the reader up)

    async def next(self, timeout: float) -> CasinoEvent | None:
        if self.closed and self.queue.empty():
            raise EOFError
        try:
            event = await asyncio.wait_for(self.queue.get(), timeout)
        except TimeoutError:
            return None
        if event is None:
            raise EOFError
        return event

    def close(self) -> None:
        self.closed = True
        self.feed.remove(self)


class LocalFeed:
    def __init__(self, queue_size: int = 256) -> None:
        self.queue_size = queue_size
        self._lock = threading.Lock()
        self._streams: set[FeedStream] = set()

    def subscribe(self) -> FeedStream:
        stream = FeedStream(self, asyncio.get_running_loop(), self.queue_size)
        with self._lock:
            self._streams.add(stream)
        return stream

    def remove(self, stream: FeedStream) -> None:
        with self._lock:
            self._streams.discard(stream)

    def publish(self, event: CasinoEvent) -> None:
        with self._lock:
            streams = list(self._streams)
        for s in streams:
            try:
                s.loop.call_soon_threadsafe(s.deliver, event)
            except RuntimeError:  # (its loop has stopped: the server is shutting down)
                pass

    @property
    def streams(self) -> int:
        with self._lock:
            return len(self._streams)
