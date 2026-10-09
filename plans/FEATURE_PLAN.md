# Feature Plan: Live Jev Dev Console (split-panel demo)

**Goal:** show Jev working in real time. The browser page becomes a split view: the existing chat terminal on the **left**, and a live **Jev dev console** on the **right**. The console shows, for every message: the raw request Jev received, the probabilities it returned for each question, how the harness turned those numbers into a decision, and what happened next (which model, timings, blocked or error). The console is fed by a real server-side event stream, so it shows what the server actually did.

`PLAN.md` is still the source of truth for architecture, the §0 wire-format facts, and the "NO REAL API KEYS" rules. A real `.env` with keys now exists in the developer's checkout. **All tests must pass with and without it, and none may make real API calls.** Build and test everything against the stub (`JEV_BACKEND=stub CHAT_PROVIDER=fake`) and `httpx2.MockTransport`.

**Test file naming:** `tests/integration/test_feat1_*.py` through `test_feat4_*.py`.

**Global acceptance (every task):**
- `uv run pytest -q` is green with no `.env` and with a real-looking `.env` (see Task 4).
- `git status --porcelain` is unchanged after a full run.
- No key ever appears in any dev-log event, server log, or page. Tests must assert this.

Mockup:
```
┌─────────── chat ───────────┬──────── JEV DEV CONSOLE ────────┐
│ > what's the capital of…   │ 14:02:11 #7  POST /v1/systemone │
│ [JEV GUARDRAIL: PASSED]    │  unsafe      ▏0.04    │ 0.70    │
│ [JEV ROUTE: lite ← simple] │  scope valid ████████▌0.92      │
│ Paris.                     │  complexity simple ███▌0.88 ≥.70│
│                            │  → PASS → lite (gemini-3.5-fl…) │
│ > ignore all previous…     │  jev 38ms · ttft 210ms · 1.1s   │
│ [JEV GUARDRAIL: BLOCKED]   │ 14:02:30 #8  unsafe ██████▉0.97 │
│                            │  → BLOCKED (unsafe) · no LLM    │
└────────────────────────────┴─────────────────────────────────┘
```

---

## Task 1: Server-side dev-log stream (`/api/devlog`)

**Build.**
- A small in-process **dev-log bus** (e.g. `app/devlog.py`). It is an async publish/subscribe with a ring buffer of the last 200 events, so a console opened mid-demo gets recent history. It lives on the app instance (built in `create_app`), not as a module global, so tests stay isolated.
- `GET /api/devlog` returns an SSE stream: the buffered events first, then live ones. It is served **only to loopback clients** (127.0.0.1, ::1); any other client gets 403, because the stream contains message text. A setting `DEVLOG_ENABLED` (default `true`) turns it off entirely: the route returns 404, and nothing is published.
- **Event types**, each with `turn_id`, `seq`, ISO `ts` and `t_ms` (ms since the turn started):
  - `turn.start`: `thread_id`, `requested_tier`, the message text.
  - `jev.request`: the **exact JSON body** POSTed to `/v1/systemone` (`state`, `model`, `questions`), the URL and the method. Headers are included **with `Authorization` replaced by `Bearer ***`**.
  - `jev.response`: HTTP status, the raw response JSON, `request_id` if present, and latency in ms.
  - `jev.decision`: covered in Task 2.
  - `llm.start`: tier and model id. `llm.first_token`: time to first token. `llm.done`: token count and `usage_metadata`.
  - `turn.end`: outcome (`answered` | `blocked` | `error`), reason, and total ms.
  - `jev.error`: the exception type and message, with keys redacted, when the Jev call fails or times out (which blocks the turn).
- **Capture the raw HTTP through `httpx2` `event_hooks`** on the classifier's `AsyncClient` (a request hook and a response hook, reading the body). In `app/providers.py`:
  - **Live mode currently passes no `async_client`.** Give it an `httpx2.AsyncClient` with the hooks, preserving `timeout=settings.guardrail_timeout_s` and default behaviour.
  - Stub mode keeps its `MockTransport` and adds the same hooks.
  - Link HTTP events to the right turn with a `contextvars.ContextVar` holding the current `turn_id`, set around the `jev_gate` call.
- The dev-log must never break chat. Publishing is fire-and-forget: a slow or disconnected console never blocks or fails a turn, and a hook exception is caught and logged.

**Tests first (`tests/integration/test_feat1_devlog_stream.py`).**
- A stub chat turn, sent through the ASGI app, publishes events in order: `turn.start` → `jev.request` → `jev.response` → `jev.decision` → `llm.start` → `llm.first_token` → `llm.done` → `turn.end`, all with the same `turn_id`.
- A blocked turn (an injection prompt) has `jev.decision` with outcome blocked, then `turn.end` outcome `blocked`, and **no** `llm.*` events.
- A Jev failure (a mock transport returning 500, or a timeout) gives `jev.error`, then `turn.end` outcome `error`.
- `jev.request.body` equals the JSON the mock transport actually received, including all 3 question ids (`unsafe`, `scope`, `complexity`).
- **Redaction:** with a real-looking fake key (`ts_live_test1234567890abcdef`) configured, no published event and no log line contains the key. `Authorization` shows `Bearer ***`.
- `GET /api/devlog` from a non-loopback client gets 403. With `DEVLOG_ENABLED=false`, it gets 404 and nothing is published.
- A console that connects after 3 turns receives their buffered events first.
- A subscriber that never reads doesn't slow or fail chat turns (bounded queue, drop-oldest).

