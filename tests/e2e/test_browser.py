"""PLAN T12: offline browser end-to-end (Playwright + real uvicorn, stub Jev, fake chat models)."""

import re

import pytest

from tests.integration.test_t5_frontend_e2e import (  # noqa: F401  (fixtures + helpers)
    COMPLEX_PROMPT,
    INJECTION,
    NOISE,
    body_text,
    browser,
    color_of,
    at_bottom,
    is_green,
    is_red,
    offline_url,
    open_page,
    page,
    send,
    split_url,
)

pytestmark = pytest.mark.e2e


def test_offline_banner_visible(page, offline_url):
    open_page(page, offline_url)
    page.wait_for_function("() => /OFFLINE/.test(document.body.innerText)")


def test_hi_there_lite_route_and_footer(page, offline_url):
    open_page(page, offline_url)
    send(page, "hi there")
    t = body_text(page)
    assert t.index("PASSED") < t.index("ROUTE: lite ← simple") < t.index("[offline:lite]") < t.index("gemini-3.5-flash-lite")
    assert is_green(color_of(page, "PASSED"))


def test_complex_routes_to_flash(page, offline_url):
    open_page(page, offline_url)
    send(page, COMPLEX_PROMPT)
    assert "ROUTE: flash ← complex" in body_text(page)


def test_injection_blocked_red_no_route(page, offline_url):
    open_page(page, offline_url)
    send(page, INJECTION)
    t = body_text(page)
    assert "BLOCKED — unsafe" in t and "ROUTE:" not in t and "[offline:" not in t
    assert is_red(color_of(page, "BLOCKED — unsafe"))


def test_noise_blocked(page, offline_url):
    open_page(page, offline_url)
    send(page, NOISE)
    assert "BLOCKED — noise" in body_text(page)


def test_model_override_route_line(page, offline_url):
    open_page(page, offline_url)
    send(page, "/model flash", expect_done=False)
    send(page, "hi there")
    assert "ROUTE: flash (override; jev→lite 0.88)" in body_text(page)


def test_stats_counts_turns(page, offline_url):
    open_page(page, offline_url)
    for m in ("hi there", COMPLEX_PROMPT, INJECTION):
        send(page, m)
    send(page, "/stats", expect_done=False)
    page.wait_for_function("() => /turns\\s+3/.test(document.body.innerText)")


def test_clear_and_history_recall(page, offline_url):
    open_page(page, offline_url)
    send(page, "hi there")
    page.locator("input").fill("/clear")
    page.locator("input").press("Enter")
    page.wait_for_function("() => !/ROUTE: lite/.test(document.body.innerText)")
    page.keyboard.press("ArrowUp")
    assert page.locator("input").input_value() == "/clear"


def test_autoscroll_after_30_turns(page, offline_url):
    open_page(page, offline_url)
    for i in range(30):
        send(page, f"hi there {i}")
    page.wait_for_timeout(300)
    assert at_bottom(page)


def test_sse_event_split_across_chunks(page, split_url):
    open_page(page, split_url)
    send(page, "hi there")
    assert "SPLITOK hello" in body_text(page)
