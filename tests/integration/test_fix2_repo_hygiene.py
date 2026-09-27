"""Top-level integration tests for t2 / Fix 2: tests must not write into the repository.

Public entry points used:
  `pytest` itself, invoked as a subprocess against this repo's test tree, exactly the way a
  developer or CI would run it (`uv run pytest -q ...`).
  `git status --porcelain` / `git check-ignore`, used only as an oracle for "did the suite write
  into the working tree", never mocked.

Nothing here imports app code directly: every assertion is made by shelling out to `pytest` and
`git`, then reading their exit codes and output.
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
THIS_FILE = "tests/integration/test_fix2_repo_hygiene.py"
T5_SUITE_SPAWN_NODEID = (
    "tests/integration/test_t5_frontend_e2e.py::test_full_not_live_suite_green_with_no_env_file"
)


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


def _run_pytest_bounded(args: list[str], env: dict[str, str], timeout: float) -> subprocess.CompletedProcess:
    """Run a pytest subprocess in its own process group, killing the whole tree on timeout.

    A guard-less suite-spawning test recurses into another full-suite subprocess instead of
    skipping, so an unguarded run can keep spawning grandchildren well past any single `timeout`.
    Killing the process group (not just the direct child) prevents those from being orphaned.
    """
    proc = subprocess.Popen(
        [sys.executable, "-m", "pytest", *args],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        start_new_session=True,
    )
    try:
        stdout, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, _ = proc.communicate(timeout=10)
        pytest.fail(
            f"pytest {' '.join(args)} did not finish within {timeout}s; this smells like the "
            "unguarded recursive full-suite spawn (missing GUM_NESTED_SUITE) rather than a slow "
            f"suite. Output tail:\n{stdout[-3000:]}"
        )
    return subprocess.CompletedProcess(proc.args, proc.returncode, stdout, None)


# ------------------------------------- AC: full suite in a subprocess leaves git status clean
# ------------------------------------- AC: `uv run pytest -q` stays green, git status stays empty


def test_full_suite_subprocess_stays_green_and_leaves_no_new_git_changes():
    if os.environ.get("GUM_NESTED_SUITE"):
        pytest.skip("already running inside a nested full-suite invocation")

    before = _git_status()
    r = _run_pytest_bounded(
        ["-q", "-p", "no:cacheprovider", f"--ignore={THIS_FILE}"],
        env=_clean_env(GUM_NESTED_SUITE="1"),
        timeout=150,
    )
    assert r.returncode == 0, r.stdout[-3000:]

    after = _git_status()
    new = after - before
    assert not new, f"full test suite left new/changed paths in the working tree: {new}"


# ------------------------------------- AC: evals/reports/*.jsonl and *.md are both gitignored


def test_gitignore_covers_both_jsonl_and_md_eval_reports():
    jsonl = subprocess.run(
        ["git", "check-ignore", "evals/reports/x.jsonl"], cwd=ROOT, capture_output=True, text=True
    )
    md = subprocess.run(
        ["git", "check-ignore", "evals/reports/x.md"], cwd=ROOT, capture_output=True, text=True
    )
    assert jsonl.returncode == 0, "evals/reports/*.jsonl must be gitignored"
    assert md.returncode == 0, "evals/reports/*.md must be gitignored"


# ------------------------------------- AC: t5's eval-runner test writes under tmp_path, not evals/reports


def test_t5_eval_runner_test_writes_to_tmp_path_not_real_reports_dir():
    # Compare mtimes, not just filenames: a stray routing-eval-<today>.* file already on disk
    # would otherwise hide a same-day overwrite, since an untracked file's `git status` line and
    # its directory listing entry look identical whether or not its content just changed.
    reports = ROOT / "evals" / "reports"
    before = {p: p.stat().st_mtime_ns for p in reports.glob("*")} if reports.exists() else {}

    r = _run_pytest_bounded(
        [
            "tests/integration/test_t5_frontend_e2e.py::test_eval_runner_stub_backend_produces_report",
            "-q", "-p", "no:cacheprovider",
        ],
        env=_clean_env(),
        timeout=60,
    )
    assert r.returncode == 0, r.stdout[-2000:]

    after = {p: p.stat().st_mtime_ns for p in reports.glob("*")} if reports.exists() else {}
    new_or_changed = {p.name for p in after if before.get(p) != after[p]}
    assert not new_or_changed, (
        "test_eval_runner_stub_backend_produces_report must pass --out under tmp_path; it wrote "
        f"to these paths in evals/reports/: {new_or_changed}"
    )


# ------------------------------------- AC: stray routing-eval files removed; .gitkeep kept


def test_stray_routing_eval_report_files_are_gone_but_gitkeep_remains():
    reports = ROOT / "evals" / "reports"
    stray = sorted(p.name for p in reports.glob("routing-eval-*"))
    assert stray == [], f"stray eval report files should have been deleted: {stray}"
    assert (reports / ".gitkeep").exists(), "evals/reports/.gitkeep must be kept"


# ------------------------------------- AC: suite-spawning tests skip themselves under GUM_NESTED_SUITE


def test_suite_spawning_tests_skip_themselves_when_already_nested():
    start = time.time()
    r = _run_pytest_bounded(
        [THIS_FILE + "::test_full_suite_subprocess_stays_green_and_leaves_no_new_git_changes", T5_SUITE_SPAWN_NODEID, "-q"],
        env=_clean_env(GUM_NESTED_SUITE="1"),
        timeout=25,
    )
    elapsed = time.time() - start

    assert r.returncode == 0, r.stdout[-2000:]
    assert "2 skipped" in r.stdout, (
        "both suite-spawning tests must skip themselves when GUM_NESTED_SUITE is already set:\n"
        f"{r.stdout[-2000:]}"
    )
    assert elapsed < 20, (
        "skipping should be near-instant; taking this long means a nested full-suite subprocess "
        "was actually spawned instead of skipped"
    )
