from app.config import Settings
from app.devlog import DevLogBus
from app.graph import build_graph
from app.sse import stream_turn
from tests.integration.test_t3_serving_stack import ScriptClassifier, spies


def graph_for(**kw):
    settings = Settings(_env_file=None, **kw)
    return build_graph(ScriptClassifier(), spies(), settings), settings


async def drain(gen):
    return [e async for e in gen]


async def test_stream_turn_emits_turn_start_first_with_thread_and_message():
    graph, settings = graph_for()
    bus = DevLogBus()
    await drain(stream_turn(graph, "thread-1", "hi there", "auto", settings=settings, bus=bus))

    history, _ = bus.subscribe()
    name, data = history[0]
    assert name == "turn.start"
    assert data["thread_id"] == "thread-1"
    assert data["requested_tier"] == "auto"
    assert data["message"] == "hi there"


async def test_stream_turn_emits_llm_events_and_turn_end_answered_on_passed_path():
    graph, settings = graph_for()
    bus = DevLogBus()
    await drain(stream_turn(graph, "thread-1", "hi there", "auto", settings=settings, bus=bus))

    history, _ = bus.subscribe()
    names = [n for n, _ in history]
    assert names == [
        "turn.start",
        "jev.decision",
        "llm.start",
        "llm.first_token",
        "llm.done",
        "turn.end",
    ]

    turn_ids = {d["turn_id"] for _, d in history}
    assert len(turn_ids) == 1
    seqs = [d["seq"] for _, d in history]
    assert seqs == list(range(len(seqs)))

    llm_start = next(d for n, d in history if n == "llm.start")
    assert llm_start["tier"] == "lite" and llm_start["model"] == settings.chat_model_lite

    llm_done = next(d for n, d in history if n == "llm.done")
    assert llm_done["token_count"] > 0
    assert llm_done["usage"] == {"input_tokens": 2, "output_tokens": 5}

    end = next(d for n, d in history if n == "turn.end")
    assert end["outcome"] == "answered"


async def test_stream_turn_emits_turn_end_blocked_with_no_llm_events():
    graph, settings = graph_for()
    bus = DevLogBus()
    await drain(stream_turn(graph, "thread-1", "INJECT this", "auto", settings=settings, bus=bus))

    history, _ = bus.subscribe()
    names = [n for n, _ in history]
    assert not any(n.startswith("llm.") for n in names)

    decision = next(d for n, d in history if n == "jev.decision")
    assert decision["outcome"] == "blocked"
    end = next(d for n, d in history if n == "turn.end")
    assert end["outcome"] == "blocked"
