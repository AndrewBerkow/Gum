import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.jev import build_request


def blocked(t):
    return AIMessage(t, additional_kwargs={"jev_blocked": True})


def test_latest_is_last_human():
    req = build_request([HumanMessage("h1"), AIMessage("a1"), HumanMessage("h2")], 2)
    assert req["state"]["latest"].content == "h2"
    assert set(req["questions"]) == {"unsafe", "scope", "complexity"}


def test_recent_capped():
    msgs = []
    for i in range(1, 6):
        msgs += [HumanMessage(f"h{i}"), AIMessage(f"a{i}")]
    msgs.append(HumanMessage("q"))
    recent = [m.content for m in build_request(msgs, 2)["state"]["recent"]]
    assert len(recent) <= 4 and "a5" in recent and "h1" not in recent
    assert build_request(msgs, 0)["state"]["recent"] == []


def test_recent_excludes_blocked_pairs():
    msgs = [HumanMessage("h1"), AIMessage("a1"), HumanMessage("evil"), blocked("canned"),
            HumanMessage("h3"), AIMessage("a3"), HumanMessage("q")]
    recent = [m.content for m in build_request(msgs, 5)["state"]["recent"]]
    assert "evil" not in recent and "canned" not in recent and "a3" in recent and "h1" in recent


def test_blocked_latest_is_not_dropped():
    # only *earlier* blocked pairs are excluded; the latest human message is always sent
    msgs = [HumanMessage("evil"), blocked("canned"), HumanMessage("q")]
    assert build_request(msgs, 2)["state"]["latest"].content == "q"


def test_empty_raises():
    with pytest.raises(ValueError):
        build_request([], 2)


def test_no_human_message_raises():
    with pytest.raises(ValueError):
        build_request([AIMessage("a")], 2)
