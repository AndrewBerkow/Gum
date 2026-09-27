"""Top-level integration tests for t1 / Fix 7: a fake `.env` created by a test must never
outlive the test run.

Public entry points used:
  `tests.fake_dotenv`        -- the shared helper Fix 7 introduces; the only way any test may
                                 create a repo-root `.env`. Imported here exactly as any other
                                 test file will import it once Fix 7 lands: `fake_dotenv(path)` as
                                 a context manager, and `heal_dotenv(path)` as the function
                                 `tests/conftest.py`'s `pytest_sessionstart` hook calls.
  `tests/conftest.py`'s `pytest_sessionstart` hook -- exercised indirectly, by spawning real
                                 `pytest` subprocesses against this repo and inspecting the
                                 repo-root `.env` before and after each one starts.
  `pytest` itself and `git status --porcelain`, used as oracles exactly like the existing Fix 2 /
  Fix 4 top-level tests.

Every test here either operates on a temporary directory, or first checks that no real `.env`
already sits at the repo root before placing a *marked* one there, and always removes whatever it
placed in a `finally` -- regardless of whether the assertions above it passed. No real API key is
ever created, and this file never deletes a `.env` that lacks the marker.
"""

import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.nested_suite import nested_suite_env

ROOT = Path(__file__).resolve().parents[2]
THIS_FILE = "tests/integration/test_fix7_fake_dotenv_self_heals.py"
DOTENV_PATH = ROOT / ".env"

# The exact marker line FIX_PLAN_3.md's Fix 7 specifies. Tests compare against this literal,
# rather than importing a constant from the helper under test, so a wrong string in the
# implementation can't make its own test trivially agree with itself.
MARKER = "# GUM-TEST-FAKE-ENV: created by the test suite; safe to delete"

NESTED_SUITE_QUICK_NODEID = (
    "tests/unit/test_nested_suite.py::test_nested_suite_env_adds_flag_without_mutating_input"
)

_FAKE_TYPESAFE_KEY = "ts_live_test1234567890abcdef"
_FAKE_GOOGLE_KEY = "AIzaTEST1234567890abcdefghijklmnopqrs"


# ---------------------------------------------------------------- helpers


