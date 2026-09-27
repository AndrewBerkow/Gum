import json
import typing

from langchain_core.messages import AIMessage, HumanMessage

from app.state import ChatState, JevDecision, RouteDecision


def test_add_messages_appends():
    reducer = typing.get_type_hints(ChatState, include_extras=True)["messages"].__metadata__[0]
    assert [m.content for m in reducer([HumanMessage("a")], [AIMessage("b")])] == ["a", "b"]


def test_decisions_round_trip_json():
    g = JevDecision(status="passed", reason=None, confidence=0.9, p_unsafe=0.1, scope="valid_request",
                    scope_probabilities={"valid_request": 0.9}, flags=[], latency_ms=1.0,
                    jev_model="m", request_id=None)
    r = RouteDecision(tier="lite", model="x", source="jev", jev_tier="lite", p_simple=0.9,
                      complexity_confidence=0.8)
    assert json.loads(json.dumps(g)) == g and json.loads(json.dumps(r)) == r


def test_chat_state_keys():
    assert set(ChatState.__annotations__) == {"messages", "requested_tier", "guardrail_passed", "jev_decision", "route"}
