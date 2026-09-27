import asyncio

from app.config import Settings
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
