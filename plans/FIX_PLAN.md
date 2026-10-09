# Fix Plan: gaps left by the first tdd-execute run

The first automated run (branch `tdd-plan`) finished all five tasks: 361 tests pass. Three gaps against `PLAN.md` remain. This plan fixes exactly those three. `PLAN.md` is still the source of truth for architecture, the §0 dependency facts, and the "NO REAL API KEYS" implementation rules. Read it before starting.

**No real API keys exist, and none are needed.** Every task below is completable and verifiable offline. Task 3 writes code that *uses* keys, but its tests check that the code skips or errors cleanly without them, or they run it against mocks. Do not defer any task for missing keys.

**Test file naming:** tests `t1`–`t5` already exist in `tests/integration/`. Name the new top-level integration tests `tests/integration/test_fix1_*.py`, `test_fix2_*.py` and `test_fix3_*.py` so they don't collide with the existing ones.

**Global acceptance (every task):** the existing suite stays green (`uv run pytest -q`), and `git status --porcelain` is empty after a full test run.

---

## Fix 1: Runnable app entry point

**Problem.** PLAN.md's definition of done says `JEV_BACKEND=stub CHAT_PROVIDER=fake uv run uvicorn app.main:app` serves a working UI. That command fails with `Attribute "app" not found in module "app.main"`: `app/main.py` defines only `create_app()`, and the tests call it directly, so nothing caught the gap.

**Build.**
- Expose a module-level ASGI app in `app/main.py` so that `uvicorn app.main:app` works.
- `create_app()` builds real providers and raises `ConfigError` when a live backend has no real key. **Importing `app.main` must therefore not raise and must not build providers** in environments without keys, including the test suite. Build the app lazily: either on first use, or by having the module-level `app` resolve `create_app()` at server startup. Keep `create_app()`'s current signature and behavior unchanged, since the existing tests depend on it.
- With `JEV_BACKEND=live` and no real key, starting the server must fail loudly with the existing `ConfigError` message naming the missing variable. It must **never fall back to the stub**.

**Tests first (`tests/integration/test_fix1_entrypoint.py`).**
- `import app.main` succeeds with no key variables set, and `app.main.app` exists.
- Under `JEV_BACKEND=stub CHAT_PROVIDER=fake`, the module-level app, driven through the ASGI test client or a real uvicorn on localhost:
  - serves `GET /` with 200 and the terminal UI HTML;
  - streams SSE from `POST /api/chat` for a benign message, with `guardrail` (passed), `route`, `token`… and `done`;
  - blocks an injection message: `guardrail` (blocked), the canned rejection, then `done`.
- A subprocess run of `uvicorn app.main:app` on a free localhost port answers `GET /` with 200 (terminate it after the check).
- Under `JEV_BACKEND=live` with no key, using the module-level app raises or exits with `ConfigError` mentioning `TYPESAFE_API_KEY`.

**Accept when:** all of the above pass, and the exact PLAN.md command `JEV_BACKEND=stub CHAT_PROVIDER=fake uv run uvicorn app.main:app` works.

---

## Fix 2: Tests must not write into the repository

**Problem.** After every full test run, `evals/reports/routing-eval-<date>.jsonl` is left untracked in the working tree. The cause is `tests/integration/test_t5_frontend_e2e.py` around line 386: it runs `evals/run_eval.py` as a subprocess **without `--out`**, so the eval writes into the real `evals/reports/`. `.gitignore` covers `evals/reports/*.md` but not `*.jsonl`.

**Build.**
- Change that test so the eval writes to pytest's `tmp_path` (pass `--out`). Keep its assertion that the eval produces output. **This task is explicitly allowed to edit `test_t5_frontend_e2e.py`, for this change only.**
- Add `evals/reports/*.jsonl` to `.gitignore` next to the existing `*.md` rule, since real manual eval runs produce both files.
- Delete the stray `evals/reports/routing-eval-*.jsonl` and `.md` files from the working tree. Keep `evals/reports/.gitkeep`.
- Check the rest of the suite for other tests that write under the repo (logs, decision logs, reports) and point them at `tmp_path` too.
- **Guard against recursive suite runs.** `test_t5_frontend_e2e.py::test_full_not_live_suite_green_with_no_env_file` already runs the whole suite in a subprocess, and the new Fix 2 test does too. Without a guard, each would launch the other recursively. Every test that spawns the full suite must set `GUM_NESTED_SUITE=1` in the child's environment, and must skip itself when `GUM_NESTED_SUITE` is already set. This task may edit that t5 test to add the guard.

