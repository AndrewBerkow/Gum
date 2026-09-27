"""Top-level integration tests for t2 / FEATURE_PLAN.md Task 4: the README "Live Jev demo"
section, and the invariant that the full non-live suite stays green with an unmarked
real-looking `.env` sitting at the repo root the way a developer's own checkout would have one.

Public entry points used:
  `README.md`  -- read as text, never executed.
  `pytest`, `git status --porcelain` -- the global-acceptance oracle, exactly like the existing
                  Fix 4 / Fix 5 / Fix 8 top-level tests.

Nothing here imports app code that talks to a network, and no real key is ever created. Following
FIX_PLAN_2.md's rule, this file never creates a repo-root `.env` unless none already exists, and
never touches (or deletes) a real one; see `tests.fake_dotenv.dotenv_present`.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.fake_dotenv import dotenv_present
from tests.nested_suite import is_nested_suite, nested_suite_env

ROOT = Path(__file__).resolve().parents[2]
THIS_FILE = "tests/integration/test_feat6_demo_ready.py"
README = ROOT / "README.md"


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


def _failed_count(stdout: str) -> int:
    m = re.search(r"(\d+) failed", stdout)
    return int(m.group(1)) if m else 0


def _git_status() -> set[str]:
    out = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    lines = {ln for ln in out.splitlines() if ln.strip()}
    return {ln for ln in lines if ".pytest_cache" not in ln}


def _unmarked_real_looking_dotenv_present():
    """Ensure a `.env` is present at the repo root for the duration of the block: reuse a
    developer's real one exactly as-is (never modified, never removed) if one already exists, or
    create+clean up a fake one via the shared tests.fake_dotenv helper otherwise. Never overwrites
    or deletes a real `.env`."""
    return dotenv_present(ROOT.joinpath(".env"))


def _demo_section_lines() -> list[str]:
    lines = README.read_text().splitlines()
    heading_idx = next(
        (i for i, ln in enumerate(lines) if ln.lstrip().startswith("#") and "live jev demo" in ln.lower()),
        None,
    )
    assert heading_idx is not None, "README.md must have a 'Live Jev demo' heading"
    next_heading_idx = next(
        (
            i
            for i, ln in enumerate(lines[heading_idx + 1 :], start=heading_idx + 1)
            if ln.lstrip().startswith("#")
        ),
        len(lines),
    )
    return lines[heading_idx:next_heading_idx]


def _demo_section_text() -> str:
    return "\n".join(_demo_section_lines())


# ------------------------------------------------------------------------------------------
# AC: README.md has a "Live Jev demo" section with the run command (a real .env, or
# JEV_BACKEND=stub CHAT_PROVIDER=fake offline).
# ------------------------------------------------------------------------------------------


def test_readme_demo_section_documents_the_live_run_command():
    section = _demo_section_text()
    assert "uv run uvicorn app.main:app --port 8000" in section, (
        "the demo section must document the live run command on port 8000"
    )


def test_readme_demo_section_documents_the_offline_run_command():
    section = _demo_section_text()
    assert "JEV_BACKEND=stub" in section and "CHAT_PROVIDER=fake" in section, (
        "the demo section must document the offline (JEV_BACKEND=stub CHAT_PROVIDER=fake) run "
        "command for demoing without real keys"
    )


# ------------------------------------------------------------------------------------------
# AC: the demo section has a 6-prompt demo script: simple, complex, injection, noise, a
# `/model flash` override, and `/stats`.
# ------------------------------------------------------------------------------------------


def test_readme_demo_section_lists_all_six_demo_prompts():
    section = _demo_section_text().lower()
    expected = ["simple", "complex", "injection", "noise", "/model flash", "/stats"]
    missing = [kw for kw in expected if kw not in section]
    assert not missing, f"demo section is missing these demo-script prompts/commands: {missing}"


# ------------------------------------------------------------------------------------------
# AC: the demo section explains what each console element means.
# ------------------------------------------------------------------------------------------


def test_readme_demo_section_explains_console_elements():
    section = _demo_section_text().lower()
    expected = ["badge", "probability", "threshold", "timing"]
    missing = [kw for kw in expected if kw not in section]
    assert not missing, f"demo section doesn't explain these console elements: {missing}"


# ------------------------------------------------------------------------------------------
# AC: the demo section explains confidence vs probability (PLAN.md §0: confidence measures
# distribution concentration, not the probability of the chosen label).
# ------------------------------------------------------------------------------------------


def test_readme_demo_section_explains_confidence_vs_probability():
    section = _demo_section_text().lower()
    assert "confidence" in section and "probability" in section, (
        "the demo section must explain confidence vs probability"
    )
    assert "concentrat" in section, (
        "the demo section must explain that confidence measures how concentrated the "
        "distribution is, not the probability of the chosen label (PLAN.md §0)"
    )


# ------------------------------------------------------------------------------------------
# AC (global acceptance): with an unmarked real-looking `.env` present at the repo root (created
# only if none exists, removed in finally, never touching an existing `.env`), the full non-live
# suite in a subprocess (GUM_NESTED_SUITE=1, --ignore for this file) gives 0 failures, and leaves
# `git status --porcelain` unchanged.
# ------------------------------------------------------------------------------------------


def test_full_not_live_suite_with_unmarked_real_looking_dotenv_present_is_green():
    if is_nested_suite():
        pytest.skip("already running inside a nested full-suite invocation")

    before = _git_status()
    with _unmarked_real_looking_dotenv_present():
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--ignore={THIS_FILE}"],
            cwd=ROOT, env=nested_suite_env(_clean_env()), capture_output=True, text=True, timeout=500,
        )
    after = _git_status()

    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-1000:]
    assert _failed_count(r.stdout) == 0, r.stdout[-4000:]
    assert after == before, f"full suite run left new/changed git-status lines: {after - before}"
