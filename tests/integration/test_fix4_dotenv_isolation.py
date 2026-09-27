"""Top-level integration tests for t1 / Fix 4: offline tests must never read the developer's
`.env`, and the app's default (unset `GUM_ENV_FILE`) behaviour must stay unchanged for users.

Public entry points used:
  `app.config.Settings`   -- constructed the same way the app and tests construct it; only the
                             `GUM_ENV_FILE` environment variable and each process's cwd are varied.
  `app.main.create_app`   -- inspected for its signature only, never changed.
  `pytest` itself, invoked as a subprocess against this repo's test tree, and `git status
  --porcelain`, exactly like the existing Fix 2 / Fix 3 top-level tests.

Nothing here imports app code that talks to a network; no real key is ever created. Following
FIX_PLAN_2.md's rule, any fake `.env` this file places at the repo root is created only when none
already exists, and removed in a `finally`; an existing `.env` is never touched.
"""

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
THIS_FILE = "tests/integration/test_fix4_dotenv_isolation.py"

_FAKE_TYPESAFE_KEY = "ts_live_test1234567890abcdef"
_FAKE_GOOGLE_KEY = "AIzaTEST1234567890abcdefghijklmnopqrs"

# The 12 tests FIX_PLAN_2.md's Fix 4 says fail today when a fake `.env` sits at the repo root.
FIX4_REGRESSION_NODEIDS = [
    "tests/integration/test_fix1_entrypoint.py::"
    "test_subprocess_uvicorn_live_backend_without_key_fails_loudly_naming_typesafe_key",
    "tests/unit/test_live_scaffold.py::test_jev_gated_tests_skip_citing_typesafe_api_key",
    "tests/unit/test_live_scaffold.py::test_gemini_gated_tests_skip_citing_google_api_key",
    "tests/integration/test_fix3_live_scaffold.py::"
    "test_marker_live_suite_with_no_keys_reports_only_skips_naming_missing_keys",
    "tests/integration/test_fix2_repo_hygiene.py::"
    "test_full_suite_subprocess_stays_green_and_leaves_no_new_git_changes",
    "tests/integration/test_t5_frontend_e2e.py::test_full_not_live_suite_green_with_no_env_file",
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


def _settings_secret_via_subprocess(field: str, env: dict[str, str], cwd: Path) -> str | None:
    """Build `Settings()` in a fresh subprocess and return `getattr(settings, field)`'s secret
    value (or None), so no import-time caching in this test process can affect the result."""
    code = (
        f"from app.config import Settings\n"
        f"s = Settings()\n"
        f"v = s.{field}\n"
        f"print(repr(v.get_secret_value() if v is not None else None))\n"
    )
    env = {**env, "PYTHONPATH": str(ROOT)}  # `app` must import regardless of cwd, which we vary on purpose
    r = subprocess.run(
        [sys.executable, "-c", code], cwd=cwd, env=env, capture_output=True, text=True, timeout=15,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    return eval(r.stdout.strip())  # noqa: S307 -- our own repr() output, not attacker input


def _failed_count(stdout: str) -> int:
    m = re.search(r"(\d+) failed", stdout)
    return int(m.group(1)) if m else 0


def _git_status() -> set[str]:
    out = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    lines = {ln for ln in out.splitlines() if ln.strip()}
    return {ln for ln in lines if ".pytest_cache" not in ln}


@contextmanager
def _fake_dotenv_at_repo_root():
    """Place a fake `.env` at the repo root, unless one already exists; never overwrite a real one."""
    path = ROOT / ".env"
    created = not path.exists()
    if created:
        path.write_text(f"TYPESAFE_API_KEY={_FAKE_TYPESAFE_KEY}\nGOOGLE_API_KEY={_FAKE_GOOGLE_KEY}\n")
    try:
        yield
    finally:
        if created:
            path.unlink(missing_ok=True)


# ------------------------------------------------------------------------------------------
# AC: Settings honours GUM_ENV_FILE -- a path to a temp file holding a fake key makes Settings()
# read that key; GUM_ENV_FILE="" makes Settings() read no file even when one exists in its cwd.
# ------------------------------------------------------------------------------------------


def test_settings_reads_key_from_gum_env_file_path(tmp_path):
    env_file = tmp_path / "custom.env"
    env_file.write_text(f"TYPESAFE_API_KEY={_FAKE_TYPESAFE_KEY}\n")

    value = _settings_secret_via_subprocess(
        "typesafe_api_key", _clean_env(GUM_ENV_FILE=str(env_file)), cwd=ROOT
    )

    assert value == _FAKE_TYPESAFE_KEY


def test_settings_reads_no_file_when_gum_env_file_is_empty_string(tmp_path):
    (tmp_path / ".env").write_text(f"TYPESAFE_API_KEY={_FAKE_TYPESAFE_KEY}\n")

    value = _settings_secret_via_subprocess(
        "typesafe_api_key", _clean_env(GUM_ENV_FILE=""), cwd=tmp_path
    )

    assert value is None, "GUM_ENV_FILE='' must make Settings() read no env file at all"


# ------------------------------------------------------------------------------------------
# AC: with GUM_ENV_FILE unset, Settings() in a subprocess whose cwd (a temp dir, not the repo
# root) holds a `.env` still reads it -- the default behaviour for real users is unchanged.
# ------------------------------------------------------------------------------------------


def test_settings_reads_default_dotenv_in_cwd_when_gum_env_file_unset(tmp_path):
    (tmp_path / ".env").write_text(f"TYPESAFE_API_KEY={_FAKE_TYPESAFE_KEY}\n")

    env = _clean_env()
    env.pop("GUM_ENV_FILE", None)
    value = _settings_secret_via_subprocess("typesafe_api_key", env, cwd=tmp_path)

    assert value == _FAKE_TYPESAFE_KEY, (
        "with GUM_ENV_FILE unset, Settings() must still read a .env from its own cwd by default"
    )


# ------------------------------------------------------------------------------------------
# AC: tests/conftest.py sets GUM_ENV_FILE="" at import time, and keeps the autouse fixture that
# clears key variables.
# ------------------------------------------------------------------------------------------


def test_conftest_sets_gum_env_file_empty_string_at_import_time():
    r = subprocess.run(
        [sys.executable, "-c", "import tests.conftest, os; print(repr(os.environ.get('GUM_ENV_FILE')))"],
        cwd=ROOT, capture_output=True, text=True, timeout=10,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.strip() == "''", (
        f"tests/conftest.py must set GUM_ENV_FILE='' in os.environ at import time, got: {r.stdout!r}"
    )


def test_conftest_keeps_autouse_fixture_clearing_key_variables():
    import tests.conftest as conftest

    marker = conftest._clean_env._fixture_function_marker
    assert marker.autouse is True, "tests/conftest.py must keep _clean_env as an autouse fixture"
    assert "TYPESAFE_API_KEY" in conftest._CLEARED_NAMES
    assert "GOOGLE_API_KEY" in conftest._CLEARED_NAMES


# ------------------------------------------------------------------------------------------
# AC: create_app()'s signature is unchanged by this task.
# ------------------------------------------------------------------------------------------


def test_create_app_signature_is_unchanged():
    from app.main import create_app

    sig = inspect.signature(create_app)
    assert list(sig.parameters) == ["settings", "graph", "log"]
    assert all(p.default is None for p in sig.parameters.values())


# ------------------------------------------------------------------------------------------
# AC: with a fake .env in the repo root, the 12 previously-failing tests pass, and still pass
# with no .env either -- with no weakened assertions. The two suite-spawning tests among them
# are asked to treat themselves as already nested (GUM_NESTED_SUITE=1), so this check stays fast
# and deterministic; the full, unnested recursive run is exercised for real by the tests below.
# ------------------------------------------------------------------------------------------


def test_fix4_listed_regression_tests_pass_with_fake_dotenv_present():
    with _fake_dotenv_at_repo_root():
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *FIX4_REGRESSION_NODEIDS, "-q", "-p", "no:cacheprovider"],
            cwd=ROOT, env=nested_suite_env(_clean_env()), capture_output=True, text=True, timeout=200,
        )
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-1000:]
    assert _failed_count(r.stdout) == 0, r.stdout[-4000:]


