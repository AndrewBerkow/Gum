# Gum: Jev-gated, Jev-routed chat harness

See `PLAN.md` for the full architecture, task list and design decisions.

## Setup

```
uv sync
uv run playwright install chromium
```

Then run the tests: `uv run pytest` (see "Test tiers" below).

## Offline demo

No API keys needed. Jev is replaced by a heuristic stub and the chat models by an offline echo:

```
JEV_BACKEND=stub CHAT_PROVIDER=fake uv run uvicorn app.main:app
```

Open `http://127.0.0.1:8000/`. The terminal-style UI shows an OFFLINE banner, streams
guardrail/route/token/done events over SSE, and blocks obvious prompt injections.

## Live mode

Put real keys in a gitignored `.env` file at the repo root, not in exported shell variables:

```
cp .env.example .env && chmod 600 .env
```

Then edit `.env` to set `TYPESAFE_API_KEY` and `GOOGLE_API_KEY`. With that `.env` in place,
`app.main.app` builds the real Jev classifier and real Gemini chat models:

```
uv run uvicorn app.main:app
```

- `TYPESAFE_API_KEY` — Jev / TypeSafe, from https://console.typesafe.ai/. Required whenever
  `JEV_BACKEND=live` (the default). Missing or placeholder-looking keys (containing `xxxx`) raise
  `ConfigError` naming `TYPESAFE_API_KEY` instead of silently falling back to the stub.
- `GOOGLE_API_KEY` (or `GEMINI_API_KEY` as a fallback) — Google Gemini, from
  https://aistudio.google.com/apikey. Required whenever `CHAT_PROVIDER=google_genai` (the
  default), and for `evals/run_eval.py --judge`.

**Exported shell variables aren't read by the tests.** `tests/conftest.py` sets `GUM_ENV_FILE=""`
for the whole offline suite, so `Settings()` never reads any `.env` file while testing (a real key
you merely `export`ed would still leak into `Settings()` via `os.environ`, which is exactly what
that isolation is guarding against). The `live`-marked tier is the one exception: it defaults
`GUM_ENV_FILE` back to the repo-root `.env` so `uv run pytest -m live` "just works" once you've
`cp .env.example .env`'d a real one.

`GUM_ENV_FILE` — the path `Settings()` reads as its env file; defaults to `.env`. Set it to `""` to
read no env file at all, or to another path to use a different one. `evals/run_eval.py --backend
live` honours it the same way the app does; `--backend stub` always ignores it, so stub reports
stay deterministic.

See `.env.example` for the full list of settings (thresholds, model ids, timeouts).

## Test tiers

| Tier | Marker | What it covers | Needs keys? |
|---|---|---|---|
| Unit | (none) | Pure logic: decision policy, wire building, config, the eval's metric functions | No |
| Integration | (none) | The FastAPI app, SSE contract, the eval CLI end to end, repo hygiene | No |
| e2e | `e2e` | A real browser (Playwright) driving the offline UI end to end | No |
| Live | `live` | The real Jev and Gemini APIs | Yes — skips cleanly otherwise |

Run them with `uv run pytest` (unit + integration; `e2e` and `live` are excluded by default via
`addopts`), `uv run pytest -m e2e`, or `uv run pytest -m live`. Without real keys, `-m live`
reports only skips, each naming the missing variable.

## Architecture

```
Browser (static/index.html)
   │  POST /api/chat {thread_id, message, tier?}   ◄── SSE: guardrail → route? → token* → done
   ▼
FastAPI (app/main.py) ── serves static/, streams SSE, appends to logs/decisions.jsonl
   ▼
LangGraph StateGraph (app/graph.py)
   START → jev_gate ──┬──► chat_lite  (gemini-3.5-flash-lite) → END
                       ├──► chat_flash (gemini-3.8-flash)      → END
                       └──► END   (blocked / error: canned AIMessage appended)
             │
             ▼
   app/jev.py: TypeSafeClassifier.ainvoke — ONE call, THREE questions
               {unsafe: Noul, scope: Choice, complexity: Choice}
```

