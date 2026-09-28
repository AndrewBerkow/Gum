import asyncio

from app.config import Settings
from app.devlog import DevLogBus
from app.main import create_app


def settings(tmp_path, **kw):
    kw.setdefault("jev_backend", "stub")
    kw.setdefault("chat_provider", "fake")
    return Settings(_env_file=None, decision_log_path=str(tmp_path / "d.jsonl"), **kw)


async def _raw_asgi_get(app, path, client=("127.0.0.1", 555)):
    """Drive the ASGI app directly for a request that terminates immediately (a rejection),
    matching tests/integration/test_t3_serving_stack.py's raw-scope pattern."""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "client": client,
        "server": ("test", 80),
    }
    delivered = False

    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.disconnect"}

    status = None

    async def send(message):
        nonlocal status
        if message["type"] == "http.response.start":
            status = message["status"]

    await asyncio.wait_for(app(scope, receive, send), timeout=5)
    return status


async def test_get_devlog_returns_404_when_disabled_and_403_for_non_loopback(tmp_path):
    app_disabled = create_app(settings(tmp_path, devlog_enabled=False))
    assert await _raw_asgi_get(app_disabled, "/api/devlog") == 404

    app_enabled = create_app(settings(tmp_path))
    assert await _raw_asgi_get(app_enabled, "/api/devlog", client=("8.8.8.8", 555)) == 403


def _raw_get_with_query(app, query):
    """Like _raw_asgi_get, but for the loopback devlog path with a query string."""

    async def run():
        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
            "scheme": "http", "path": "/api/devlog", "raw_path": b"/api/devlog",
            "query_string": query, "headers": [], "client": ("127.0.0.1", 555), "server": ("test", 80),
        }
        delivered = False

        async def receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": b"", "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message):
            pass

        await asyncio.wait_for(app(scope, receive, send), timeout=5)

    return run()


async def test_devlog_route_passes_replay_flag_from_query_param(tmp_path, monkeypatch):
    calls = []

    class SpyBus(DevLogBus):
        async def stream(self, replay=True):
            calls.append(replay)
            return
            yield  # pragma: no cover - makes this an (immediately finishing) async generator

    # patch create_app's own globals: other tests may reload app.main, so a dotted-path patch can miss it
    monkeypatch.setitem(create_app.__globals__, "DevLogBus", SpyBus)
    app = create_app(settings(tmp_path))
    for query in (b"", b"replay=0", b"replay=1"):
        await _raw_get_with_query(app, query)

    assert calls == [True, False, True]
