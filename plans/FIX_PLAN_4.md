# Fix Plan 4: make the suite green with and without a real `.env`

**One small task. Don't split it.** The `.env` wiring itself is done: `GUM_ENV_FILE` (Fix 4), the live paths reading `.env` (Fix 5), the self-healing fake-`.env` helper `tests/fake_dotenv.py` (Fix 7), and the removal of the "no .env allowed" assertions (commits `fe08b3d`, `635b847`). Two test-only bugs keep the suite from passing. **Don't change app code**; only the tests below need changes. Don't weaken what any test checks.

The user is about to add a real, unmarked `.env` with real keys. No real keys exist in this environment. To simulate the user's file, use an **unmarked** real-looking `.env`, e.g. `TYPESAFE_API_KEY=ts_live_simreal1234567890abcd` and `GOOGLE_API_KEY=AIzaSIMREAL1234567890abcdefghijklmnop`. Only ever create one if none exists, and always remove it in `finally`. If an unmarked `.env` already exists, **never modify or delete it**. The integration tests must not leave any `.env` behind.

## Bug 1: Fix 7 tests fail inside nested suite runs (cascades into 8 failures)

`tests/integration/test_fix7_fake_dotenv_self_heals.py` has three tests that start `pytest` subprocesses expecting the session-start self-heal to run:
- `test_marked_repo_root_dotenv_is_removed_by_a_fresh_top_level_session_start`
- `test_sigkilled_process_leaves_marked_file_and_next_session_start_removes_it`
- `test_self_heal_only_runs_outside_nested_suites` (its "heal runs" half)

They pass at top level, but they inherit `GUM_NESTED_SUITE=1` when they run inside a full-suite subprocess. There the heal is deliberately off, so they fail. That breaks every test that runs the full suite: `test_fix2_repo_hygiene`, `test_fix4_dotenv_isolation`, `test_fix5_live_reads_dotenv` (2), `test_fix8_real_dotenv_present` (2) and `test_t5_frontend_e2e`.

**Fix:** those subprocesses must build their child environment explicitly, with `GUM_NESTED_SUITE` **removed** where the heal is expected to run and **set** where it's expected not to. They must not depend on the ambient value.

Reproduce: `GUM_NESTED_SUITE=1 uv run pytest tests/integration/test_fix7_fake_dotenv_self_heals.py -q` gives 3 failures today and must give 0.

## Bug 2: A real `.env` makes the helper raise `FileExistsError`

With an unmarked `.env` in the repo root, these fail with `FileExistsError: refusing to overwrite an existing .env`:
- `tests/integration/test_fix4_dotenv_isolation.py::test_fix4_listed_regression_tests_pass_with_fake_dotenv_present`
- `tests/integration/test_fix5_live_reads_dotenv.py::test_live_tier_reads_repo_root_dotenv_by_default_and_attempts_jev_gated_tests`
- `tests/integration/test_fix5_live_reads_dotenv.py::test_live_marker_suite_with_empty_gum_env_file_only_skips_even_with_repo_root_dotenv`

The helper refusing to overwrite is correct; keep that. The tests must handle an existing `.env` instead of crashing:
- **"with a `.env` present" checks:** when a `.env` already exists, use it as-is. It satisfies "a `.env` is present". Create a fake only when none exists.
- **The live-tier check that expects the key-gated tests to be *attempted*:** it must not fire real API calls with the user's keys, and it must not fail because of them. Prefer pointing `GUM_ENV_FILE` at a temporary file with fake keys, which tests the same opt-in path without the repo root. If the test really needs the default repo-root path and a real `.env` exists, skip with a clear reason rather than using real keys.
- Look for any other test that uses the helper and apply the same rule.

## Tests first (`tests/integration/test_fix10_suite_green_both_ways.py`)
- `GUM_NESTED_SUITE=1 pytest tests/integration/test_fix7_fake_dotenv_self_heals.py` in a subprocess gives 0 failures.
- **With no `.env`:** the full non-live suite in a subprocess (with `GUM_NESTED_SUITE=1` and `--ignore` for this file) gives 0 failures.
- **With an unmarked real-looking `.env`:** create it only if none exists, and remove it in `finally`. The same full-suite subprocess gives 0 failures, and afterwards the `.env` is byte-for-byte unchanged.
- After the test, `.env` is back to its starting state (absent, or the user's untouched file), and `git status --porcelain` is unchanged.

## Accept when
The tests above pass. A plain top-level `uv run pytest -q` is green **with no `.env`** and **with an unmarked real-looking `.env`**, and no fake `.env` is left behind.

## Out of scope
App code, the judge fixes (FIX_PLAN_2 Fix 6), the threshold sweep, and any real API calls.