One Jev call per turn answers safety, scope and complexity together. A blocked or erroring turn
never reaches the LLM. A passing turn is routed to the cheap model (`gemini-3.5-flash-lite`) when
Jev is confident it's simple, otherwise to the stronger one (`gemini-3.8-flash`). See PLAN.md §1
for the full policy (thresholds, the ambiguous-scope zone, fail-closed behavior, manual overrides).

## Live Jev demo

Run the app with a real `.env` in place (see "Live mode" above):

```
uv run uvicorn app.main:app --port 8000
```

Or run it entirely offline, no keys needed:

```
JEV_BACKEND=stub CHAT_PROVIDER=fake uv run uvicorn app.main:app --port 8000
```

## Reading the eval report

`uv run python evals/run_eval.py --backend stub` (or `--backend live`, once keys exist) writes a
dated Markdown report to `evals/reports/` with these sections:

- **Gate metrics** — unsafe recall/precision, the benign false-block rate, and the noise/
  out-of-scope catch rate.
- **Route metrics** — routing accuracy, the confusion matrix, the complex→lite misroute rate (the
  key risk metric), the simple→flash rate (money left on the table), and the lite share.
- **Threshold sweep** — for each candidate `ROUTE_LITE_THRESHOLD`, the lite share, the
  complex→lite misroute rate and the estimated cost savings, plus the lowest threshold that meets
  the misroute target.
- **Latency (Jev)** — p50, p95 and max, measured against the ~40ms target.
- **Lite-adequacy judge** (only with `--judge`) — the fraction of lite-routed items whose lite
  answer a blind pairwise Gemini judge rated as good as flash's, plus the ids that failed.

A raw-results `.jsonl` sits next to the report with one record per dataset item.

## Adding a question or a third tier

- **A new eval question:** append a line to `evals/routing_dataset.jsonl` —
  `{"id", "text", "context"?, "expect_gate", "expect_tier"?, "notes"}`. Keep ids unique; a
  `pass`-gate item needs `expect_tier`, every other gate must not have one.
- **A third tier:** add its model id to `Settings` (`app/config.py`), add a case to
  `build_chat_models` (`app/providers.py`), add a graph node and routing edge
  (`app/graph.py`), and extend the `Tier` literal in `app/state.py`. The route metrics in
  `evals/run_eval.py` currently assume two tiers (`simple`→lite, `complex`→flash); a third tier
  needs its own expected-route mapping there too.

## Spike: httpx2 offline transport

Checked on `httpx2` as installed by `langchain-typesafe==0.0.1a3`: `httpx2.MockTransport` exists and
`httpx2.AsyncClient(transport=httpx2.MockTransport(handler))` works, so no custom `AsyncBaseTransport`
subclass is needed. Offline tests inject that client via `TypeSafeClassifier(async_client=...)`.

## Run T13 manually once keys exist

T13 (PLAN.md) is implemented but never run by the automated workflow — it's the one task that
needs real keys. Once `TYPESAFE_API_KEY` and `GOOGLE_API_KEY` are set:

- [ ] `uv run pytest -m live -q` — confirm every live test now runs (not skips) and passes.
- [ ] Confirm the recorded fixtures under `tests/fixtures/recorded/*.json` look sane, then update
      T5a to replay them instead of the hand-written §0 JSON.
- [ ] Fill in real prices in `MODEL_PRICES` from Google's Gemini API pricing page, and note the
      date checked here.
- [ ] `uv run python evals/run_eval.py --backend live --threshold-sweep 0.5:0.95:0.05`, then again
      with `--judge`, and commit the resulting report.
- [ ] Set `ROUTE_LITE_THRESHOLD` to the sweep's recommended value.
- [ ] Record the Jev p50/p95 latency against the ~40ms target.
- [ ] Resolve the `TODO(T13-verify)` comments in `app/` against what the live run actually showed.
