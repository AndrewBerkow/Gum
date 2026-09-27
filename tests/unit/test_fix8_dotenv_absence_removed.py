"""Unit tests for t2 / Fix 8: no test may assert a repo-root `.env` is absent.

These mirror the structural check the top-level `test_fix8_real_dotenv_present.py` already uses
for the Fix 5 case (`inspect.getsource` + regex), applied to each function that used to hold the
absence assertion, so each fix is provable cheaply without re-running an expensive subprocess.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

_ABSENCE_ASSERTION_RE = re.compile(
    r'assert not\s*\(?\s*ROOT\s*'
    r'(?:/\s*["\']\.env["\']|\.joinpath\(\s*["\']\.env["\']\s*\))'
    r'\s*\)?\s*\.exists\(\)'
)


def test_fix4_regression_nodeids_test_uses_gum_env_file_not_absence_assert():
    from tests.integration import test_fix4_dotenv_isolation as fix4

    fn = fix4.test_fix4_listed_regression_tests_pass_without_dotenv
    source = inspect.getsource(fn)

    assert not _ABSENCE_ASSERTION_RE.search(source), (
        f"this test must no longer assert that .env is absent:\n{source}"
    )
    assert "GUM_ENV_FILE" in source, (
        f"this test must hide .env from its subprocess via GUM_ENV_FILE pointing at an empty "
        f"temporary file instead:\n{source}"
    )


def test_fix4_full_suite_without_dotenv_test_uses_gum_env_file_not_absence_assert():
    from tests.integration import test_fix4_dotenv_isolation as fix4

    fn = fix4.test_full_not_live_suite_without_dotenv_is_green_and_leaves_git_status_unchanged
    source = inspect.getsource(fn)

    assert not _ABSENCE_ASSERTION_RE.search(source), (
        f"this test must no longer assert that .env is absent:\n{source}"
    )
    assert "GUM_ENV_FILE" in source, (
        f"this test must hide .env from its subprocess via GUM_ENV_FILE pointing at an empty "
        f"temporary file instead:\n{source}"
    )


def test_fix5_full_suite_without_dotenv_test_uses_gum_env_file_not_absence_assert():
    from tests.integration import test_fix5_live_reads_dotenv as fix5

    fn = fix5.test_full_not_live_suite_without_dotenv_is_green_and_leaves_git_status_unchanged
    source = inspect.getsource(fn)

    assert not _ABSENCE_ASSERTION_RE.search(source), (
        f"this test must no longer assert that .env is absent:\n{source}"
    )
    assert "GUM_ENV_FILE" in source, (
        f"this test must hide .env from its subprocess via GUM_ENV_FILE pointing at an empty "
        f"temporary file instead:\n{source}"
    )


def test_no_dotenv_absence_assertions_anywhere_in_tests():
    offenders = []
    for path in sorted((ROOT / "tests").rglob("*.py")):
        if path.name in ("test_fix8_real_dotenv_present.py", "test_fix8_dotenv_absence_removed.py"):
            continue
        text = path.read_text()
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _ABSENCE_ASSERTION_RE.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")

    assert not offenders, (
        "no test may assert a repo-root .env is absent; found:\n" + "\n".join(offenders)
    )
