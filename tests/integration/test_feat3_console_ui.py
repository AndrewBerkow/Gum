"""Top-level integration tests for t3 (FEATURE_PLAN.md Task 3): the split-panel Jev dev console
in `static/index.html`.

Public entry points used: the same real-uvicorn + Playwright/Chromium setup already established
by `tests/integration/test_t5_frontend_e2e.py` (`offline_url`, stub Jev + fake chat models, no
network beyond 127.0.0.1). This file drives the page exactly like `test_t5_frontend_e2e.py` does
(`open_page`, `send`) and only adds assertions about the new console panel; it imports the shared
fixtures/helpers rather than re-implementing them, following the cross-file-import precedent
`test_feat2_decision_explained.py` already set against `test_feat1_devlog_stream.py`.

`static/index.html` doesn't have a console yet (t1/t2 only touched the server side), so every
test here currently fails -- there is no `data-testid="devlog-panel"` etc. in the page at all.

## Markup contract this test file locks in (for the coming implementation)

The console consumes `GET /api/devlog` (an `EventSource`-compatible SSE stream, confirmed against
`app/main.py`'s `EventSourceResponse`) and renders:

- `[data-testid="chat-panel"]` -- wraps the existing chat UI (for the layout/stacking checks).
- `[data-testid="devlog-panel"]` -- the console root.
- `[data-testid="devlog-status"]` with `data-state="live"|"reconnecting"|"disabled"`.
- One `[data-testid="devlog-card"]` per turn, newest last, with `data-outcome` equal to the
  turn's `turn.end` outcome (`"answered"|"blocked"|"error"`, the same vocabulary `app/sse.py`
  already emits -- see `test_feat1_devlog_stream.py`).
- Inside each card, one `[data-testid="devlog-bar"][data-question="unsafe"|"scope"|"complexity"]`
  per Jev question (3 total), each containing a `[data-testid="devlog-threshold-marker"]` placed
  at the question's `threshold` fraction along the bar. `scope`'s bar additionally contains one
  `[data-testid="devlog-scope-bar"]` per label in `jev.decision.scope.probabilities` (3:012
  `valid_request`, `noise`, `out_of_scope`).
- A `[data-testid="devlog-timing"]` element with the Jev/ttft/total timings and model id --
  only `ttft`/model text when the turn actually reached an LLM (`llm.start` was emitted).
- `▸ request` / `▸ response` toggles (`[data-testid="devlog-request-toggle"]` /
  `[data-testid="devlog-response-toggle"]`) that reveal `[data-testid="devlog-request-json"]` /
  `[data-testid="devlog-response-json"]` raw JSON blocks.

These names are this test file's contract, not a re-derivation of anything already decided
elsewhere; the implementation is free to style them however it likes as long as the selectors and
outcome vocabulary above resolve.
"""

import re

import pytest

from tests.integration.test_t5_frontend_e2e import (
    COMPLEX_PROMPT,
    INJECTION,
    body_text,
    browser,
    offline_url,
    open_page,
    page,
    send,
)

pytestmark = pytest.mark.e2e

SIMPLE = "hi there"
# Exact `_one_liner` output for SIMPLE through the stub backend (app/jev_stub.py's heuristics:
# p_unsafe=0.05, scope=("valid_request", 0.92), complexity=("simple", 0.88)) against the default
# thresholds (Settings.block_threshold == Settings.route_lite_threshold == 0.70).
SIMPLE_ONE_LINER = "p_unsafe 0.05 ≤ 0.70 · scope valid_request 0.92 · p_simple 0.88 ≥ 0.70 → lite"
INJECTION_ONE_LINER = "p_unsafe 0.95 > 0.70 → blocked (unsafe)"
SCOPE_LABELS = ("valid_request", "noise", "out_of_scope")


# ---------------------------------------------------------------- element helpers


def panel(page):
    return page.locator('[data-testid="devlog-panel"]')


def cards(page):
    return page.locator('[data-testid="devlog-card"]')


def bar(card, question):
    return card.locator(f'[data-testid="devlog-bar"][data-question="{question}"]')


def wait_for_cards(page, n):
    page.wait_for_function(
        "(n) => document.querySelectorAll('[data-testid=\"devlog-card\"]').length >= n", arg=n
    )


# ---------------------------------------------------------------- criterion 1: simple turn card


def test_simple_message_shows_card_with_three_probability_bars_pass_lite_badge(page, offline_url):
    open_page(page, offline_url)
    send(page, SIMPLE)
    wait_for_cards(page, 1)
    card = cards(page).last
    assert card.get_attribute("data-outcome") == "answered"
    assert re.search(r"PASS.*lite", card.inner_text())
    for question in ("unsafe", "scope", "complexity"):
        assert bar(card, question).count() == 1, f"missing bar for {question}"
    assert SIMPLE_ONE_LINER in card.inner_text()


def test_simple_message_threshold_marker_sits_at_configured_position(page, offline_url):
    open_page(page, offline_url)
    send(page, SIMPLE)
    wait_for_cards(page, 1)
    card = cards(page).last
    unsafe_bar = bar(card, "unsafe")
    marker = unsafe_bar.locator('[data-testid="devlog-threshold-marker"]')
    bar_box = unsafe_bar.bounding_box()
    marker_box = marker.bounding_box()
    assert bar_box and marker_box, "bar or threshold marker not rendered"
    fraction = (marker_box["x"] - bar_box["x"]) / bar_box["width"]
    assert abs(fraction - 0.70) < 0.06, f"marker at {fraction:.2f}, expected ~0.70"


