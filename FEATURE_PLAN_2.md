# Feature Plan 2: finish the Live Jev Dev Console

`FEATURE_PLAN.md` was partly executed (tdd-execute run `b53e5e64`):
- **Task 1 (the `/api/devlog` stream) and Task 2 (`jev.decision` explanations) are done.**
- **Task 3 (the split-panel console in `static/index.html`) is implemented** (commits `eee03ea`, `ba6f6dd`, `116886c`, `9f9d968`), but its top-level test file has a bug, so it was never validated.
- **Task 4 (README demo section + the conftest `.env` test fix) was not started.**

Read `FEATURE_PLAN.md` for the full spec. `PLAN.md` is still the source of truth for architecture and the "NO REAL API KEYS" rules. A real `.env` with keys exists in the developer's checkout. Tests must pass with and without it and make no real API calls.

**Test file naming:** `tests/integration/test_feat5_*.py`, `test_feat6_*.py`.

---

## Task A: Fix the console test helper and validate Task 3

**Problem.** `tests/integration/test_feat3_console_ui.py:83-85`:
```python
def wait_for_cards(page, n):
    page.wait_for_function(
        "(n) => document.querySelectorAll('[data-testid=\"devlog-card\"]').length >= n", n
    )
```
In the Python Playwright API (`playwright==1.63.0`), `Page.wait_for_function(expression, *, arg=None, ...)` takes `arg` **by keyword only**. So 9 tests fail with `TypeError: Page.wait_for_function() takes 2 positional arguments but 3 were given` before they touch the page. This also fails `test_t5_frontend_e2e.py::test_full_not_live_suite_green_with_no_env_file`, which runs the whole suite. Run `b53e5e64`'s diagnosis (`t3/diagnosis.md`) confirmed that changing `n` to `arg=n` makes all 12 console tests pass.

**Build.**
- **This task may edit `test_feat3_console_ui.py`**, for this fix only: pass `arg=n`. Also look for any other positional `arg` use of `wait_for_function` / `evaluate`-style calls in the tests and correct those. Don't weaken or remove any assertion.
- If any console test still fails after that, fix `static/index.html` (the implementation), not the test.

**Tests first (`tests/integration/test_feat5_console_validated.py`).**
- A subprocess run of `pytest tests/integration/test_feat3_console_ui.py -q` gives 0 failures and at least 12 passed. It uses a real uvicorn on localhost with stub/fake backends, like the existing file.
- `grep` finds no `wait_for_function(` call in `tests/` that passes its argument positionally.

**Accept when:** both pass, and `test_t5_frontend_e2e.py` is green.

---

## Task B: `FEATURE_PLAN.md` Task 4 (README demo section + conftest `.env` test fix)

Implement **Task 4 exactly as written in `FEATURE_PLAN.md`**:
- The README "Live Jev demo" section: the command, the 6-prompt demo script, what each console element means, and confidence vs probability.
- The fix for `test_fix4_dotenv_isolation.py::test_conftest_sets_gum_env_file_empty_string_at_import_time`. It should assert the real invariant (offline tests read no keys) rather than `GUM_ENV_FILE == ""`, keeping `setdefault` unchanged.

Write the top-level tests as described there, in `tests/integration/test_feat6_demo_ready.py`. In particular: with an unmarked real-looking `.env` present (created only if none exists, removed in `finally`, never touching an existing `.env`), the full non-live suite gives 0 failures.

**Accept when:** those tests pass, and a plain `uv run pytest -q` is green with no `.env` and with a real `.env`.

---

## Out of scope
New console features, changes to Jev's questions, thresholds or routing, the `--judge` fixes, and real API calls.
