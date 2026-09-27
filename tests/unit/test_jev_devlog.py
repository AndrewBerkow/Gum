from langchain_core.messages import HumanMessage

from app.config import Settings
from app.devlog import DevLogBus, end_turn, start_turn
from app.jev import make_jev_gate_node
from tests.integration.test_t3_serving_stack import ScriptClassifier


def settings(**kw):
    return Settings(_env_file=None, jev_backend="stub", chat_provider="fake", **kw)


async def _run_gate(classifier, message):
    bus = DevLogBus()
    token = start_turn(bus, "t1")
    try:
        gate = make_jev_gate_node(classifier, settings())
        await gate({"messages": [HumanMessage(message)], "requested_tier": "auto"})
    finally:
        end_turn(token)
    return bus.subscribe()[0]


async def test_jev_gate_emits_jev_decision_with_outcome_matching_status():
    history = await _run_gate(ScriptClassifier(), "hello")
    decision = next(d for n, d in history if n == "jev.decision")
    assert decision["outcome"] == "passed"

    history = await _run_gate(ScriptClassifier(), "INJECT this")
    decision = next(d for n, d in history if n == "jev.decision")
    assert decision["outcome"] == "blocked"


async def test_jev_gate_emits_jev_error_on_classifier_failure():
    history = await _run_gate(ScriptClassifier(exc=RuntimeError("boom")), "hello")
    names = [n for n, _ in history]
    assert names.index("jev.error") < names.index("jev.decision")
    error = next(d for n, d in history if n == "jev.error")
    assert error["error_type"] == "RuntimeError"
    assert "boom" in error["message"]
    decision = next(d for n, d in history if n == "jev.decision")
    assert decision["outcome"] == "error"
