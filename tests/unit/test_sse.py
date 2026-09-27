import json

from app.config import Settings
from app.graph import build_graph
from app.jev import REJECTION_MESSAGES
from app.sse import stream_turn
from tests.integration.test_t3_serving_stack import CrashModel, GatedModel, ScriptClassifier, SpyModel, spies


def graph_for(classifier=None, cls=SpyModel, **kw):
    s = Settings(_env_file=None, **kw)
    models = spies(cls)
    return build_graph(classifier or ScriptClassifier(), models, s), models, s


async def events(g, text, tier="auto", **kw):
    return [(e["event"], json.loads(e["data"])) async for e in stream_turn(g, "t", text, tier, **kw)]


async def test_stream_turn_order_passed():
    g, _, _ = graph_for()
    ev = await events(g, "hello")
    names = [n for n, _ in ev]
    assert names[:2] == ["guardrail", "route"] and names[-1] == "done"
    assert set(names[2:-1]) == {"token"} and len(names) > 4


async def test_stream_turn_order_blocked_has_single_canned_token_and_no_route():
    g, m, _ = graph_for()
    ev = await events(g, "INJECT")
    assert [n for n, _ in ev] == ["guardrail", "token", "done"]
    assert ev[1][1]["text"] == REJECTION_MESSAGES["unsafe"]
    assert m["lite"].calls == [] and m["flash"].calls == []


async def test_stream_turn_order_jev_error():
    g, _, _ = graph_for(ScriptClassifier(exc=RuntimeError("x")))
    ev = await events(g, "hello")
    assert [n for n, _ in ev] == ["guardrail", "token", "done"]
    assert ev[0][1]["status"] == "error"
    assert ev[1][1]["text"] == REJECTION_MESSAGES["jev_error"]


async def test_stream_turn_order_llm_crash():
    g, _, _ = graph_for(cls=CrashModel)
    ev = await events(g, "hello")
    names = [n for n, _ in ev]
    assert names[:2] == ["guardrail", "route"] and names[-2:] == ["error", "done"]
    assert "llm exploded" in ev[-2][1]["message"]


async def test_stream_turn_tokens_and_done_fields():
    g, _, s = graph_for()
    seen = []
    ev = await events(g, "hi there", on_record=lambda r: seen.append(r), settings=s)
    assert "".join(d["text"] for n, d in ev if n == "token") == "[offline:lite] You said: hi there"
    done = ev[-1][1]
    assert done["model"] == ev[1][1]["model"] == s.chat_model_lite
    assert done["usage"] == {"input_tokens": 2, "output_tokens": 5}
    assert 0 <= done["latency_ms"]["ttft"] <= done["latency_ms"]["total"]
    assert done["cost_usd"] is None and done["guardrail_passed"] is True
    assert len(seen) == 1 and seen[0].error is None and seen[0].model == s.chat_model_lite


async def test_stream_turn_guardrail_emitted_before_chat_model_runs():
    g, m, _ = graph_for(cls=GatedModel)
    stream = stream_turn(g, "t", "hello", "auto")
    first = await stream.__anext__()
    assert first["event"] == "guardrail"
    m["lite"].gate.set()
    rest = [e["event"] async for e in stream]
    assert rest[0] == "route" and rest[-1] == "done"


async def test_stream_turn_close_marks_client_disconnected():
    g, _, _ = graph_for()
    seen = []

    async def sink(r):
        seen.append(r)

    stream = stream_turn(g, "t", "hello", "auto", on_record=sink)
    await stream.__anext__()
    await stream.aclose()
    assert len(seen) == 1 and seen[0].error == "client_disconnected"
