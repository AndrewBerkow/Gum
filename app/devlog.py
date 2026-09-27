"""In-process dev-log pub/sub bus: a bounded ring buffer plus live SSE subscribers.

Lives on the app instance (see `app.main.create_app`), not as a module global, so tests and
concurrent app instances stay isolated. The current turn is tracked with a `contextvars.ContextVar`
so any code running inside a turn (the httpx2 hooks in `app.providers`, `jev_gate` in `app.jev`,
the SSE loop in `app.sse`) can call `emit()` without the bus being threaded through every call.
"""

import asyncio
import contextvars
import itertools
import logging
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_HISTORY_SIZE = 200
DEFAULT_QUEUE_SIZE = 64

Event = tuple[str, dict[str, Any]]


class DevLogBus:
    """Publish/subscribe with a bounded history ring buffer and bounded, drop-oldest queues."""

    def __init__(self, history_size: int = DEFAULT_HISTORY_SIZE, queue_size: int = DEFAULT_QUEUE_SIZE) -> None:
        self._history: deque[Event] = deque(maxlen=history_size)
        self._subscribers: set[asyncio.Queue[Event]] = set()
        self._queue_size = queue_size

    def publish(self, name: str, data: dict[str, Any]) -> None:
        """Fire-and-forget: never blocks, never raises."""
        try:
            item: Event = (name, data)
            self._history.append(item)
            for queue in list(self._subscribers):
                self._deliver(queue, item)
        except Exception:
            log.exception("devlog publish failed for %s", name)

    def _deliver(self, queue: "asyncio.Queue[Event]", item: Event) -> None:
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                queue.put_nowait(item)
            except asyncio.QueueFull:
                pass

    def subscribe(self) -> tuple[list[Event], "asyncio.Queue[Event]"]:
        """Register a subscriber; returns buffered history plus its live queue."""
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers.add(queue)
        return list(self._history), queue

    def unsubscribe(self, queue: "asyncio.Queue[Event]") -> None:
        self._subscribers.discard(queue)

    async def stream(self) -> AsyncIterator[Event]:
        """Buffered history first, then live events, until the consumer stops iterating."""
        history, queue = self.subscribe()
        try:
            for item in history:
                yield item
            while True:
                yield await queue.get()
        finally:
            self.unsubscribe(queue)


@dataclass
class _TurnRecorder:
    bus: DevLogBus
    turn_id: str
    started: float
    _seq: "itertools.count[int]" = field(default_factory=itertools.count)

    def emit(self, name: str, **fields: Any) -> None:
        try:
            data = {
                "turn_id": self.turn_id,
                "seq": next(self._seq),
                "ts": datetime.now(UTC).isoformat(),
                "t_ms": (perf_counter() - self.started) * 1000,
                **fields,
            }
            self.bus.publish(name, data)
        except Exception:
            log.exception("devlog emit failed for %s", name)


_CURRENT_TURN: contextvars.ContextVar["_TurnRecorder | None"] = contextvars.ContextVar(
    "gum_devlog_current_turn", default=None
)


def start_turn(bus: DevLogBus, turn_id: str) -> contextvars.Token:
    """Mark the start of a turn; `emit()` publishes to `bus` until `end_turn(token)`."""
    return _CURRENT_TURN.set(_TurnRecorder(bus=bus, turn_id=turn_id, started=perf_counter()))


def end_turn(token: contextvars.Token) -> None:
    _CURRENT_TURN.reset(token)


def emit(name: str, **fields: Any) -> None:
    """Publish a dev-log event for the active turn; a safe no-op with no active turn."""
    recorder = _CURRENT_TURN.get()
    if recorder is not None:
        recorder.emit(name, **fields)


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    """Copy `headers` with `Authorization` (any case) replaced by `Bearer ***`."""
    return {k: ("Bearer ***" if k.lower() == "authorization" else v) for k, v in headers.items()}
