"""LangGraph assembly: jev_gate, then chat_lite / chat_flash, or END when blocked."""

from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.config import Settings
from app.jev import _drop_blocked_pairs, make_jev_gate_node
from app.state import ChatState, Tier


def route_after_gate(state: ChatState) -> Literal["chat_lite", "chat_flash", "__end__"]:
    decision = state.get("jev_decision")
    route = state.get("route")
    if not decision or decision["status"] != "passed" or not route:
        return END
    return "chat_lite" if route["tier"] == "lite" else "chat_flash"


def make_chat_node(model: BaseChatModel):
    async def chat(state: ChatState) -> dict[str, Any]:
        reply = await model.ainvoke(_drop_blocked_pairs(list(state["messages"])))
        return {"messages": [reply]}

    return chat


def build_graph(
    classifier: Any,
    chat_models: dict[Tier, BaseChatModel],
    settings: Settings,
    checkpointer: Any = None,
):
    builder = StateGraph(ChatState)
    builder.add_node("jev_gate", make_jev_gate_node(classifier, settings))
    builder.add_node("chat_lite", make_chat_node(chat_models["lite"]))
    builder.add_node("chat_flash", make_chat_node(chat_models["flash"]))
    builder.add_edge(START, "jev_gate")
    builder.add_conditional_edges("jev_gate", route_after_gate, ["chat_lite", "chat_flash", END])
    builder.add_edge("chat_lite", END)
    builder.add_edge("chat_flash", END)
    return builder.compile(checkpointer=checkpointer or MemorySaver())
