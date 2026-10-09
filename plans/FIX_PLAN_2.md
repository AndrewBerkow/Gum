# Fix Plan 2: real keys via `.env` + judge correctness

The user is about to add real keys in a gitignored `.env` in the repo root: `TYPESAFE_API_KEY`, `GOOGLE_API_KEY`, and optionally `LANGCHAIN_API_KEY`. Testing with a temporary `.env` holding fake but real-looking keys (`ts_live_test1234567890abcdef`, `AIzaTEST1234567890abcdefghijklmnopqrs`) exposed the three problems below. `PLAN.md` is still the source of truth for architecture, the §0 facts and the "NO REAL API KEYS" rules. Rule 4 says the suite must behave the same after a human adds real keys, and that is currently false.

**No real keys exist in this environment, and none are needed.** Every task is verifiable offline. Use fake but real-looking keys where a test needs a `.env`.

**Never create, overwrite or delete a real `.env`.** A test that needs one must create a temporary `.env` in the repo root **only if none exists**, and remove it in a `finally`. If a `.env` already exists, use it as-is and never modify it. Better still, point the code at a temporary env file through the override described in Fix 1, so no test touches the repo root at all.

**Test file naming:** name the new top-level integration tests `tests/integration/test_fix4_*.py`, `test_fix5_*.py` and `test_fix6_*.py`.

**Global acceptance (every task):**
- `uv run pytest -q` is green **both with no `.env` and with a fake `.env` in the repo root**.
- `git status --porcelain` is unchanged after a full run.
- Any test that runs the full suite in a subprocess follows the existing `GUM_NESTED_SUITE` guard: it sets the variable in the child, and skips itself when the variable is already set.

---

## Fix 4: Offline tests must never read the developer's `.env`

**Problem.** `Settings` uses `SettingsConfigDict(env_file=".env")`. `tests/conftest.py` deletes key variables from the environment, but it doesn't stop pydantic-settings from reading `.env` files. With a fake `.env` present, **12 offline tests fail**:
- `tests/integration/test_fix1_entrypoint.py::test_subprocess_uvicorn_live_backend_without_key_fails_loudly_naming_typesafe_key`: the uvicorn subprocess reads `.env`, so it doesn't fail.
- `tests/unit/test_live_scaffold.py`, 8 cases: `Settings()` sees keys, so the live tests no longer skip.
- `tests/integration/test_fix3_live_scaffold.py::test_marker_live_suite_with_no_keys_reports_only_skips_naming_missing_keys`
- `tests/integration/test_fix2_repo_hygiene.py::test_full_suite_subprocess_stays_green_and_leaves_no_new_git_changes` and `tests/integration/test_t5_frontend_e2e.py::test_full_not_live_suite_green_with_no_env_file`: both run nested suites, which inherit the same failures.

**Build.**
- Make the env file configurable: `Settings` reads the path from an environment variable `GUM_ENV_FILE`. It defaults to `.env`, so the app's behaviour for users doesn't change. An empty value means "read no env file".
- In `tests/conftest.py`, set `GUM_ENV_FILE=""` in `os.environ` at import time, the way `NO_COLOR` is already set there. This happens before any `Settings` is built, and subprocesses the tests spawn (uvicorn, nested pytest, the eval CLI) inherit it. Offline tests then never see a `.env`, however they construct `Settings`.
- Keep the existing autouse fixture that clears key variables.
- Don't change `create_app()`'s signature. Don't weaken any existing assertion; the failing tests above must pass unchanged. You may edit an existing test only where it has to opt into reading an env file on purpose.

**Tests first (`tests/integration/test_fix4_dotenv_isolation.py`).**
- With a fake `.env` present, following the no-overwrite rule above, a full non-live suite run in a subprocess passes with 0 failures. Pass `--ignore` for this file and follow the nesting guard.
- With `GUM_ENV_FILE` pointing at a temporary file that holds a fake key, `Settings()` reads that key. With `GUM_ENV_FILE=""`, `Settings()` reads no file.
- With `GUM_ENV_FILE` unset, `Settings()` in a subprocess whose cwd holds a `.env` still reads it, so the default behaviour for users is unchanged. Use a temporary directory as the cwd, not the repo root.

**Accept when:** all of the above pass, and the 12 tests listed fail neither with nor without a fake `.env`.

---

## Fix 5: The live code paths must read keys from `.env`

**Problem.** The `.env` file is the user's only key source. The conftest wipes environment variables, so exported shell keys never reach the tests. But:
- `evals/run_eval.py` builds `Settings(_env_file=None, jev_backend="live", ...)`, so **`--backend live` never reads `.env`** and always reports `TYPESAFE_API_KEY` as missing. The same is true for `--judge` and `GOOGLE_API_KEY`.
- After Fix 4, the offline test run sets `GUM_ENV_FILE=""`, so `tests/live/test_live.py` would never see keys either, even when the user runs `uv run pytest -m live` on purpose.

