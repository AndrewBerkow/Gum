"""Top-level integration tests for FEATURE_PLAN_3.md t1: the console starts empty on page reload
(`GET /api/devlog?replay=0`) and the header Clear button.

Public entry points used: the real-uvicorn + Playwright/Chromium setup from
`tests/integration/test_t5_frontend_e2e.py` (`offline_url`: stub Jev + fake chat models, nothing
beyond 127.0.0.1), driven like `test_feat3_console_ui.py`; plus raw `GET /api/devlog[?replay=0]`
and `POST /api/chat` over real HTTP for the API-level criteria.

Markup contract: `[data-testid="devlog-clear"]` with `title="Clear console and chat"` inside the
console header (`#devlog-header`), a sibling of `[data-testid="devlog-status"]`.
"""

import asyncio
import json

import httpx
import pytest

from tests.integration.test_t5_frontend_e2e import (
    browser,
    offline_url,
    open_page,
    page,
    send,
)

SIMPLE = "hi there"
LIVE = '[data-testid="devlog-status"][data-state="live"]'


def cards(page):
    return page.locator('[data-testid="devlog-card"]')


def clear_button(page):
    return page.locator('[data-testid="devlog-clear"]')


def wait_for_cards(page, n):
    page.wait_for_function(
        "(n) => document.querySelectorAll('[data-testid=\"devlog-card\"]').length >= n", arg=n
    )


def thread_id(page):
    return page.evaluate("sessionStorage.getItem('thread_id')")


def chat_log_text(page) -> str:
    return page.locator("#log").inner_text().strip()


def send_two_and_wait(page):
    send(page, SIMPLE)
    send(page, SIMPLE)
    wait_for_cards(page, 2)
    assert cards(page).count() == 2


def assert_console_stays_at(page, n):
    page.wait_for_timeout(500)
    assert cards(page).count() == n


# ---------------------------------------------------------------- browser: reload


@pytest.mark.e2e
def test_reload_after_two_messages_shows_zero_cards_and_next_message_shows_exactly_one(page, offline_url):
    open_page(page, offline_url)
    send_two_and_wait(page)
    page.reload()
    page.wait_for_selector("input")
    page.wait_for_selector(LIVE)
    assert_console_stays_at(page, 0)
    send(page, SIMPLE)
    wait_for_cards(page, 1)
    assert_console_stays_at(page, 1)


# ---------------------------------------------------------------- browser: Clear button


@pytest.mark.e2e
def test_clear_button_empties_console_and_chat_log_changes_thread_and_next_message_shows_one_card(
    page, offline_url
):
    open_page(page, offline_url)
    send_two_and_wait(page)
    before = thread_id(page)
    assert before and chat_log_text(page)

    clear_button(page).click()
    page.wait_for_function("() => document.querySelectorAll('[data-testid=\"devlog-card\"]').length === 0")
    assert cards(page).count() == 0
    assert chat_log_text(page) == ""
    after = thread_id(page)
    assert after and after != before

    # the devlog connection stayed open: the next turn arrives as the first (and only) card
    assert page.locator(LIVE).count() == 1
    send(page, SIMPLE)
    wait_for_cards(page, 1)
    assert_console_stays_at(page, 1)
    assert cards(page).first.locator(".devlog-turn-index").inner_text().strip() == "#1", (
        "card counter was not reset by Clear"
    )


@pytest.mark.e2e
def test_clear_button_does_not_reset_server_stats(page, offline_url):
    open_page(page, offline_url)
    send_two_and_wait(page)
    with httpx.Client() as c:
        before = c.get(f"{offline_url}/api/stats").json()
    assert before["turns"] == 2
    assert clear_button(page).count() == 1, "no Clear button in the console"
    clear_button(page).click()
    page.wait_for_function("() => document.querySelectorAll('[data-testid=\"devlog-card\"]').length === 0")
    with httpx.Client() as c:
        after = c.get(f"{offline_url}/api/stats").json()
    assert after == before


@pytest.mark.e2e
def test_clear_button_has_title_and_sits_in_console_header_next_to_status_dot(page, offline_url):
    open_page(page, offline_url)
    button = clear_button(page)
    assert button.count() == 1, "no Clear button in the console"
    assert button.get_attribute("title") == "Clear console and chat"
    same_header = page.evaluate(
        """() => {
            const b = document.querySelector('[data-testid="devlog-clear"]');
            const s = document.querySelector('[data-testid="devlog-status"]');
            const header = document.getElementById('devlog-header');
            return !!(b && s && header && b.parentElement === header && s.parentElement === header
                      && header.closest('[data-testid="devlog-panel"]'));
        }"""
    )
    assert same_header, "Clear button and status dot must both be direct children of #devlog-header"
    button_box, dot_box = button.bounding_box(), page.locator('[data-testid="devlog-status"]').bounding_box()
    assert button_box and dot_box
    assert abs(button_box["y"] + button_box["height"] / 2 - (dot_box["y"] + dot_box["height"] / 2)) < 20
    assert button.is_visible()


