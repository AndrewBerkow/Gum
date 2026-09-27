from datetime import datetime

from app.devlog import DevLogBus, emit, end_turn, redact_headers, start_turn


def test_emit_populates_envelope_fields_and_is_noop_outside_a_turn():
    bus = DevLogBus()
    history_before, _ = bus.subscribe()
    emit("turn.start", thread_id="x")  # no active turn: must not raise, must not publish
    assert bus.subscribe()[0] == history_before

    token = start_turn(bus, "turn-1")
    emit("turn.start", thread_id="x")
    emit("turn.end", outcome="answered")
    end_turn(token)
    emit("turn.start", thread_id="after-end")  # no longer active: must not publish

    history, _ = bus.subscribe()
    assert len(history) == 2
    (name1, data1), (name2, data2) = history
    assert (name1, name2) == ("turn.start", "turn.end")
    assert data1["turn_id"] == data2["turn_id"] == "turn-1"
    assert data1["seq"] == 0 and data2["seq"] == 1
    assert datetime.fromisoformat(data1["ts"])
    assert isinstance(data1["t_ms"], int | float) and data1["t_ms"] >= 0
    assert data1["thread_id"] == "x"
    assert data2["outcome"] == "answered"


def test_redact_headers_hides_authorization_case_insensitively():
    headers = {"authorization": "Bearer sk-secret", "Content-Type": "application/json"}
    redacted = redact_headers(headers)
    assert redacted == {"authorization": "Bearer ***", "Content-Type": "application/json"}
    assert headers["authorization"] == "Bearer sk-secret"  # input untouched
