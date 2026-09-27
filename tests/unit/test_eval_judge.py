"""Unit tests for the offline-testable pieces of the --judge lite-adequacy judge (PLAN T11/T13).

The judge itself only ever runs live (it costs real Gemini calls), but its order-randomization,
blind-prompt and verdict-parsing logic is pure, and the orchestration can be driven with fake
chat models -- none of this needs a real key.
"""

import random

import pytest
from langchain_core.messages import AIMessage, HumanMessage

import evals.run_eval as ev


def test_lite_first_follows_the_rng_draw():
    low = random.Random()
    low.random = lambda: 0.1  # type: ignore[method-assign]
    high = random.Random()
    high.random = lambda: 0.9  # type: ignore[method-assign]

    assert ev.lite_first(low) is True
    assert ev.lite_first(high) is False


def test_render_judge_prompt_is_blind_to_lite_and_flash():
    prompt = ev.render_judge_prompt("what is 2+2?", "four", "2 + 2 = 4")
    assert "what is 2+2?" in prompt
    assert "four" in prompt
    assert "2 + 2 = 4" in prompt
    assert "lite" not in prompt.lower()
    assert "flash" not in prompt.lower()


@pytest.mark.parametrize(
    "text, expected",
    [("Yes, they are equally good.", True), ("No, answer B is more complete.", False), ("unclear", False)],
)
def test_parse_judge_verdict_reads_yes_no(text, expected):
    assert ev.parse_judge_verdict(text) is expected


class _FakeAnswerModel:
    """Returns a canned answer to ordinary questions, and a canned verdict to a judge prompt."""

    def __init__(self, answer: str, verdict: str | None = None):
        self._answer = answer
        self._verdict = verdict
        self.calls: list[list] = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        is_judge_prompt = "you are grading" in str(messages[-1].content).lower()
        return AIMessage(self._verdict if is_judge_prompt else self._answer)


async def test_run_judge_reports_adequacy_rate_and_failures():
    items = {
        "s1": {"id": "s1", "text": "hi there", "expect_gate": "pass", "expect_tier": "simple"},
        "s2": {"id": "s2", "text": "how are you", "expect_gate": "pass", "expect_tier": "simple"},
    }
    results = [
        {"id": "s1", "route_tier": "lite"},
        {"id": "s2", "route_tier": "lite"},
        {"id": "c1", "route_tier": "flash"},  # not lite-routed: excluded from the judge
    ]
    lite = _FakeAnswerModel("lite answer")
    flash = _FakeAnswerModel("flash answer", verdict="yes")
    rng = random.Random(0)

    out = await ev.run_judge(items, results, {"lite": lite, "flash": flash}, rng=rng)

    assert out["n"] == 2
    assert out["lite_adequacy_rate"] == pytest.approx(1.0)
    assert out["failures"] == []


async def test_run_judge_lists_failures_when_verdict_is_no():
    items = {"s1": {"id": "s1", "text": "hi there", "expect_gate": "pass", "expect_tier": "simple"}}
    results = [{"id": "s1", "route_tier": "lite"}]
    lite = _FakeAnswerModel("lite answer")
    flash = _FakeAnswerModel("flash answer", verdict="no")

    out = await ev.run_judge(items, results, {"lite": lite, "flash": flash}, rng=random.Random(0))

    assert out["lite_adequacy_rate"] == pytest.approx(0.0)
    assert out["failures"] == ["s1"]


def test_render_report_includes_judge_section_when_present():
    judge = {"n": 2, "lite_adequacy_rate": 0.5, "failures": ["s2"]}
    text = ev.render_report([], {"rows": [], "recommended": None, "target": 0.05}, date=__import__("datetime").date(2026, 1, 2), backend="live", judge=judge)
    lower = text.lower()
    assert "judge" in lower
    assert "50.0%" in text or "50%" in text
    assert "s2" in text
