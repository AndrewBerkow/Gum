"""Unit tests for static/index.html. Pure helpers are exposed as window.Gum and run in headless Chromium."""

import re
from pathlib import Path

import pytest

INDEX = Path(__file__).resolve().parents[2] / "static" / "index.html"


@pytest.fixture(scope="module")
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page(browser):
    pg = browser.new_page()
    pg.goto(INDEX.as_uri())
    yield pg
    pg.close()


# 1. shell
def test_shell_is_single_file_dark_monospace_terminal_with_one_input():
    html = INDEX.read_text()
    assert "<style" in html and "<script" in html
    assert not re.search(r"<script[^>]+src=|<link[^>]+stylesheet|https?://", html, re.I)
    assert "monospace" in html
    assert len(re.findall(r"<input\b", html)) == 1
    assert 'id="log"' in html and "overflow-y" in html


def test_shell_references_endpoints_and_uses_stream_reader():
    html = INDEX.read_text()
    for needle in ("/api/chat", "/api/stats", "/healthz", "getReader", "sessionStorage"):
        assert needle in html
    assert "EventSource" not in html


# 2. SSE parser
def test_sse_parser_reassembles_event_split_across_chunks(page):
    out = page.evaluate(
        """() => {
            const p = Gum.createSSEParser();
            const a = p.push('event: token\\r\\ndata: {"te');
            const b = p.push('xt": "hi"}\\r\\n\\r\\nevent: done\\ndata: {}\\n\\n');
            return [a, b];
        }"""
    )
    assert out[0] == []
    assert out[1] == [{"event": "token", "data": {"text": "hi"}}, {"event": "done", "data": {}}]


def test_sse_parser_handles_crlf_split_between_chunks(page):
    out = page.evaluate(
        """() => {
            const p = Gum.createSSEParser();
            return [p.push('event: route\\r\\ndata: {"a":1}\\r'), p.push('\\n\\r\\n')];
        }"""
    )
    assert out[0] == [] and out[1] == [{"event": "route", "data": {"a": 1}}]


# 3. formatters
def test_format_guardrail_passed_blocked_and_error(page):
    f = lambda d: page.evaluate("(d) => Gum.formatGuardrail(d)", d)  # noqa: E731
    ok = f({"status": "passed", "p_unsafe": 0.08, "confidence": 0.92, "latency_ms": 38.2})
    assert ok["text"] == "[JEV GUARDRAIL: PASSED (0.92)] 38ms" and ok["cls"] == "green"
    bad = f({"status": "blocked", "reason": "unsafe", "confidence": 0.95, "latency_ms": 41})
    assert bad["text"] == "[JEV GUARDRAIL: BLOCKED — unsafe (0.95)] 41ms" and bad["cls"] == "red"
    err = f({"status": "error", "reason": "jev_error", "confidence": 0, "latency_ms": 5})
    assert "ERROR — fail-closed" in err["text"] and err["cls"] == "amber"


def test_format_route_jev_and_override(page):
    f = lambda d: page.evaluate("(d) => Gum.formatRoute(d)", d)  # noqa: E731
    lite = f({"tier": "lite", "source": "jev", "jev_tier": "lite", "p_simple": 0.88})
    assert lite == {"text": "[JEV ROUTE: lite ← simple (0.88)]", "cls": "cyan"}
    flash = f({"tier": "flash", "source": "jev", "jev_tier": "flash", "p_simple": 0.15})
    assert flash == {"text": "[JEV ROUTE: flash ← complex (0.85)]", "cls": "magenta"}
    ov = f({"tier": "flash", "source": "override", "jev_tier": "lite", "p_simple": 0.88})
    assert ov == {"text": "[JEV ROUTE: flash (override; jev→lite 0.88)]", "cls": "yellow"}


def test_format_footer_with_and_without_usage_and_cost(page):
    f = lambda d: page.evaluate("(d) => Gum.formatFooter(d)", d)  # noqa: E731
    full = f({"model": "gemini-3.5-flash-lite", "usage": {"input_tokens": 42, "output_tokens": 310},
              "cost_usd": 0.00012, "latency_ms": {"ttft": 180}})
    assert full == "  · gemini-3.5-flash-lite · ttft 180ms · 42→310 tok · $0.00012"
    bare = f({"model": "m", "usage": None, "cost_usd": None, "latency_ms": {"ttft": 3}})
    assert bare == "  · m · ttft 3ms"
    assert f({"model": None, "latency_ms": {}}) is None


# 4. commands
def test_parse_command(page):
    f = lambda s: page.evaluate("(s) => Gum.parseCommand(s)", s)  # noqa: E731
    assert f("hello") is None
    assert f("/model flash") == {"name": "model", "arg": "flash"}
    assert f("/stats") == {"name": "stats", "arg": ""}
    assert f("/clear") == {"name": "clear", "arg": ""}
    assert f("/model gpt-4") == {"name": "model", "arg": "gpt-4"}


# 5. history
def test_history_up_down_navigation(page):
    out = page.evaluate(
        """() => {
            const h = Gum.createHistory();
            h.add('a'); h.add('b');
            return [h.up('draft'), h.up('x'), h.up('x'), h.down(), h.down(), h.down()];
        }"""
    )
    assert out == ["b", "a", "a", "b", "draft", "draft"]


