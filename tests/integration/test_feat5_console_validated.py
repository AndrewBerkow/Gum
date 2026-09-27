"""Top-level integration tests for t1 (FEATURE_PLAN_2.md Task A): the console test helper bug and
the resulting validation of FEATURE_PLAN.md Task 3 (the split-panel Jev dev console).

`tests/integration/test_feat3_console_ui.py`'s `wait_for_cards` helper calls
`page.wait_for_function(expression, n)`, passing its argument positionally. In the Python
Playwright API (`playwright==1.63.0`), `Page.wait_for_function(expression, *, arg=None, ...)`
takes `arg` by keyword only, so every test that calls `wait_for_cards` currently raises
`TypeError: Page.wait_for_function() takes 2 positional arguments but 3 were given` before it ever
touches the page. This file locks in the fix (run `test_feat3_console_ui.py` as a subprocess and
require it fully green) and the contract that must never regress again (no `wait_for_function(`
call anywhere in `tests/` may pass its argument positionally).

Public entry points used:
  `pytest`, invoked as a subprocess against `tests/integration/test_feat3_console_ui.py`, exactly
                             like the existing Fix 2 / Fix 4 / Fix 5 / Fix 8 / Fix 10 top-level
                             suite-spawning tests (see `tests/integration/test_fix10_suite_green_both_ways.py`).
  Source text of every `tests/**/*.py` file, read only, never executed, to statically verify the
                             `wait_for_function` keyword-only-`arg` contract via `ast` (a plain
                             substring grep would also flag the harmless single-argument calls
                             already in this codebase, e.g. `page.wait_for_function("() => ...")`).

Nothing here holds a real API key or makes a real API call: the subprocess below drives the
console entirely against `test_feat3_console_ui.py`'s own `offline_url` fixture (stub Jev + fake
chat models), and its child environment strips the same real-looking key variables the rest of the
suite strips (`tests/integration/test_fix10_suite_green_both_ways.py`'s `_clean_env` precedent), so
this file's behaviour does not depend on whether a real repo-root `.env` exists.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = "tests/integration/test_feat3_console_ui.py"


def _clean_env() -> dict[str, str]:
    """A child env with no real-looking key vars and no tracing -- the same filtering
    `test_fix10_suite_green_both_ways.py`'s `_clean_env` applies, so the subprocess below can never
    make a real API call regardless of what the developer's own shell environment holds."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("TYPESAFE_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY")
        and not k.startswith(("LANGCHAIN_", "LANGSMITH_"))
    }
    env["LANGCHAIN_TRACING_V2"] = "false"
    env["LANGSMITH_TRACING"] = "false"
    return env


def _counts(stdout: str) -> tuple[int, int]:
    """(passed, failed) parsed from pytest's `-q` summary line."""
    passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", stdout)) else 0
    failed = int(m.group(1)) if (m := re.search(r"(\d+) failed", stdout)) else 0
    return passed, failed


# ------------------------------------------------------------------------------------------
# AC: a subprocess run of `pytest tests/integration/test_feat3_console_ui.py -q` gives 0 failures
# and at least 12 passed, using a real uvicorn on localhost with stub/fake backends (the file's own
# `offline_url` fixture), like the existing file.
# ------------------------------------------------------------------------------------------


def test_console_ui_suite_is_fully_green_with_at_least_twelve_passed():
    r = subprocess.run(
        [sys.executable, "-m", "pytest", TARGET, "-q", "-p", "no:cacheprovider"],
        cwd=ROOT, env=_clean_env(), capture_output=True, text=True, timeout=300, check=False,
    )
    passed, failed = _counts(r.stdout)
    assert failed == 0, r.stdout[-4000:] + r.stderr[-1000:]
    assert passed >= 12, r.stdout[-4000:]
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-1000:]


# ------------------------------------------------------------------------------------------
# AC: a grep over `tests/` finds no `wait_for_function(` call that passes its argument
# positionally (Playwright's `Page.wait_for_function(expression, *, arg=None, ...)` takes `arg` by
# keyword only).
# ------------------------------------------------------------------------------------------


def _positional_wait_for_function_calls(path: Path) -> list[tuple[Path, int]]:
    """Every `<expr>.wait_for_function(...)` call in `path` that passes more than the bare
    expression positionally (i.e. an `arg` given as a second positional argument instead of
    `arg=...`). Returns `(path, lineno)` for each offender."""
    tree = ast.parse(path.read_text(), filename=str(path))
    offenders = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "wait_for_function"
            and len(node.args) > 1
        ):
            offenders.append((path, node.lineno))
    return offenders


def test_no_wait_for_function_call_passes_its_argument_positionally():
    offenders = []
    for path in sorted((ROOT / "tests").rglob("*.py")):
        offenders.extend(_positional_wait_for_function_calls(path))
    assert offenders == [], (
        "wait_for_function's arg must be passed as arg=..., not positionally: "
        + ", ".join(f"{p.relative_to(ROOT)}:{n}" for p, n in offenders)
    )
