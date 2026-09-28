"""Unit tests for the `Stream` SSE reader helper in tests/integration/test_feat7_console_clear.py,
driven against an in-memory httpx transport (no sockets)."""

import asyncio

import httpx

from tests.unit._load_test_module import load

MODULE = load(
    "tests/integration/test_feat7_console_clear.py", "feat7_console_clear_under_test"
)


def _frame(name, data):
    return f'event: {name}\ndata: {{"n": {data}}}\n\n'.encode()


class Feed:
    """Byte chunks released on demand, so a test controls when the 'server' emits."""

    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()

    def send(self, name, n):
        self.queue.put_nowait(_frame(name, n))

    def end(self):
        self.queue.put_nowait(None)

    async def __aiter__(self):
        while (chunk := await self.queue.get()) is not None:
            yield chunk


async def _open(feed):
    def handler(request):
        return httpx.Response(200, content=feed.__aiter__())

    stream = MODULE.Stream("http://test")
    await stream._client.aclose()
    stream._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), timeout=None
    )
    await stream.open()
    return stream


async def test_second_read_until_continues_the_same_stream():
    feed = Feed()
    feed.send("turn.start", 1)
    feed.send("turn.end", 2)
    stream = await _open(feed)
    try:
        assert await stream.read_until(lambda ev: len(ev) >= 1, timeout=2)
        assert await stream.read_until(lambda ev: len(ev) >= 2, timeout=2)
        assert [n for n, _ in stream.events] == ["turn.start", "turn.end"]
    finally:
        await stream.close()


async def test_read_until_returns_false_on_timeout():
    feed = Feed()
    stream = await _open(feed)
    try:
        assert await stream.read_until(lambda ev: len(ev) >= 1, timeout=0.2) is False
    finally:
        await stream.close()


async def test_read_until_timeout_does_not_lose_the_stream():
    feed = Feed()
    stream = await _open(feed)
    try:
        assert await stream.read_until(lambda ev: len(ev) >= 1, timeout=0.2) is False
        feed.send("turn.start", 1)
        assert await stream.read_until(lambda ev: len(ev) >= 1, timeout=2) is True
        assert [n for n, _ in stream.events] == ["turn.start"]
    finally:
        await stream.close()