# ---------------------------------------------------------------- browser: /clear command


@pytest.mark.e2e
def test_slash_clear_chat_command_also_empties_the_console(page, offline_url):
    open_page(page, offline_url)
    send_two_and_wait(page)
    page.locator("input").fill("/clear")
    page.locator("input").press("Enter")
    page.wait_for_function("() => document.querySelectorAll('[data-testid=\"devlog-card\"]').length === 0")
    assert cards(page).count() == 0
    assert chat_log_text(page) == ""
    send(page, SIMPLE)
    wait_for_cards(page, 1)
    assert_console_stays_at(page, 1)


# ---------------------------------------------------------------- browser: reconnect uses replay=0


@pytest.mark.e2e
def test_page_requests_devlog_with_replay_0_on_initial_connect_and_every_automatic_reconnect(
    page, offline_url
):
    urls: list[str] = []

    def handler(route):
        urls.append(route.request.url)
        if len(urls) <= 2:
            route.abort()  # force the page's automatic reconnect loop to fire (twice)
        else:
            route.continue_()

    page.route("**/api/devlog*", handler)
    open_page(page, offline_url)
    page.wait_for_selector(LIVE, timeout=15000)
    assert len(urls) >= 3, f"expected initial connect plus reconnects, saw {urls}"
    assert all("replay=0" in u for u in urls), urls


# ---------------------------------------------------------------- API: replay parameter


class Stream:
    """Real-HTTP reader for the never-ending `/api/devlog` SSE stream."""

    def __init__(self, base_url, query=""):
        self.url = f"{base_url}/api/devlog{query}"
        self.events: list[tuple[str, dict]] = []
        self._client = httpx.AsyncClient(timeout=None)
        self._cm = None
        self._resp = None

    async def open(self):
        self._cm = self._client.stream("GET", self.url)
        self._resp = await self._cm.__aenter__()
        assert self._resp.status_code == 200

    async def read_until(self, predicate, timeout):
        async def loop():
            name, data = None, []
            async for line in self._resp.aiter_lines():
                if line.startswith("event:"):
                    name = line[6:].strip()
                elif line.startswith("data:"):
                    data.append(line[5:].lstrip())
                elif not line.strip():
                    if name is not None and data:
                        self.events.append((name, json.loads("\n".join(data))))
                    name, data = None, []
                    if predicate(self.events):
                        return True
            return False

        try:
            return await asyncio.wait_for(loop(), timeout=timeout)
        except TimeoutError:
            return False

    async def close(self):
        if self._cm is not None:
            await self._cm.__aexit__(None, None, None)
        await self._client.aclose()


def _turn_ends(events):
    return sum(1 for n, _ in events if n == "turn.end")


async def _chat(base_url, message, thread):
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(f"{base_url}/api/chat", json={"thread_id": thread, "message": message})
    assert r.status_code == 200


async def test_devlog_without_replay_param_still_replays_earlier_turns(offline_url):
    await _chat(offline_url, SIMPLE, "a")
    await _chat(offline_url, SIMPLE, "b")
    stream = Stream(offline_url)
    await stream.open()
    ok = await stream.read_until(lambda evs: _turn_ends(evs) >= 2, timeout=5)
    await stream.close()
    assert ok, [n for n, _ in stream.events]
    assert len({d["turn_id"] for _, d in stream.events}) == 2


async def test_devlog_replay_0_skips_history_then_delivers_a_new_turns_events(offline_url):
    await _chat(offline_url, SIMPLE, "a")
    await _chat(offline_url, SIMPLE, "b")
    stream = Stream(offline_url, "?replay=0")
    await stream.open()
    replayed = await stream.read_until(lambda evs: len(evs) > 0, timeout=1.5)
    assert not replayed, f"replay=0 delivered history: {[n for n, _ in stream.events]}"
    assert stream.events == []

    await _chat(offline_url, SIMPLE, "c")
    ok = await stream.read_until(lambda evs: _turn_ends(evs) >= 1, timeout=5)
    await stream.close()
    assert ok, [n for n, _ in stream.events]
    names = [n for n, _ in stream.events]
    assert names[0] == "turn.start" and names.count("turn.start") == 1
    assert len({d["turn_id"] for _, d in stream.events}) == 1
