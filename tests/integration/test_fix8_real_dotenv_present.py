"""Top-level integration tests for t2 / Fix 8: no test may require the absence of a real `.env`.

Public entry points used:
  `pytest` itself, run as a subprocess against the whole non-live suite -- exactly like the
                             existing Fix 4 / Fix 5 top-level tests -- to prove the suite stays
                             green when a repo-root `.env` exists.
  `tests.fake_dotenv.fake_dotenv` -- the shared Fix 7 helper, the only way this file creates a
                             repo-root `.env`; it carries the safe-to-delete marker (a comment,
                             invisible to the code under test) and always cleans up after itself.
  `git status --porcelain`  -- the global-acceptance oracle, exactly like Fix 4 / Fix 5.
  Source text of `tests/` (via `grep`-equivalent regex and `inspect.getsource`) -- read only,
                             never executed, to check no test still asserts a `.env` is absent.

Nothing here holds a real API key: the helper's fake keys are real-looking but inert, and the
classifier code path is never exercised by this file. Any fake `.env` this file places at the
repo root is created only when none already exists (the helper refuses to overwrite one), and is
always removed, even on failure.
"""

from __future__ import annotations

import inspect
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.fake_dotenv import fake_dotenv
from tests.nested_suite import is_nested_suite, nested_suite_env

ROOT = Path(__file__).resolve().parents[2]
THIS_FILE = "tests/integration/test_fix8_real_dotenv_present.py"

_ABSENCE_MESSAGE = "expects no real .env"

# Matches both spellings seen in the repo today: `ROOT.joinpath(".env")` and `(ROOT / ".env")`,
# with either quote style, immediately followed by `.exists()` inside an `assert not`.
_ABSENCE_ASSERTION_RE = re.compile(
    r'assert not\s*\(?\s*ROOT\s*'
    r'(?:/\s*["\']\.env["\']|\.joinpath\(\s*["\']\.env["\']\s*\))'
    r'\s*\)?\s*\.exists\(\)'
)


# ---------------------------------------------------------------- helpers


def _clean_env() -> dict[str, str]:
    """A child env with no real-looking key vars and no tracing (GUM_ENV_FILE, if the parent
    process already set it via tests/conftest.py's default, is inherited unchanged)."""
    import os

    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("TYPESAFE_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY")
        and not k.startswith(("LANGCHAIN_", "LANGSMITH_"))
    }
    env["LANGCHAIN_TRACING_V2"] = "false"
    env["LANGSMITH_TRACING"] = "false"
    return env


def _git_status() -> set[str]:
    out = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    lines = {ln for ln in out.splitlines() if ln.strip()}
    return {ln for ln in lines if ".pytest_cache" not in ln}


def _failed_count(stdout: str) -> int:
    m = re.search(r"(\d+) failed", stdout)
    return int(m.group(1)) if m else 0


def _fake_dotenv_at_repo_root():
    """Place a real-looking fake `.env` at the repo root via the shared tests.fake_dotenv helper
    (t1 / Fix 7), the only way any test may create one; it refuses to overwrite a real one and
    always cleans up after itself."""
    return fake_dotenv(ROOT.joinpath(".env"))


# ------------------------------------------------------------------------------------------
# AC: with a repo-root `.env` created via the Fix 7 helper (real-looking fake keys), the full
# non-live suite run in a subprocess with GUM_NESTED_SUITE=1 and --ignore for this test file
# reports 0 failures, its output never contains "expects no real .env", and it leaves
# `git status --porcelain` unchanged.
# ------------------------------------------------------------------------------------------


def test_full_suite_with_marked_real_looking_dotenv_reports_zero_failures():
    if is_nested_suite():
        pytest.skip("already running inside a nested full-suite invocation")

    before = _git_status()
    with _fake_dotenv_at_repo_root():
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--ignore={THIS_FILE}"],
            cwd=ROOT, env=nested_suite_env(_clean_env()), capture_output=True, text=True, timeout=500,
        )
    after = _git_status()

    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-1000:]
    assert _failed_count(r.stdout) == 0, r.stdout[-4000:]
    assert after == before, f"full suite run left new/changed git-status lines: {after - before}"


