import json

import httpx
import pytest

from app.config import ConfigError, Settings
from app.main import create_app
from tests.integration.test_t3_serving_stack import log_lines, parse_sse


def settings(tmp_path, **kw):
    kw.setdefault("jev_backend", "stub")
    kw.setdefault("chat_provider", "fake")
    return Settings(_env_file=None, decision_log_path=str(tmp_path / "d.jsonl"), **kw)


def client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


@pytest.mark.parametrize(
    "body",
    [
        {"thread_id": "t", "message": ""},
        {"thread_id": "t", "message": "x" * 4001},
        {"message": "hi"},
        {"thread_id": "t", "message": "hi", "tier": "gpt-4"},
    ],
)
async def test_chat_rejects_invalid_body_with_422(tmp_path, body):
    async with client(create_app(settings(tmp_path))) as c:
        assert (await c.post("/api/chat", json=body)).status_code == 422


async def test_healthz_reports_config(tmp_path):
    s = settings(tmp_path)
    async with client(create_app(s)) as c:
        h = (await c.get("/healthz")).json()
    assert h == {
        "jev_backend": "stub",
        "chat_provider": "fake",
        "tiers": {"flash": s.chat_model_flash, "lite": s.chat_model_lite},
        "route_lite_threshold": s.route_lite_threshold,
    }


async def test_chat_streams_events_logs_turn_and_updates_stats(tmp_path):
    s = settings(tmp_path)
    async with client(create_app(s)) as c:
        r = await c.post("/api/chat", json={"thread_id": "a", "message": "hi there"})
        assert r.headers["content-type"].startswith("text/event-stream")
        names = [n for n, _ in parse_sse(r.text)]
        assert names[0] == "guardrail" and names[-1] == "done"
        assert (await c.get("/api/stats")).json()["turns"] == 1
    (rec,) = log_lines(s.decision_log_path)
    assert rec["thread_id"] == "a" and rec["error"] is None
    assert "hi there" not in json.dumps(rec)


async def test_static_root_is_served(tmp_path):
    async with client(create_app(settings(tmp_path))) as c:
        assert (await c.get("/")).status_code == 200


def test_live_mode_with_placeholder_keys_raises_config_error(tmp_path):
    s = settings(tmp_path, jev_backend="live", typesafe_api_key="ts_live_xxxx")
    with pytest.raises(ConfigError):
        create_app(s)


# ---------------------------------------------------------------- _LazyASGIApp (t1)


def test_lazy_asgi_app_does_not_build_until_first_call():
    from app.main import _LazyASGIApp

    build_calls = []
    _LazyASGIApp(lambda: build_calls.append(1))
    assert build_calls == []


async def test_lazy_asgi_app_builds_once_forwards_calls_and_does_not_cache_a_failed_build():
    from app.main import _LazyASGIApp

    build_calls = []
    forwarded = []

    class FakeApp:
        async def __call__(self, scope, receive, send):
            forwarded.append((scope, receive, send))

    def builder():
        build_calls.append(1)
        return FakeApp()

    lazy = _LazyASGIApp(builder)
    r1, s1 = object(), object()
    r2, s2 = object(), object()
    await lazy({"type": "http", "n": 1}, r1, s1)
    await lazy({"type": "http", "n": 2}, r2, s2)

    assert build_calls == [1], "should build exactly once across repeated calls"
    assert forwarded == [({"type": "http", "n": 1}, r1, s1), ({"type": "http", "n": 2}, r2, s2)]

    class FailingThenOk:
        def __init__(self):
            self.attempts = 0

        def __call__(self):
            self.attempts += 1
            if self.attempts == 1:
                raise ConfigError("boom: TYPESAFE_API_KEY is missing")
            return FakeApp()

    flaky = FailingThenOk()
    lazy2 = _LazyASGIApp(flaky)
    with pytest.raises(ConfigError, match="TYPESAFE_API_KEY"):
        await lazy2({"type": "http"}, r1, s1)
    assert flaky.attempts == 1, "a failed build must not be cached"
    await lazy2({"type": "http"}, r1, s1)  # retries the builder and succeeds this time
    assert flaky.attempts == 2


def test_module_level_app_is_a_lazy_wrapper_around_create_app_and_import_never_builds_it(monkeypatch):
    import importlib
    import sys

    from app import providers

    classifier_calls = []
    monkeypatch.setattr(providers, "build_classifier", lambda *a, **k: classifier_calls.append(1))
    for name in list(sys.modules):
        if name == "app.main":
            del sys.modules[name]

    mod = importlib.import_module("app.main")

    assert isinstance(mod.app, mod._LazyASGIApp)
    assert mod.app._builder is mod.create_app
    assert classifier_calls == []