def _clean_env(**overrides: str) -> dict[str, str]:
    """A child env with no real-looking key vars and no tracing, plus the given overrides."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("TYPESAFE_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "GUM_NESTED_SUITE")
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


def _write_marked_file_directly(path: Path) -> None:
    """Write a marked fake `.env` bypassing the helper's own API, to simulate a *leftover* file
    from a process that was killed before it could clean up -- exactly the scenario Fix 7 must
    heal from."""
    path.write_text(
        f"{MARKER}\nTYPESAFE_API_KEY={_FAKE_TYPESAFE_KEY}\nGOOGLE_API_KEY={_FAKE_GOOGLE_KEY}\n"
    )


def _run_quick_pytest(env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", NESTED_SUITE_QUICK_NODEID, "-q", "-p", "no:cacheprovider"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )


def _skip_if_real_dotenv_present() -> None:
    if DOTENV_PATH.exists():
        pytest.skip("a real .env already sits at the repo root; refusing to simulate a leftover there")


# ------------------------------------------------------------------------------------------
# AC: a repo-root .env whose first line is the marker is removed when a fresh top-level pytest
# session starts (a subprocess run of a trivial -k/nodeid selection, without GUM_NESTED_SUITE).
# ------------------------------------------------------------------------------------------


def test_marked_repo_root_dotenv_is_removed_by_a_fresh_top_level_session_start():
    _skip_if_real_dotenv_present()

    _write_marked_file_directly(DOTENV_PATH)
    try:
        r = _run_quick_pytest(_clean_env())
        assert r.returncode == 0, r.stdout + r.stderr
        assert not DOTENV_PATH.exists(), (
            "a fresh top-level pytest session must self-heal (delete) a marked leftover .env"
        )
    finally:
        DOTENV_PATH.unlink(missing_ok=True)


# ------------------------------------------------------------------------------------------
# AC: a .env without the marker is untouched by session start: same bytes, same mtime. Exercised
# directly, against a temporary path, via the same injectable-target-path function the hook
# itself calls -- so this test is safe to run whether or not a real .env exists at the repo root.
# ------------------------------------------------------------------------------------------


def test_unmarked_dotenv_is_untouched_same_bytes_and_mtime(tmp_path):
    from tests.fake_dotenv import heal_dotenv

    real_looking = tmp_path / ".env"
    real_looking.write_text("TYPESAFE_API_KEY=ts_live_realuserkey\nGOOGLE_API_KEY=AIzaRealUserKey\n")
    before_bytes = real_looking.read_bytes()
    before_mtime = real_looking.stat().st_mtime_ns

    heal_dotenv(real_looking)

    assert real_looking.exists(), "an unmarked .env must never be deleted"
    assert real_looking.read_bytes() == before_bytes
    assert real_looking.stat().st_mtime_ns == before_mtime


# ------------------------------------------------------------------------------------------
# AC: the helper writes the marker as the first line, refuses to overwrite an existing .env, and
# removes only a file it created.
# ------------------------------------------------------------------------------------------


def test_helper_writes_marker_as_the_first_line(tmp_path):
    from tests.fake_dotenv import fake_dotenv

    target = tmp_path / ".env"
    with fake_dotenv(target):
        first_line = target.read_text().splitlines()[0]

    assert first_line == MARKER


def test_helper_refuses_to_overwrite_an_existing_dotenv(tmp_path):
    from tests.fake_dotenv import fake_dotenv

    target = tmp_path / ".env"
    target.write_text("TYPESAFE_API_KEY=ts_live_realuserkey\n")

    with pytest.raises(FileExistsError):
        with fake_dotenv(target):
            pass

    assert target.read_text() == "TYPESAFE_API_KEY=ts_live_realuserkey\n", (
        "the helper must never overwrite a pre-existing .env, even one it's about to refuse on"
    )


def test_helper_removes_only_the_file_it_created(tmp_path):
    from tests.fake_dotenv import fake_dotenv

    pre_existing = tmp_path / "existing.env"
    pre_existing.write_text("TYPESAFE_API_KEY=ts_live_realuserkey\n")
    fresh = tmp_path / "fresh.env"

    with fake_dotenv(fresh) as created_path:
        assert created_path.exists()

    assert not created_path.exists(), "the helper must remove the file it created on exit"
    assert pre_existing.exists(), "the helper must never remove a file it did not create"
    assert pre_existing.read_text() == "TYPESAFE_API_KEY=ts_live_realuserkey\n"


# ------------------------------------------------------------------------------------------
# AC: a process killed with SIGKILL while holding the helper's fake .env leaves a marked file,
# and the next session start removes it.
# ------------------------------------------------------------------------------------------


def test_sigkilled_process_leaves_marked_file_and_next_session_start_removes_it():
    _skip_if_real_dotenv_present()

    code = (
        "import sys, time\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "from tests.fake_dotenv import fake_dotenv\n"
        f"with fake_dotenv({str(DOTENV_PATH)!r}):\n"
        "    time.sleep(60)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        cwd=ROOT, env=_clean_env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        deadline = time.time() + 10
        while time.time() < deadline and not DOTENV_PATH.exists() and proc.poll() is None:
            time.sleep(0.1)

        if not DOTENV_PATH.exists():
            out = proc.stdout.read() if proc.stdout else ""
            proc.kill()
            pytest.fail(f"the helper subprocess never created the fake .env; output:\n{out}")

        os.kill(proc.pid, signal.SIGKILL)
        proc.wait(timeout=10)

        assert DOTENV_PATH.exists(), "SIGKILL must not have run the helper's `finally` cleanup"
        assert DOTENV_PATH.read_text().splitlines()[0] == MARKER

        r = _run_quick_pytest(_clean_env())
        assert r.returncode == 0, r.stdout + r.stderr
        assert not DOTENV_PATH.exists(), (
            "the next top-level session start must heal the leftover marked .env"
        )
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
        DOTENV_PATH.unlink(missing_ok=True)


# ------------------------------------------------------------------------------------------
# AC: the session-start heal does not run in nested suites (GUM_NESTED_SUITE set), while a
# subsequent non-nested session start still heals the same leftover file.
# ------------------------------------------------------------------------------------------


def test_self_heal_only_runs_outside_nested_suites():
    _skip_if_real_dotenv_present()

    _write_marked_file_directly(DOTENV_PATH)
    try:
        r_nested = _run_quick_pytest(nested_suite_env(_clean_env()))
        assert r_nested.returncode == 0, r_nested.stdout + r_nested.stderr
        assert DOTENV_PATH.exists(), "GUM_NESTED_SUITE=1 must suppress the self-heal hook"

        r_top_level = _run_quick_pytest(_clean_env())
        assert r_top_level.returncode == 0, r_top_level.stdout + r_top_level.stderr
        assert not DOTENV_PATH.exists(), (
            "a subsequent top-level (non-nested) session start must still heal the leftover file"
        )
    finally:
        DOTENV_PATH.unlink(missing_ok=True)


# ------------------------------------------------------------------------------------------
# AC: grep -rn '\.env' tests/ shows no repo-root .env writers other than the helper.
# ------------------------------------------------------------------------------------------

_ROOT_DOTENV_PATH_RE = re.compile(r'\(?\s*ROOT\s*/\s*["\']\.env["\']\s*\)?\s*\.write_text\(')


def test_no_repo_root_dotenv_writers_outside_the_helper():
    offenders = []
    for path in sorted((ROOT / "tests").rglob("*.py")):
        # fake_dotenv.py is the helper itself; this file's own direct write simulates a
        # crash-leftover file on purpose (see `_write_marked_file_directly`), which is exactly
        # the scenario Fix 7's self-heal is built to recover from, not a writer the fix migrates.
        if path.name in ("fake_dotenv.py", "test_fix7_fake_dotenv_self_heals.py"):
            continue
        text = path.read_text()
        if _ROOT_DOTENV_PATH_RE.search(text):
            offenders.append(str(path.relative_to(ROOT)))

    assert not offenders, (
        f"only tests/fake_dotenv.py may write a repo-root .env; found direct writers: {offenders}"
    )


# ------------------------------------------------------------------------------------------
# AC (global acceptance, scoped to this fix): using the helper to create and clean up a
# repo-root .env leaves `git status --porcelain` exactly as it was.
# ------------------------------------------------------------------------------------------


def test_git_status_unchanged_after_using_the_helper_at_the_repo_root():
    _skip_if_real_dotenv_present()

    from tests.fake_dotenv import fake_dotenv

    before = _git_status()
    with fake_dotenv(DOTENV_PATH):
        pass
    after = _git_status()

    assert after == before
