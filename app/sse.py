"""SSE adapter: turn a graph run into contracted events and a TurnRecord."""

import asyncio
import inspect
import json
from collections.abc import AsyncIterator, Callable
from time import perf_counter
from typing import Any
from uuid import uuid4

import anyio
from langchain_core.messages import HumanMessage

from app import devlog
from app.config import Settings
from app.devlog import DevLogBus
from app.telemetry import TurnRecord, cost, counterfactual_flash_cost

CHAT_NODES = ("chat_lite", "chat_flash")


def _event(name: str, data: dict[str, Any]) -> dict[str, str]:
    return {"event": name, "data": json.dumps(data)}


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p if isinstance(p, str) else p.get("text", "") for p in content)
    return ""


async def stream_turn(
    graph: Any,
    thread_id: str,
    message: str,
    requested_tier: str = "auto",
    *,
    settings: Settings | None = None,
    on_record: Callable[[TurnRecord], Any] | None = None,
    bus: DevLogBus | None = None,
) -> AsyncIterator[dict[str, str]]:
    """Yield guardrail, route?, token*, error?, done. `on_record` gets the TurnRecord exactly once.

    When `bus` is given, publishes the dev-log event sequence for the turn (`turn.start`,
    `llm.start`/`llm.first_token`/`llm.done` on the passed path, `turn.end`); see `app.devlog`.
    """
    config = {"configurable": {"thread_id": thread_id}}
    prior = (await graph.aget_state(config)).values.get("messages", [])
    record = TurnRecord(
        thread_id=thread_id,
        turn_index=sum(isinstance(m, HumanMessage) for m in prior),
        message=message,
    )
    started = perf_counter()
    ttft: float | None = None
    usage: dict[str, int] | None = None
    passed = False
    recorded = False
    llm_started = False
    token_count = 0
    devlog_token = devlog.start_turn(bus, str(uuid4())) if bus is not None else None
    if devlog_token is not None:
        devlog.emit("turn.start", thread_id=thread_id, requested_tier=requested_tier, message=message)

    async def finish() -> None:
        nonlocal recorded
        if recorded:
            return
        recorded = True
        record.latency_ms = {
            "jev": (record.jev_decision or {}).get("latency_ms", 0.0),
            "ttft": ttft if ttft is not None else 0.0,
            "total": (perf_counter() - started) * 1000,
        }
        record.usage = usage
        record.model = (record.route or {}).get("model")
        if settings is not None:
            record.cost_usd = cost(usage, record.model, settings.model_prices)
            record.counterfactual_flash_cost_usd = counterfactual_flash_cost(
                usage, settings.model_prices, settings.chat_model_flash
            )
        if record.error or (record.jev_decision and record.jev_decision.get("status") == "error"):
            outcome = "error"
        elif passed:
            outcome = "answered"
        else:
            outcome = "blocked"
        devlog.emit("turn.end", outcome=outcome, total_ms=record.latency_ms["total"])
        if on_record is not None:
            with anyio.CancelScope(shield=True):
                result = on_record(record)
                if inspect.isawaitable(result):
                    await result

    try:
        inputs = {"messages": [HumanMessage(message)], "requested_tier": requested_tier}
        try:
            async for mode, payload in graph.astream(
                inputs, config, stream_mode=["updates", "messages"]
            ):
                if mode == "updates" and "jev_gate" in payload:
                    update = payload["jev_gate"]
                    record.jev_decision = update["jev_decision"]
                    record.route = update["route"]
                    passed = update["guardrail_passed"]
                    yield _event("guardrail", update["jev_decision"])
                    if update["route"]:
                        yield _event("route", update["route"])
                        devlog.emit(
                            "llm.start", tier=update["route"]["tier"], model=update["route"]["model"]
                        )
                        llm_started = True
                    if not passed:
                        yield _event("token", {"text": _text(update["messages"][0].content)})
                elif mode == "messages":
                    chunk, meta = payload
                    if meta.get("langgraph_node") not in CHAT_NODES:
                        continue
                    if chunk.usage_metadata:
                        usage = usage or {"input_tokens": 0, "output_tokens": 0}
                        usage["input_tokens"] += chunk.usage_metadata["input_tokens"]
                        usage["output_tokens"] += chunk.usage_metadata["output_tokens"]
                    text = _text(chunk.content)
                    if text:
                        token_count += 1
                        if ttft is None:
                            ttft = (perf_counter() - started) * 1000
                            devlog.emit("llm.first_token", ttft_ms=ttft)
                        yield _event("token", {"text": text})
            if llm_started:
                devlog.emit("llm.done", token_count=token_count, usage=usage)
        except Exception as exc:
            record.error = f"{type(exc).__name__}: {exc}"
            yield _event("error", {"message": str(exc) or type(exc).__name__})
        await finish()
        yield _event(
            "done",
            {
                "guardrail_passed": passed,
                "model": record.model,
                "usage": usage,
                "cost_usd": record.cost_usd,
                "latency_ms": record.latency_ms,
            },
        )
    except (asyncio.CancelledError, GeneratorExit):
        if not recorded:
            record.error = "client_disconnected"
        raise
    finally:
        await finish()
        if devlog_token is not None:
            devlog.end_turn(devlog_token)