**Tests first (`tests/integration/test_fix2_repo_hygiene.py`).**
- Run the full non-live suite in a subprocess, excluding this test file to avoid recursion, with `uv run pytest -q -p no:cacheprovider --ignore=<this file>`. Then assert that `git status --porcelain` lists no new untracked or modified files outside `.pytest_cache`. Compare the before and after snapshots, so pre-existing user changes don't cause a false failure.
- `git check-ignore evals/reports/x.jsonl` and `git check-ignore evals/reports/x.md` both succeed.

**Accept when:** a full `uv run pytest -q` leaves `git status` clean.

---

## Fix 3: T13 scaffolding (live tests that skip cleanly, live eval path, README)

**Problem.** PLAN.md rule 5 requires that T13 *is implemented but not run*. The first run deferred T13 entirely, so:
- `tests/live/test_live.py` does not exist, and `uv run pytest -m live` finds nothing.
- `evals/run_eval.py --backend live` exits with "runs in T13 and is not available yet".
- `README.md` is a stub.

The PLAN.md T13 section and rule 5 define the target. Implement everything there that doesn't need a real key. The steps that need real keys stay a **human step**: actually running the live suite, recording fixtures, filling in real prices, and running the vetting eval and committing its report.

**Build.**
- `tests/live/test_live.py` (marker `live`), with every T13 test from PLAN.md written for real:
  - Jev: real responses validate against the wire format; a benign prompt passes, an injection is blocked, and a simple prompt routes to lite; one scrubbed response per scenario is recorded to `tests/fixtures/recorded/`.
  - Gemini: `models.list` contains both configured ids; each tier streams at least 2 tokens with `usage_metadata`; an invalid key yields `error` then `done`.
  - Each test **skips unless `has_real_key(...)` is true** for the key it needs, and the skip reason names the missing variable (`TYPESAFE_API_KEY` or `GOOGLE_API_KEY`). The `live` marker must re-enable sockets for these tests, as PLAN.md rule 3 requires.
- `evals/run_eval.py --backend live`: build the real `TypeSafeClassifier` via `app.providers.build_classifier` with `jev_backend="live"`. With no real key it must exit non-zero with the `ConfigError` message naming `TYPESAFE_API_KEY`, never silently use the stub.
- `--judge` (live only): implement the blind pairwise lite-vs-flash judge described in PLAN.md T11, with the order randomized. Without a real `GOOGLE_API_KEY` it must exit non-zero, naming the variable.
- Add `# TODO(T13-verify): ...` comments where PLAN.md rule 6 asks for them. At minimum: the response header that carries `request_id`, whether `gemini-3.8-flash` exists, and the empty `MODEL_PRICES`.
- `README.md`, per the T13 section: setup (`uv sync`, `uv run playwright install chromium`), the offline demo command (`JEV_BACKEND=stub CHAT_PROVIDER=fake uv run uvicorn app.main:app`), live mode and the keys it needs, the test tiers (unit / integration / e2e / live), the architecture, how to read the eval report, and how to add a question or a third tier. Keep the existing httpx2 spike note. Write "Run T13 manually once keys exist" as a checklist of the human steps.

**Tests first (`tests/integration/test_fix3_live_scaffold.py`).** All of these run offline, with key variables removed from the environment:
- `uv run pytest -m live -q` (as a subprocess, with the `-m 'not live'` addopts overridden) exits 0 and reports **only skips**: at least 6 skipped, 0 passed, 0 failed, 0 errors. Each skip reason names `TYPESAFE_API_KEY` or `GOOGLE_API_KEY`.
- `evals/run_eval.py --backend live` exits non-zero, with `TYPESAFE_API_KEY` in its output, and does **not** contain "not available yet".
- `evals/run_eval.py --backend live --judge` with a real-looking fake TypeSafe key and no Google key exits non-zero, naming `GOOGLE_API_KEY`. Construct only; don't invoke the network.
- With the real `TypeSafeClassifier` backed by an `httpx2.MockTransport` that serves §0-format responses, the live eval's classification path produces a report. Use a seam such as an injectable classifier or client factory to do this with no network.
- `README.md` contains the offline demo command, `playwright install chromium`, and a "live" section naming both key variables.
- `grep -rn "TODO(T13-verify)" app/` finds at least 3 comments.

**Accept when:** all of the above pass. `uv run pytest -q` stays green, and `uv run pytest -m live` reports only skips.

---

## Out of scope (don't do these)
- Running anything against the real TypeSafe or Gemini APIs, creating a `.env`, or recording real fixtures.
- Changing the threshold-sweep recommendation logic. It currently allows recommending a threshold with 0% lite share; that is a known issue for a later pass.
- Refactoring code that works. Touch only what these three fixes need.