def test_full_suite_with_marked_real_looking_dotenv_output_never_says_expects_no_real_env():
    if is_nested_suite():
        pytest.skip("already running inside a nested full-suite invocation")

    with _fake_dotenv_at_repo_root():
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--ignore={THIS_FILE}"],
            cwd=ROOT, env=nested_suite_env(_clean_env()), capture_output=True, text=True, timeout=500,
        )

    out = r.stdout + r.stderr
    assert _ABSENCE_MESSAGE not in out, (
        f"no test may assume `.env` is absent; found the old refusal message in suite output:\n"
        f"{out[-4000:]}"
    )


# ------------------------------------------------------------------------------------------
# AC (global acceptance, regression): `uv run pytest -q` also stays green with no `.env` at all,
# and still leaves `git status --porcelain` unchanged, unaffected by this fix.
# ------------------------------------------------------------------------------------------


def test_full_suite_without_dotenv_still_green_and_git_status_unchanged():
    if is_nested_suite():
        pytest.skip("already running inside a nested full-suite invocation")
    if ROOT.joinpath(".env").exists():
        pytest.skip("a real .env already sits at the repo root; this check needs one to be absent")

    before = _git_status()
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--ignore={THIS_FILE}"],
        cwd=ROOT, env=nested_suite_env(_clean_env()), capture_output=True, text=True, timeout=500,
    )
    after = _git_status()

    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-1000:]
    assert _failed_count(r.stdout) == 0, r.stdout[-4000:]
    assert after == before, f"full suite run left new/changed git-status lines: {after - before}"


# ------------------------------------------------------------------------------------------
# AC: `grep` finds no `assert not (ROOT / ".env").exists()` (or the `ROOT.joinpath(".env")`
# equivalent) left anywhere in tests/.
# ------------------------------------------------------------------------------------------


def test_no_dotenv_absence_assertions_left_in_tests():
    offenders = []
    for path in sorted((ROOT / "tests").rglob("*.py")):
        # This file's own docstring/comments describe the pattern being searched for, which would
        # otherwise match itself; every other file is a real candidate offender.
        if path.name == "test_fix8_real_dotenv_present.py":
            continue
        text = path.read_text()
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _ABSENCE_ASSERTION_RE.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")

    assert not offenders, (
        "no test may assert a repo-root .env is absent; found:\n" + "\n".join(offenders)
    )


# ------------------------------------------------------------------------------------------
# AC: the edited Fix 5 test (`test_full_not_live_suite_without_dotenv_is_green_and_leaves_git_
# status_unchanged`) no longer asserts `.env` is absent, hides it from its subprocess via
# GUM_ENV_FILE pointing at an empty temporary file instead, and still verifies the suite is green
# and `git status --porcelain` is unchanged.
# ------------------------------------------------------------------------------------------


def test_fix5_without_dotenv_test_hides_env_via_empty_gum_env_file_not_an_absence_assert():
    from tests.integration import test_fix5_live_reads_dotenv as fix5

    fn = getattr(
        fix5, "test_full_not_live_suite_without_dotenv_is_green_and_leaves_git_status_unchanged", None
    )
    assert fn is not None, (
        "tests/integration/test_fix5_live_reads_dotenv.py must still define "
        "test_full_not_live_suite_without_dotenv_is_green_and_leaves_git_status_unchanged"
    )
    source = inspect.getsource(fn)

    assert not _ABSENCE_ASSERTION_RE.search(source), (
        f"this test must no longer assert that .env is absent:\n{source}"
    )
    assert "GUM_ENV_FILE" in source, (
        f"this test must hide .env from its subprocess via GUM_ENV_FILE pointing at an empty "
        f"temporary file, the way test_fix3_live_scaffold.py does:\n{source}"
    )


def test_fix5_without_dotenv_test_still_verifies_suite_green_and_git_status_unchanged():
    from tests.integration import test_fix5_live_reads_dotenv as fix5

    fn = getattr(
        fix5, "test_full_not_live_suite_without_dotenv_is_green_and_leaves_git_status_unchanged", None
    )
    assert fn is not None, (
        "tests/integration/test_fix5_live_reads_dotenv.py must still define "
        "test_full_not_live_suite_without_dotenv_is_green_and_leaves_git_status_unchanged"
    )
    source = inspect.getsource(fn)

    assert "returncode" in source and "0" in source, (
        f"this test must still assert the subprocess suite run exits 0:\n{source}"
    )
    assert "failed" in source.lower(), (
        f"this test must still assert there are 0 failures in the suite run:\n{source}"
    )
    assert "git" in source.lower() or "before" in source and "after" in source, (
        f"this test must still assert git status --porcelain is unchanged:\n{source}"
    )
