import json

import httpx2

from app.devlog import DevLogBus, end_turn, start_turn
from app.providers import _devlog_request_hook, _devlog_response_hook


async def test_request_hook_publishes_jev_request_with_redacted_headers():
    bus = DevLogBus()
    token = start_turn(bus, "t1")
    try:
        request = httpx2.Request(
            "POST",
            "https://typesafe.test/v1/systemone",
            json={"state": {"latest": "hi"}, "questions": {"unsafe": {}}},
            headers={"Authorization": "Bearer sk-secret"},
        )
        await _devlog_request_hook(request)
    finally:
        end_turn(token)

    history, _ = bus.subscribe()
    (name, data) = history[0]
    assert name == "jev.request"
    assert data["method"] == "POST"
    assert data["url"] == "https://typesafe.test/v1/systemone"
    assert data["body"] == {"state": {"latest": "hi"}, "questions": {"unsafe": {}}}
    assert data["headers"]["Authorization"] == "Bearer ***"


async def test_response_hook_publishes_jev_response_with_status_and_body():
    bus = DevLogBus()
    token = start_turn(bus, "t1")
    try:
        response = httpx2.Response(
            200,
            json={"model": "jev-latest", "answers": {}},
            headers={"x-typesafe-request-id": "req-123"},
        )
        await _devlog_response_hook(response)
    finally:
        end_turn(token)

    history, _ = bus.subscribe()
    (name, data) = history[0]
    assert name == "jev.response"
    assert data["status"] == 200
    assert data["body"] == {"model": "jev-latest", "answers": {}}
    assert data["request_id"] == "req-123"
    assert "sk-secret" not in json.dumps(data)