---

## Task 2: Explain each decision

**Build.** Emit a `jev.decision` event from the decision logic in `app/jev.py` (`evaluate`). Reuse its numbers; don't re-derive them in the UI. It carries:
- per question:
  - `unsafe`: `p`, threshold (`block_threshold`), comparison (`>`), verdict.
  - `scope`: the chosen label, every label's probability, the threshold, and verdict.
  - `complexity`: `p_simple`, `route_lite_threshold`, comparison (`≥`), and the resulting tier.
- Jev's `confidence` for each Choice question, labelled as *distribution concentration*, not the probability of the chosen label (see PLAN.md §0).
- the final outcome: `passed → lite|flash`, `blocked (unsafe|noise|out_of_scope)`, or `error`. With a `/model` override, it includes both Jev's tier and the tier actually used.
- a one-line explanation string, e.g. `p_unsafe 0.04 ≤ 0.70 · scope valid_request 0.92 · p_simple 0.88 ≥ 0.70 → lite`.

**Tests first (`tests/integration/test_feat2_decision_explained.py`).** Use hand-built `ClassifierResponse` fixtures in the §0 format:
- For a passing simple turn, a blocked-unsafe turn, a noise turn, a complex turn and an override turn, the fields and one-liner match the exact expected values.
- Values at exactly the threshold follow the same `>` / `≥` rules as `evaluate`. Test 0.70 for both thresholds.
- The decision event's outcome always agrees with the `guardrail` / `route` SSE events the chat UI receives for the same turn.

---

## Task 3: Split-panel dev console in the browser

**Build** (`static/index.html`; keep it one static file, no build step, no new dependencies):
- **Layout:** chat on the left, console on the right, with a draggable divider. Below 900px wide they stack, console underneath. `Ctrl+\` or a `/devlog` chat command toggles the console, and the choice persists in `localStorage`, wrapped in try/catch.
- The console connects to `/api/devlog` with `EventSource`, reconnecting automatically. It shows a status dot: live, reconnecting, or disabled.
- **One card per turn**, newest at the bottom, with pause-on-scroll-up auto-scroll like the chat. Each card shows:
  - a header: time, `#turn`, a message preview, and an outcome badge (green PASS→lite/flash, red BLOCKED(reason), amber ERROR).
  - **probability bars**, one per question, filled to `p`, with a **vertical threshold marker** and the number. `scope` shows all three labels as stacked mini-bars.
  - the explanation one-liner from Task 2.
  - a **timing strip**: Jev ms · ttft · total, plus the model id.
  - two collapsed `▸ request` / `▸ response` sections showing the raw pretty-printed JSON, with a copy button.
- **Style:** match the existing terminal look (monospace, dark). Every colour is a CSS variable. Text stays readable at 1280px wide on a projector.
- The chat panel must keep working exactly as today, and all existing e2e tests stay green.

**Tests first (`tests/integration/test_feat3_console_ui.py`, Playwright against a real uvicorn on localhost with stub/fake, like `test_t5_frontend_e2e.py`).**
- After sending a simple message, the console shows a card with 3 probability bars, a PASS→lite badge, and a threshold marker at the configured position.
- An injection prompt produces a BLOCKED(unsafe) card with no model or ttft in its timing strip.
- Expanding `▸ request` shows JSON containing `"questions"`, and the text `Bearer ***` never shows a key.
- The console card count equals the number of turns sent. Reloading the page restores recent cards from the ring buffer.
- `Ctrl+\` hides and shows the console. At 800px wide the panels stack.
- The chat's existing behaviour is unchanged: the existing e2e suite passes.

---

## Task 4: Demo docs + the conftest `.env` test fix

**Build.**
- **README "Live Jev demo" section:** the command (`uv run uvicorn app.main:app --port 8000` with a real `.env`, or `JEV_BACKEND=stub CHAT_PROVIDER=fake` offline), a 6-prompt demo script (simple, complex, injection, noise, `/model flash` override, `/stats`), what each console element means, and how to read `confidence` vs probability.
- **Fix the known failing test.** `tests/integration/test_fix4_dotenv_isolation.py::test_conftest_sets_gum_env_file_empty_string_at_import_time` asserts `GUM_ENV_FILE == ""`. But `tests/conftest.py` uses `os.environ.setdefault("GUM_ENV_FILE", "")`, and parents deliberately pass `GUM_ENV_FILE=<empty temp file>` to child suites. So with a real `.env` present, 3 nested-suite tests fail (`test_fix5_…without_dotenv…`, and 2 in `test_fix8_real_dotenv_present.py`). Make the assertion check the actual invariant: offline tests read **no keys**, meaning `GUM_ENV_FILE` is `""` or points to a file with no keys. Don't change the `setdefault` behaviour. This task may edit that test.

**Tests first (`tests/integration/test_feat4_demo_ready.py`).**
- With an unmarked real-looking `.env` present, created only if none exists, removed in `finally`, and never touching an existing `.env`, the full non-live suite in a subprocess gives 0 failures. Use `GUM_NESTED_SUITE=1` and `--ignore` for this file.
- The README contains the demo command, the 6 demo prompts, and a "confidence vs probability" explanation.

---

## Out of scope
- Real API calls in tests, or changes to Jev's questions, thresholds or routing behaviour.
- The `--judge` fixes (FIX_PLAN_2 Fix 6) and the threshold-sweep issue.
- Authentication for `/api/devlog` beyond loopback-only. It's a local demo tool.