def test_fix4_listed_regression_tests_pass_without_dotenv():
    assert not (ROOT / ".env").exists(), "this test expects no real .env; found one at repo root"
    r = subprocess.run(
        [sys.executable, "-m", "pytest", *FIX4_REGRESSION_NODEIDS, "-q", "-p", "no:cacheprovider"],
        cwd=ROOT, env=nested_suite_env(_clean_env()), capture_output=True, text=True, timeout=200,
    )
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-1000:]
    assert _failed_count(r.stdout) == 0, r.stdout[-4000:]


# ------------------------------------------------------------------------------------------
# AC (global acceptance): with a fake .env in the repo root, a full non-live suite subprocess
# run (self-ignored, following the GUM_NESTED_SUITE guard) has 0 failures, and leaves
# `git status --porcelain` unchanged.
# ------------------------------------------------------------------------------------------


def test_full_not_live_suite_with_fake_dotenv_is_green_and_leaves_git_status_unchanged():
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


# ------------------------------------------------------------------------------------------
# AC (global acceptance): `uv run pytest -q` also stays green with no `.env` at all, and still
# leaves `git status --porcelain` unchanged.
# ------------------------------------------------------------------------------------------


def test_full_not_live_suite_without_dotenv_is_green_and_leaves_git_status_unchanged():
    if is_nested_suite():
        pytest.skip("already running inside a nested full-suite invocation")
    assert not (ROOT / ".env").exists(), "this test expects no real .env; found one at repo root"

    before = _git_status()
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--ignore={THIS_FILE}"],
        cwd=ROOT, env=nested_suite_env(_clean_env()), capture_output=True, text=True, timeout=500,
    )
    after = _git_status()

    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-1000:]
    assert _failed_count(r.stdout) == 0, r.stdout[-4000:]
    assert after == before, f"full suite run left new/changed git-status lines: {after - before}"
