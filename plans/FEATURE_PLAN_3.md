# Feature Plan 3: console starts empty on reload + a Clear button

**One small task. Don't split it.** This changes only the browser UI in `static/index.html`, plus one small optional server parameter. `FEATURE_PLAN.md` has the console spec. `PLAN.md` is still the source of truth and "NO REAL API KEYS" still applies. A real `.env` exists in the developer's checkout: don't touch it, and make no real API calls.

## What to change

1. **The console starts empty after a page reload.** Today `/api/devlog` replays its ring buffer (the last 200 events) on connect, so a reload brings back old cards. The browser console must **not** show events from before the page loaded.
   - Add a query parameter `GET /api/devlog?replay=0` that skips the buffered history and streams only new events. The default (`replay` omitted) keeps today's behaviour, so the existing API tests still hold.
   - The page connects with `?replay=0`, including on every automatic reconnect. After a server restart or a network blip, the console must not refill with history.
2. **A Clear button** in the console header, next to the status dot. It has `data-testid="devlog-clear"`, `title="Clear console and chat"`, and it's styled like the rest of the terminal UI. One click:
   - removes every console card and resets the card counter;
   - clears the chat log and starts a new conversation (a new `thread_id`), exactly like the existing `/clear` chat command;
   - leaves the devlog connection open, so the next message shows up as a new card;
   - doesn't touch server-side `/stats` totals.
   The existing `/clear` chat command also clears the console, so both behave the same way.

## Tests first (`tests/integration/test_feat7_console_clear.py`)
Playwright against a real uvicorn on localhost with `JEV_BACKEND=stub CHAT_PROVIDER=fake`, set up the same way as `tests/integration/test_feat3_console_ui.py`:
- Send 2 messages, and the console shows 2 cards. **Reload** the page, and the console shows **0** cards. Send 1 more, and it shows exactly 1.
- Send 2 messages and click `[data-testid="devlog-clear"]`. Both the console and the chat log are empty, and `sessionStorage` `thread_id` has changed. Send 1 more, and exactly 1 card appears.
- Typing `/clear` also empties the console.
- API level: after 2 turns, `GET /api/devlog` (no parameter) still replays their events, and `GET /api/devlog?replay=0` delivers none of them, then delivers a new turn's events.

**Existing tests.** `test_feat3_console_ui.py::test_reloading_page_restores_recent_cards_from_ring_buffer` asserts the old behaviour this plan deliberately reverses. **This task may edit that one test** so it asserts the new behaviour (reload → empty console), and should rename it to match. Change nothing else in existing tests.

## Test command (keep it fast)
Use this exact command as the task's integration test command. It deliberately avoids the slow nested full-suite tests:
`uv run pytest tests/integration/test_feat7_console_clear.py tests/integration/test_feat3_console_ui.py -q`

## Accept when
The tests above pass, all tests in `test_feat3_console_ui.py` pass (with the one reversed test updated), and the chat works as before.

## Out of scope
Server `/stats` reset, any other console features, and changes to Jev's logic.
