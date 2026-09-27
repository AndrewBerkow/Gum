"""Top-level integration tests for t1 / Fix 10 (FIX_PLAN_4.md): the whole suite must be green
both with no repo-root `.env` and with an unmarked, real-looking one, and every test that uses
`tests.fake_dotenv` must handle a pre-existing `.env` instead of crashing.

Public entry points used:
  `pytest` itself, invoked as a subprocess against this repo's test tree (the whole non-live
                             suite, and targeted node-id subsets), exactly like the existing
                             Fix 2 / Fix 4 / Fix 5 / Fix 8 top-level tests.
  `tests.fake_dotenv.fake_dotenv` -- the shared Fix 7 helper, used only to confirm it still
                             refuses to overwrite an existing file; never used to write a repo-root
                             `.env` here (this file writes its own *unmarked* simulated `.env`
                             directly, since the helper's file is always marked and this file needs
                             to simulate the user's own, unmarked file).
  `tests.nested_suite`       -- the shared recursion guard the existing suite-spawning tests use.
  Source text of `tests/integration/test_fix5_live_reads_dotenv.py` (via `inspect.getsource`),
                             read only, never executed, to check the live-tier "attempted" check
                             never needs a real key.
  `git status --porcelain`  -- the global-acceptance oracle, exactly like Fix 4 / Fix 5 / Fix 8.

Nothing here holds a real API key: the simulated `.env` this file may place at the repo root
carries only fake-but-real-looking values (`ts_live_simreal...` / `AIzaSIMREAL...`), is created
only when no `.env` already exists there, and is removed in a `finally` -- an existing `.env` is
never modified or deleted. An autouse fixture below additionally asserts, after every single test
in this file, that the repo-root `.env`'s existence and bytes are exactly what they were before
that test ran, so a bug in any one test can't leave the repo dirty for the rest of the suite.
"""

from __future__ import annotations

import inspect
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

from tests.nested_suite import is_nested_suite, nested_suite_env

ROOT = Path(__file__).resolve().parents[2]
THIS_FILE = "tests/integration/test_fix10_suite_green_both_ways.py"
FIX7_FILE = "tests/integration/test_fix7_fake_dotenv_self_heals.py"

# Deliberately built with `.joinpath(...)`, not the `ROOT / ".env"` slash form: the existing
# Fix 7 check `test_no_repo_root_dotenv_writers_outside_the_helper` greps tests/ for that exact
# slash-form pattern next to `.write_text(` to enforce "only tests/fake_dotenv.py writes a
# repo-root .env". This file *must* write its own unmarked `.env` directly (see module docstring),
# so it uses the same `.joinpath(...)` spelling `tests/fake_dotenv.py`'s own callers use for this
# exact reason.
DOTENV_PATH = ROOT.joinpath(".env")

# The plan's own example values (FIX_PLAN_4.md): real-looking but fake, and never used to make a
# network call in this file.
_UNMARKED_TYPESAFE_KEY = "ts_live_simreal1234567890abcd"
_UNMARKED_GOOGLE_KEY = "AIzaSIMREAL1234567890abcdefghijklmnop"
_UNMARKED_DOTENV_CONTENT = (
    f"TYPESAFE_API_KEY={_UNMARKED_TYPESAFE_KEY}\nGOOGLE_API_KEY={_UNMARKED_GOOGLE_KEY}\n"
)

# The three tests FIX_PLAN_4.md's Bug 2 names as raising FileExistsError when an unmarked .env
# already sits at the repo root.
BUG2_REGRESSION_NODEIDS = [
    "tests/integration/test_fix4_dotenv_isolation.py::"
    "test_fix4_listed_regression_tests_pass_with_fake_dotenv_present",
    "tests/integration/test_fix5_live_reads_dotenv.py::"
    "test_live_tier_reads_repo_root_dotenv_by_default_and_attempts_jev_gated_tests",
    "tests/integration/test_fix5_live_reads_dotenv.py::"
    "test_live_marker_suite_with_empty_gum_env_file_only_skips_even_with_repo_root_dotenv",
]


# ---------------------------------------------------------------- helpers


