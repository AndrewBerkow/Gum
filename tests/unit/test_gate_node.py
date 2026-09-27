import asyncio

import httpx2
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_typesafe.client import TypeSafeInternalServerError

from app.config import Settings
from app.jev import REJECTION_MESSAGES, make_jev_gate_node
from tests.unit.test_evaluate import resp


class Fake:
    def __init__(self, response=None, exc=None, delay=0.0):
        self.response, self.exc, self.delay, self.calls = response, exc, delay, []

    async def ainvoke(self, req, *a, **k):
        self.calls.append(req)
        await asyncio.sleep(self.delay or 0.001)
        if self.exc:
            raise self.exc
        return self.response


def state(text="hi", tier="auto"):
    return {"messages": [HumanMessage(text)], "requested_tier": tier, "guardrail_passed": False,
            "jev_decision": None, "route": None}


async def run(fake, st=None, **kw):
    node = make_jev_gate_node(fake, Settings(_env_file=None, **kw))
    return await node(st or state())


async def test_pass():
    out = await run(Fake(resp(rid="r1")))
    assert out["guardrail_passed"] is True and out["route"]["model"] == "gemini-3.5-flash-lite"
    assert out["jev_decision"]["request_id"] == "r1" and out["jev_decision"]["latency_ms"] > 0
    assert not out.get("messages")


async def test_block_appends_canned_message():
    out = await run(Fake(resp(0.95)))
    (m,) = out["messages"]
    assert out["guardrail_passed"] is False and out["route"] is None
    assert isinstance(m, AIMessage) and m.content == REJECTION_MESSAGES["unsafe"]
    assert m.additional_kwargs["jev_blocked"] is True


@pytest.mark.parametrize("exc", [TypeSafeInternalServerError(500, None, httpx2.Headers({})), RuntimeError("x")])
async def test_errors_fail_closed(exc):
    out = await run(Fake(exc=exc))
    assert out["jev_decision"]["status"] == "error" and out["jev_decision"]["latency_ms"] > 0
    assert out["guardrail_passed"] is False and out["route"] is None
    assert out["messages"][0].content == REJECTION_MESSAGES["jev_error"]


async def test_timeout_fails_closed():
    t0 = asyncio.get_running_loop().time()
    out = await run(Fake(resp(), delay=1.0), guardrail_timeout_s=0.05)
    assert asyncio.get_running_loop().time() - t0 < 0.8
    assert out["jev_decision"]["reason"] == "jev_error" and out["route"] is None


async def test_missing_answer_fails_closed():
    out = await run(Fake(resp(drop=("complexity",))))
    assert out["jev_decision"]["status"] == "error" and out["messages"]


async def test_single_call_all_questions():
    f = Fake(resp())
    await run(f, state("q"))
    assert len(f.calls) == 1 and set(f.calls[0]["questions"]) == {"unsafe", "scope", "complexity"}
    assert f.calls[0]["state"]["latest"].content == "q"


async def test_override_uses_settings_models():
    out = await run(Fake(resp(p_simple=0.9)), state(tier="flash"), chat_model_flash="F")
    assert out["route"]["model"] == "F" and out["route"]["source"] == "override"


def test_rejection_messages_cover_all_reasons():
    assert {"unsafe", "noise", "out_of_scope", "jev_error"} <= set(REJECTION_MESSAGES)