# 6. stats table
def test_format_stats_flattens_nested_values_into_aligned_rows(page):
    rows = page.evaluate(
        "(s) => Gum.formatStats(s)",
        {"turns": 5, "blocked_pct": {"unsafe": 20.0}, "total_cost_usd": None,
         "jev_latency_ms": {"p50": 30, "p95": 41}},
    )
    lines = rows.split("\n")
    assert re.match(r"turns\s+5$", lines[0])
    assert any(re.match(r"blocked_pct\.unsafe\s+20$", line) or "blocked_pct.unsafe" in line for line in lines)
    assert any(re.match(r"total_cost_usd\s+—$", line) for line in lines)
    assert len({line.index(line.split()[-1]) for line in lines if line}) == 1  # aligned value column


# 7. scroll stickiness
def test_near_bottom_detects_user_scrolled_up(page):
    out = page.evaluate(
        "() => [Gum.nearBottom({scrollHeight: 1000, clientHeight: 300, scrollTop: 700}),"
        " Gum.nearBottom({scrollHeight: 1000, clientHeight: 300, scrollTop: 300})]"
    )
    assert out == [True, False]


# 8. devlog console: turn-event reducer
def test_merge_devlog_event_folds_full_turn_sequence_into_accumulator(page):
    turn = page.evaluate(
        """() => {
            let t = {};
            const fold = (name, data) => { t = Gum.mergeDevlogEvent(t, name, data); };
            fold("turn.start", {turn_id: "abc", message: "hi there"});
            fold("jev.request", {turn_id: "abc", body: {questions: {}}});
            fold("jev.response", {turn_id: "abc", body: {ok: true}});
            fold("jev.decision", {turn_id: "abc", t_ms: 12.4, outcome: "passed",
                                  explanation: "p_unsafe 0.05 ≤ 0.70 → lite"});
            fold("llm.start", {turn_id: "abc", tier: "lite", model: "gemini-3.5-flash-lite"});
            fold("llm.first_token", {turn_id: "abc", ttft_ms: 45.2});
            fold("llm.done", {turn_id: "abc", token_count: 7});
            fold("turn.end", {turn_id: "abc", outcome: "answered", total_ms: 210.9});
            return t;
        }"""
    )
    assert turn["message"] == "hi there"
    assert turn["request"]["body"] == {"questions": {}}
    assert turn["response"]["body"] == {"ok": True}
    assert turn["decision"]["explanation"] == "p_unsafe 0.05 ≤ 0.70 → lite"
    assert turn["jevMs"] == 12.4
    assert turn["llmStart"] == {"turn_id": "abc", "tier": "lite", "model": "gemini-3.5-flash-lite"}
    assert turn["ttftMs"] == 45.2
    assert turn["llmDone"]["token_count"] == 7
    assert turn["outcome"] == "answered"
    assert turn["totalMs"] == 210.9


def test_merge_devlog_event_folds_jev_error(page):
    turn = page.evaluate(
        """() => {
            let t = Gum.mergeDevlogEvent({}, "turn.start", {turn_id: "z"});
            t = Gum.mergeDevlogEvent(t, "jev.error", {error_type: "TimeoutError", message: "boom"});
            return t;
        }"""
    )
    assert turn["error"] == {"error_type": "TimeoutError", "message": "boom"}


# 9. devlog console: badge / timing / bar-position / scope-bars / persistence helpers
def test_devlog_badge_passed_blocked_and_error(page):
    out = page.evaluate(
        """() => [
            Gum.devlogBadge({outcome: "answered", decision: {route: {tier: "lite"}}}),
            Gum.devlogBadge({outcome: "blocked", decision: {reason: "unsafe"}}),
            Gum.devlogBadge({outcome: "error"}),
        ]"""
    )
    assert out[0] == {"text": "PASS → lite", "cls": "green"}
    assert out[1] == {"text": "BLOCKED (unsafe)", "cls": "red"}
    assert out[2] == {"text": "ERROR", "cls": "amber"}


def test_devlog_timing_text_omits_ttft_and_model_when_no_llm_start(page):
    out = page.evaluate(
        """() => [
            Gum.devlogTimingText({jevMs: 12.4, ttftMs: 45.2, totalMs: 210.9,
                                   llmStart: {model: "gemini-3.5-flash-lite"}}),
            Gum.devlogTimingText({jevMs: 8.1, totalMs: 9.3}),
        ]"""
    )
    assert out[0] == "jev 12ms · ttft 45ms · total 211ms · gemini-3.5-flash-lite"
    assert "ttft" not in out[1] and "gemini" not in out[1]
    assert out[1] == "jev 8ms · total 9ms"


def test_devlog_bar_pct_clamps_to_unit_interval(page):
    out = page.evaluate("() => [Gum.devlogBarPct(0.7), Gum.devlogBarPct(-1), Gum.devlogBarPct(5)]")
    assert out == [0.7, 0, 1]


def test_scope_bars_lists_one_entry_per_probability_label(page):
    out = page.evaluate(
        """() => Gum.scopeBars({choice: "valid_request",
            probabilities: {valid_request: 0.92, noise: 0.04, out_of_scope: 0.04}})"""
    )
    assert {(b["label"], b["p"]) for b in out} == {
        ("valid_request", 0.92), ("noise", 0.04), ("out_of_scope", 0.04)
    }


def test_devlog_visibility_persists_through_local_storage_and_survives_a_throwing_backend(page):
    out = page.evaluate(
        """() => {
            localStorage.removeItem("devlog_visible");
            const before = Gum.loadDevlogVisible();
            Gum.saveDevlogVisible(false);
            const after = Gum.loadDevlogVisible();
            const fakeStorage = { getItem() { throw new Error("blocked"); },
                                   setItem() { throw new Error("blocked"); } };
            const safeLoad = Gum.loadDevlogVisible(fakeStorage);
            Gum.saveDevlogVisible(true, fakeStorage);
            return [before, after, safeLoad];
        }"""
    )
    assert out == [True, False, True]
