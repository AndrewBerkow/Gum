from typing import Annotated, Literal

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

Tier = Literal["flash", "lite"]


class JevDecision(TypedDict):
    status: Literal["passed", "blocked", "error"]
    reason: str | None
    confidence: float
    p_unsafe: float | None
    scope: str | None
    scope_probabilities: dict[str, float] | None
    flags: list[str]
    latency_ms: float
    jev_model: str
    request_id: str | None


class RouteDecision(TypedDict):
    tier: Tier
    model: str
    source: Literal["jev", "override"]
    jev_tier: Tier
    p_simple: float
    complexity_confidence: float


class ChatState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    requested_tier: Literal["auto", "flash", "lite"]
    guardrail_passed: bool
    jev_decision: JevDecision | None
    route: RouteDecision | None
