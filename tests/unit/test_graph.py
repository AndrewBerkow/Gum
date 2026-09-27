import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END

from app.config import Settings
from app.graph import build_graph, make_chat_node, route_after_gate
from app.providers import FakeChatModel
from tests.integration.test_t3_serving_stack import ScriptClassifier, SpyModel


def st(status, tier=None):
    return {"jev_decision": {"status": status}, "route": {"tier": tier} if tier else None}


def test_route_after_gate_passed_lite():
    assert route_after_gate(st("passed", "lite")) == "chat_lite"


def test_route_after_gate_passed_flash():
    assert route_after_gate(st("passed", "flash")) == "chat_flash"


@pytest.mark.parametrize("status", ["blocked", "error"])
def test_route_after_gate_blocked_or_error_ends(status):
    assert route_after_gate(st(status)) == END


async def test_chat_node_filters_blocked_pairs():
    model = SpyModel(tier="lite")
    node = make_chat_node(model)
    msgs = [
        HumanMessage("bad"),
        AIMessage("no", additional_kwargs={"jev_blocked": True}),
        HumanMessage("good"),
    ]
    out = await node({"messages": msgs})
    assert [m.content for m in model.calls[0]] == ["good"]
    assert out["messages"][0].content.startswith("[offline:lite]")


async def test_build_graph_routes_and_persists_history():
    s = Settings(_env_file=None)
    models = {"flash": SpyModel(tier="flash"), "lite": SpyModel(tier="lite")}
    g = build_graph(ScriptClassifier(), models, s)
    cfg = {"configurable": {"thread_id": "t"}}
    await g.ainvoke({"messages": [HumanMessage("hello")], "requested_tier": "auto"}, cfg)
    await g.ainvoke({"messages": [HumanMessage("COMPLEX")], "requested_tier": "auto"}, cfg)
    assert len(models["lite"].calls) == 1 and len(models["flash"].calls) == 1
    assert len((await g.aget_state(cfg)).values["messages"]) == 4