def test_scope_question_renders_stacked_mini_bars_for_every_label(page, offline_url):
    open_page(page, offline_url)
    send(page, SIMPLE)
    wait_for_cards(page, 1)
    card = cards(page).last
    scope_bars = bar(card, "scope").locator('[data-testid="devlog-scope-bar"]')
    assert scope_bars.count() == len(SCOPE_LABELS)
    labels = {scope_bars.nth(i).get_attribute("data-label") for i in range(scope_bars.count())}
    assert labels == set(SCOPE_LABELS)


# ---------------------------------------------------------------- criterion 2: blocked turn card


def test_injection_prompt_shows_blocked_unsafe_card(page, offline_url):
    open_page(page, offline_url)
    send(page, INJECTION)
    wait_for_cards(page, 1)
    card = cards(page).last
    assert card.get_attribute("data-outcome") == "blocked"
    text = card.inner_text()
    assert "BLOCKED" in text and "unsafe" in text
    assert INJECTION_ONE_LINER in text


def test_injection_prompt_timing_strip_has_no_model_or_ttft(page, offline_url):
    open_page(page, offline_url)
    send(page, INJECTION)
    wait_for_cards(page, 1)
    card = cards(page).last
    timing = card.locator('[data-testid="devlog-timing"]').inner_text()
    assert "ttft" not in timing.lower()
    assert "gemini" not in timing.lower()


# ---------------------------------------------------------------- criterion 3: raw JSON sections


def test_expanding_request_section_shows_questions_json_with_authorization_redacted(page, offline_url):
    open_page(page, offline_url)
    send(page, SIMPLE)
    wait_for_cards(page, 1)
    card = cards(page).last
    card.locator('[data-testid="devlog-request-toggle"]').click()
    raw = card.locator('[data-testid="devlog-request-json"]').inner_text()
    assert '"questions"' in raw
    assert "Bearer ***" in raw
    assert "stub-key" not in raw


def test_no_api_key_ever_appears_anywhere_on_the_page(page, offline_url):
    open_page(page, offline_url)
    send(page, SIMPLE)
    send(page, INJECTION)
    wait_for_cards(page, 2)
    for card_index in range(2):
        card = cards(page).nth(card_index)
        card.locator('[data-testid="devlog-request-toggle"]').click()
        card.locator('[data-testid="devlog-response-toggle"]').click()
    assert "stub-key" not in body_text(page)


# ---------------------------------------------------------------- criterion 4: card count / reload


def test_card_count_equals_number_of_turns_sent(page, offline_url):
    open_page(page, offline_url)
    send(page, SIMPLE)
    send(page, COMPLEX_PROMPT)
    send(page, INJECTION)
    wait_for_cards(page, 3)
    assert cards(page).count() == 3


def test_reloading_page_restores_recent_cards_from_ring_buffer(page, offline_url):
    open_page(page, offline_url)
    send(page, SIMPLE)
    send(page, COMPLEX_PROMPT)
    wait_for_cards(page, 2)
    page.reload()
    page.wait_for_selector("input")
    wait_for_cards(page, 2)
    assert cards(page).count() == 2


# ---------------------------------------------------------------- criterion 5: toggle / stacking


def test_ctrl_backslash_hides_and_shows_the_console(page, offline_url):
    open_page(page, offline_url)
    assert panel(page).is_visible()
    page.keyboard.press("Control+Backslash")
    page.wait_for_function(
        "() => { const el = document.querySelector('[data-testid=\"devlog-panel\"]'); "
        "return !el || el.offsetParent === null; }"
    )
    assert not panel(page).is_visible()
    page.keyboard.press("Control+Backslash")
    page.wait_for_selector('[data-testid="devlog-panel"]', state="visible")
    assert panel(page).is_visible()


def test_devlog_chat_command_also_toggles_the_console(page, offline_url):
    open_page(page, offline_url)
    assert panel(page).is_visible()
    page.locator("input").fill("/devlog")
    page.locator("input").press("Enter")
    page.wait_for_function(
        "() => { const el = document.querySelector('[data-testid=\"devlog-panel\"]'); "
        "return !el || el.offsetParent === null; }"
    )
    assert not panel(page).is_visible()


def test_panels_are_side_by_side_at_1280px_and_stacked_at_800px(page, offline_url):
    open_page(page, offline_url)
    page.set_viewport_size({"width": 1280, "height": 800})
    chat_box = page.locator('[data-testid="chat-panel"]').bounding_box()
    console_box = panel(page).bounding_box()
    assert chat_box and console_box
    assert chat_box["x"] + chat_box["width"] <= console_box["x"] + 1, (
        "chat and console should be side by side at 1280px"
    )

    page.set_viewport_size({"width": 800, "height": 800})
    page.wait_for_timeout(100)
    chat_box = page.locator('[data-testid="chat-panel"]').bounding_box()
    console_box = panel(page).bounding_box()
    assert chat_box and console_box
    vertically_separated = (
        chat_box["y"] + chat_box["height"] <= console_box["y"] + 1
        or console_box["y"] + console_box["height"] <= chat_box["y"] + 1
    )
    assert vertically_separated, "chat and console should stack at 800px"