**Build.**
- `run_eval.py --backend live` (with or without `--judge`) reads keys the way the app does, honouring `GUM_ENV_FILE` with the default `.env`. `--backend stub` keeps ignoring env files (`_env_file=None`) so stub reports stay deterministic.
- Live tests read the real `.env` when the user runs the live tier. Put the opt-in in `tests/live/` (for example, its own conftest or fixture) so `-m live` runs load `.env`: the path in `GUM_ENV_FILE` if the user set it deliberately, otherwise the repo-root `.env`. It must still skip cleanly, naming the variable, when a key is missing or a placeholder. The live tier must not change how the offline tests behave.
- `test_fix3_live_scaffold.py`'s "no keys → only skips" check must keep passing when a real `.env` exists. Hide the `.env` from that subprocess explicitly, e.g. by pointing `GUM_ENV_FILE` at an empty temporary file.

**Tests first (`tests/integration/test_fix5_live_reads_dotenv.py`).** All offline; no network:
- `run_eval.py --backend live` with `GUM_ENV_FILE` pointing at a temporary env file with a fake TypeSafe key gets **past** the missing-key check. Prove this through the existing seam (the real `TypeSafeClassifier` backed by an `httpx2.MockTransport` serving §0-format responses), or by asserting that the missing-key error doesn't appear. It must never touch the network.
- `run_eval.py --backend live` with `GUM_ENV_FILE` pointing at an empty temporary file still exits non-zero, naming `TYPESAFE_API_KEY`.
- `run_eval.py --backend live --judge` with a temporary env file holding only a fake TypeSafe key exits non-zero, naming `GOOGLE_API_KEY`.
- The live tier, run in a subprocess with `GUM_ENV_FILE` pointing at a temporary env file holding fake real-looking keys and sockets still disabled, **does not skip** the key-gated tests. It attempts them, and they error or fail on the blocked network. Assert "not skipped", not "passed". This proves the opt-in works.
- `uv run pytest -m live` with an empty env file reports only skips, as before.

**Accept when:** all of the above pass. The README's live-mode section says keys go in `.env` (`cp .env.example .env && chmod 600 .env`), explains why exported shell variables aren't read by the tests, and documents `GUM_ENV_FILE`.

---

## Fix 6: The `--judge` verdicts must measure the right thing

**Problem** (in `evals/run_eval.py`):
- **Order-flip bug.** `render_judge_prompt` always asks "is Answer A as good as Answer B?". `run_judge` randomly puts the flash answer in slot A (when `lite_first(rng)` is False), but still counts "yes" as *lite* being adequate. About half the verdicts measure the wrong thing. The unit tests only assert totals, so they don't catch it.
- **Parsing fails closed too eagerly.** `parse_judge_verdict` does `text.strip().lower().startswith("yes")`, so `**Yes**`, `"Yes."` or `Yes — …` count as "no", which undercounts adequacy on real Gemini output.

**Build.**
- The judge must always ask whether **the lite answer** is as good as the flash answer, whichever slot lite is in. Either phrase the question about the slot that holds lite ("is Answer B as good as Answer A?" when lite is B), or keep one question and invert the verdict. The judge must stay blind: the prompt must never say which answer is lite or flash.
- Parse verdicts robustly. Strip whitespace, surrounding quotes, markdown emphasis (`*`, `_`, backticks) and trailing punctuation, then take the first word: `yes` → adequate, `no` → not adequate. Anything else is **unparseable**. Count unparseable verdicts separately (`unparseable` count and ids in the judge result and the report), don't count them as adequate, and leave them out of the adequacy rate's denominator. Document that choice in the report.
- Keep the judge result's existing keys (`n`, `lite_adequacy_rate`, `failures`), and add `unparseable`.

**Tests first (`tests/integration/test_fix6_judge_correctness.py`).** Use fake chat models with a deterministic `rng`:
- **Order-flip test.** Build a fake judge that answers from content. For example, it says "yes" exactly when the answer in the slot the question asks about contains `LITE-GOOD`. Where lite is clearly good, adequacy is 100% whether `lite_first` is True or False. Where lite is clearly bad, adequacy is 0% in both orderings. Run both orderings explicitly, e.g. with a seeded rng or by patching `lite_first`.
- **Blindness test.** No judge prompt contains the words `lite`, `flash`, or either configured model id.
- **Parser tests.** `**Yes**`, `"Yes."`, `yes`, and `Yes — it covers…` → adequate. `No.` and `**no**` → not adequate. `Maybe`, empty and `I think both are fine` → unparseable, and the rate excludes them.
- **End-to-end.** `run_judge` with the fakes returns `n`, `lite_adequacy_rate`, `failures` and `unparseable`, with exact values for a small hand-built set.

**Accept when:** all of the above pass, and the existing judge unit tests still pass. Only adjust an existing test where it asserted the buggy behaviour, and say so in the commit message.

---

## Out of scope (don't do these)
- Running anything against the real TypeSafe or Gemini APIs, or creating a real `.env`.
- The threshold-sweep issue where a threshold with 0% lite share can be recommended. That is a known issue for a later pass.
- Refactoring code that works. Touch only what these three fixes need.