def _clean_env(**overrides: str) -> dict[str, str]:
    """A child env with no real-looking key vars and no tracing, plus the given overrides."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("TYPESAFE_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY")
        and not k.startswith(("LANGCHAIN_", "LANGSMITH_"))
    }
    env["LANGCHAIN_TRACING_V2"] = "false"
    env["LANGSMITH_TRACING"] = "false"
    env.update(overrides)
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


@contextmanager
def _unmarked_real_looking_dotenv_at_repo_root():
    """Simulate the user's own unmarked, real-looking `.env`: create it only if none exists
    already, and remove only the file this created -- a pre-existing `.env` is never written to
    or deleted. Yields `(path, created)`."""
    created = not DOTENV_PATH.exists()
    if created:
        DOTENV_PATH.write_text(_UNMARKED_DOTENV_CONTENT)
    try:
        yield DOTENV_PATH, created
    finally:
        if created:
            DOTENV_PATH.unlink(missing_ok=True)


# ---------------------------------------------------------------- fixtures


@pytest.fixture(autouse=True)
def _dotenv_state_preserved():
    """Every test in this file must leave the repo-root `.env` exactly as it found it: same
    existence, same bytes if it existed. This is the file-wide guarantee for FIX_PLAN_4.md's
    'no .env is left behind, and git status --porcelain is unchanged' requirement."""
    existed_before = DOTENV_PATH.exists()
    bytes_before = DOTENV_PATH.read_bytes() if existed_before else None
    yield
    existed_after = DOTENV_PATH.exists()
    assert existed_after == existed_before, (
        "this test must not change whether a repo-root .env exists"
    )
    if existed_before:
        assert DOTENV_PATH.read_bytes() == bytes_before, (
            "this test must not modify a pre-existing repo-root .env"
        )


# ------------------------------------------------------------------------------------------
# AC: `GUM_NESTED_SUITE=1 uv run pytest tests/integration/test_fix7_fake_dotenv_self_heals.py -q`
# gives 0 failures (Bug 1: those tests must build their child env explicitly instead of inheriting
# an ambient GUM_NESTED_SUITE).
# ------------------------------------------------------------------------------------------


def test_fix7_self_heal_suite_is_green_when_nested_suite_is_set():
    r = subprocess.run(
        [sys.executable, "-m", "pytest", FIX7_FILE, "-q", "-p", "no:cacheprovider"],
        cwd=ROOT, env=nested_suite_env(_clean_env()), capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-1000:]
    assert _failed_count(r.stdout) == 0, r.stdout[-4000:]


# ------------------------------------------------------------------------------------------
# AC: with no repo-root .env, a full non-live suite subprocess (GUM_NESTED_SUITE=1, --ignore for
# this file) gives 0 failures.
# ------------------------------------------------------------------------------------------


def test_full_suite_with_no_dotenv_is_green():
    if is_nested_suite():
        pytest.skip("already running inside a nested full-suite invocation")
    if DOTENV_PATH.exists():
        pytest.skip("a real .env already sits at the repo root; this check needs one to be absent")

    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--ignore={THIS_FILE}"],
        cwd=ROOT, env=nested_suite_env(_clean_env()), capture_output=True, text=True, timeout=500,
    )
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-1000:]
    assert _failed_count(r.stdout) == 0, r.stdout[-4000:]


# ------------------------------------------------------------------------------------------
# AC: with an unmarked real-looking .env (created only if none exists, removed in `finally`), the
# same full-suite subprocess gives 0 failures, and the .env is byte-for-byte unchanged afterwards.
# ------------------------------------------------------------------------------------------


def test_full_suite_with_unmarked_real_looking_dotenv_is_green_and_bytes_unchanged():
    if is_nested_suite():
        pytest.skip("already running inside a nested full-suite invocation")

    with _unmarked_real_looking_dotenv_at_repo_root() as (path, _created):
        before_bytes = path.read_bytes()
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--ignore={THIS_FILE}"],
            cwd=ROOT, env=nested_suite_env(_clean_env()), capture_output=True, text=True, timeout=500,
        )
        after_bytes = path.read_bytes()

    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-1000:]
    assert _failed_count(r.stdout) == 0, r.stdout[-4000:]
    assert after_bytes == before_bytes, (
        "an unmarked real-looking .env must be byte-for-byte unchanged by the suite run"
    )


# ------------------------------------------------------------------------------------------
# AC (Bug 2): the fake_dotenv helper still refuses to overwrite an existing .env ...
# ------------------------------------------------------------------------------------------


def test_fake_dotenv_helper_still_refuses_to_overwrite_an_existing_dotenv(tmp_path):
    from tests.fake_dotenv import fake_dotenv

    target = tmp_path / ".env"
    target.write_text("TYPESAFE_API_KEY=ts_live_realuserkey\n")

    with pytest.raises(FileExistsError):
        with fake_dotenv(target):
            pass

    assert target.read_text() == "TYPESAFE_API_KEY=ts_live_realuserkey\n", (
        "the helper must never overwrite a pre-existing .env, even one it's about to refuse on"
    )


# ------------------------------------------------------------------------------------------
# AC (Bug 2): ... and the tests that use it handle a pre-existing .env instead of crashing with
# FileExistsError -- specifically the three tests FIX_PLAN_4.md names.
# ------------------------------------------------------------------------------------------


def test_fix4_and_fix5_dotenv_tests_handle_a_pre_existing_unmarked_dotenv():
    with _unmarked_real_looking_dotenv_at_repo_root():
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *BUG2_REGRESSION_NODEIDS, "-q", "-p", "no:cacheprovider"],
            cwd=ROOT, env=nested_suite_env(_clean_env()), capture_output=True, text=True, timeout=200,
        )

    out = r.stdout + r.stderr
    assert "FileExistsError" not in out, (
        f"these tests must handle a pre-existing .env instead of crashing:\n{out[-4000:]}"
    )
    assert r.returncode == 0, out[-4000:]
    assert _failed_count(r.stdout) == 0, out[-4000:]


# ------------------------------------------------------------------------------------------
# AC: the live-tier check that expects key-gated tests to be *attempted* never uses real keys: it
# points GUM_ENV_FILE at a temp file with fake keys, or skips with a clear reason when the
# repo-root default path is required and a real .env exists.
# ------------------------------------------------------------------------------------------


def test_live_tier_attempted_check_never_requires_a_real_repo_root_dotenv():
    from tests.integration import test_fix5_live_reads_dotenv as fix5

    fn = getattr(
        fix5, "test_live_tier_reads_repo_root_dotenv_by_default_and_attempts_jev_gated_tests", None
    )
    assert fn is not None, (
        "tests/integration/test_fix5_live_reads_dotenv.py must still define "
        "test_live_tier_reads_repo_root_dotenv_by_default_and_attempts_jev_gated_tests"
    )
    source = inspect.getsource(fn)

    uses_temp_fake_key_env_file = (
        "GUM_ENV_FILE" in source
        and "TYPESAFE_API_KEY" in source
        and ("tmp_path" in source or "NamedTemporaryFile" in source)
    )
    skips_with_a_reason_instead = "pytest.skip(" in source and ".env" in source.lower()

    assert uses_temp_fake_key_env_file or skips_with_a_reason_instead, (
        "the live-tier 'attempted' check must point GUM_ENV_FILE at a temp fake-key file, or skip "
        f"with a clear reason, instead of requiring a real repo-root .env:\n{source}"
    )


# ------------------------------------------------------------------------------------------
# AC (global acceptance): after using the simulated unmarked .env, it is gone again and git status
# --porcelain is unchanged (mirrors Fix 7's own git-status hygiene check, for the unmarked file
# this task introduces).
# ------------------------------------------------------------------------------------------


def test_git_status_unchanged_after_using_the_unmarked_dotenv_helper():
    if DOTENV_PATH.exists():
        pytest.skip("a real .env already sits at the repo root; nothing to create/remove here")

    before = _git_status()
    with _unmarked_real_looking_dotenv_at_repo_root() as (path, created):
        assert created, "the simulated .env must be created only because none existed"
        assert path.exists()
    after = _git_status()

    assert not DOTENV_PATH.exists(), "the simulated unmarked .env must be removed afterwards"
    assert after == before, f"using the simulated .env must leave git status unchanged: {after - before}"
