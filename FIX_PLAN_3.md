# Fix Plan 3: finish FIX_PLAN_2 — robust to a real `.env`, then judge correctness

`FIX_PLAN_2.md` was partly executed:
- **Fix 4 is done** (commits `8e589d1`…`27f1062`). `Settings` honours `GUM_ENV_FILE`, and `tests/conftest.py` sets it to `""`.
- **Fix 5 is implemented** (commits `e66f2b9`…`88af8e5`, plus the `test_fix3_live_scaffold.py` change that hides `.env` via an empty `GUM_ENV_FILE`). One of its tests is wrong, though; see Fix 8.
- **Fix 6 (judge correctness) was not started.** It is Fix 9 below, unchanged.

Read `FIX_PLAN_2.md` for background. `PLAN.md` is still the source of truth for architecture and the "NO REAL API KEYS" rules. Rule 4 says **the suite must behave the same after a human adds real keys.**

**No real keys exist in this environment, and none are needed.** Everything here is offline.

**Test file naming:** `tests/integration/test_fix7_*.py`, `test_fix8_*.py`, `test_fix9_*.py`.

**Global acceptance (every task):**
- `uv run pytest -q` is green with **no `.env`**, and also with **a real-looking `.env` in the repo root that the tests didn't create** (simulated as described in Fix 8).
- `git status --porcelain` is unchanged after a full run.
- Tests that run the full suite in a subprocess follow the existing `GUM_NESTED_SUITE` guard.

---

## Fix 7: A fake `.env` created by a test must never outlive the test run

**Problem.** Tests that need a repo-root `.env` create one with fake keys and remove it in a `finally`. When the test process is killed first (a node timeout, an agent's tool timeout, or `_run_pytest_bounded` killing a process group), the fake `.env` stays behind. That has happened twice. A leftover fake `.env` breaks later runs, and it looks like a user's real one, so nothing dares delete it.

**Build.**
- Put one shared helper in the tests (e.g. `tests/fake_dotenv.py`) that is the **only** way tests create a repo-root `.env`. It writes a first line `# GUM-TEST-FAKE-ENV: created by the test suite; safe to delete` and then the fake keys. It creates the file only if no `.env` exists, and removes it in `finally`. Move every existing repo-root `.env` writer to this helper; today that's `test_fix4_dotenv_isolation.py`, and search for others.
- **Self-healing.** When a top-level pytest session starts (a `pytest_sessionstart` hook in `tests/conftest.py`, not in nested runs where `GUM_NESTED_SUITE` is set), delete the repo-root `.env` **only if its first line is exactly that marker**. Never touch a `.env` without the marker.
- Prefer temporary env files through `GUM_ENV_FILE` over repo-root files wherever a test doesn't specifically need the default `.env` path.

**Tests first (`tests/integration/test_fix7_fake_dotenv_self_heals.py`).** Run everything in a temporary copy or through the helper's API; never delete an unmarked real `.env`:
- A repo-root `.env` whose first line is the marker is gone after a fresh top-level `pytest` session starts. Run a trivial selection in a subprocess, e.g. `-k` on a quick test, without `GUM_NESTED_SUITE`.
- A `.env` without the marker is **untouched** by the same session start: same bytes, same mtime. If a real `.env` already exists, run this against a temporary directory by making the hook's target path injectable, rather than swapping out the user's file.
- The helper writes the marker as the first line, refuses to overwrite an existing `.env`, and removes only a file it created.
- A process killed with SIGKILL while holding the helper's fake `.env` leaves a marked file, and the next session start removes it.

**Accept when:** all of the above pass, and `grep -rn '\.env' tests/` shows no repo-root `.env` writers other than the helper.

---

## Fix 8: No test may require the absence of a real `.env`

**Problem.** `tests/integration/test_fix5_live_reads_dotenv.py::test_full_not_live_suite_without_dotenv_is_green_and_leaves_git_status_unchanged` starts with `assert not (ROOT / ".env").exists()`. It fails the moment the user adds real keys, which violates PLAN.md rule 4 and FIX_PLAN_2's global acceptance.

**Build.**
- Change that test so it never fails because a real `.env` exists. Where it needs "no env file", hide `.env` from its subprocess with `GUM_ENV_FILE` pointing at an empty temporary file, as `test_fix3_live_scaffold.py` now does. **This task may edit that test** for this purpose only, and must keep what it checks: the suite is green and `git status` is unchanged.
- Audit every test for other assumptions that no `.env` exists (`.exists()` checks, skips, or reading the default path) and fix them the same way.

**Tests first (`tests/integration/test_fix8_real_dotenv_present.py`).**
- **Simulate a user's real `.env`.** Create a repo-root `.env` with real-looking fake keys through the Fix 7 helper. It carries the marker, which is only a comment, so the code under test sees it as a normal `.env`. Then run the full non-live suite in a subprocess with `GUM_NESTED_SUITE=1`, so the child neither heals the file nor recurses, and with `--ignore` for this file. Assert 0 failures, and assert that the child's output doesn't contain "expects no real .env".
- `grep` finds no `assert not (ROOT / ".env").exists()` (or an equivalent absence assertion) left in `tests/`.

**Accept when:** all of the above pass. The whole suite is green with and without a repo-root `.env`.

---

## Fix 9: The `--judge` verdicts must measure the right thing

This is **exactly Fix 6 in `FIX_PLAN_2.md`**. Implement it as written there: the order-flip fix, the blindness requirement, robust `yes`/`no` parsing with a separate `unparseable` count left out of the rate, and the exact tests listed there. Name its integration tests `tests/integration/test_fix9_judge_correctness.py`.

---

## Out of scope (don't do these)
- Running anything against the real TypeSafe or Gemini APIs, or creating a real `.env`.
- The threshold-sweep issue where a threshold with 0% lite share can be recommended.
- Reworking Fix 4 or Fix 5 beyond what Fixes 7 and 8 require.
