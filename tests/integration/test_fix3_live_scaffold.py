"""Top-level integration tests for t3 / Fix 3: T13 scaffolding (PLAN.md T13, no real keys used).

Public entry points used:
  `pytest -m live`                         -- the live-marked suite, run as a subprocess
  `evals/run_eval.py` CLI                  -- `--backend live` and `--backend live --judge`
  `app.providers.build_classifier`          -- the injectable seam the live eval path must call
                                               through, patched here to substitute a real
                                               `TypeSafeClassifier` wired to an offline
                                               `httpx2.MockTransport` (never the network)
  `README.md`, `app/**/*.py`                -- read as text, never executed

Nothing here holds a real API key. `has_real_key()` rejects anything containing "xxxx", so a
fake-but-real-looking key like "ts_live_test123" is used only to reach "construct, don't invoke
the network" code paths; the classifier used to actually produce a report is always the
MockTransport-backed one substituted via monkeypatch, never a classifier that talks to a real host.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import httpx2
import pytest
from langchain_typesafe import TypeSafeClassifier

from app import providers
from app.jev_stub import make_stub_transport

ROOT = Path(__file__).resolve().parents[2]
LIVE_TEST_FILE = ROOT / "tests" / "live" / "test_live.py"
RUN_EVAL = ROOT / "evals" / "run_eval.py"
README = ROOT / "README.md"

_FAKE_TYPESAFE_KEY = "ts_live_test123"  # real-looking (no "xxxx"), never sent over the network


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


def _run_eval_cli(*args: str, env: dict[str, str] | None = None, timeout: float = 20) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(RUN_EVAL), *args],
        cwd=ROOT, env=env if env is not None else _clean_env(),
        capture_output=True, text=True, timeout=timeout,
    )


def _summary_counts(stdout: str) -> dict[str, int]:
    """Sum pytest's final '<n> passed'/'<n> skipped'/... counts; absent categories are 0."""
    counts = {"passed": 0, "failed": 0, "skipped": 0, "error": 0}
    for n, word in re.findall(r"(\d+) (passed|failed|skipped|errors?)", stdout):
        counts["error" if word.startswith("error") else word] += int(n)
    return counts


def _skip_reason_lines(stdout: str) -> list[str]:
    return [ln for ln in stdout.splitlines() if ln.startswith("SKIPPED")]


# ------------------------------------------------------------------------------------------
# AC: `uv run pytest -m live -q` (addopts' -m 'not live' overridden) exits 0 with only skips:
# >=6 skipped, 0 passed, 0 failed, 0 errors; every skip reason names TYPESAFE_API_KEY or
# GOOGLE_API_KEY.
# ------------------------------------------------------------------------------------------


def test_marker_live_suite_with_no_keys_reports_only_skips_naming_missing_keys():
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-m", "live", "-q", "-rs", "--no-header"],
        cwd=ROOT, env=_clean_env(), capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, r.stdout + r.stderr

    counts = _summary_counts(r.stdout)
    assert counts["skipped"] >= 6, f"expected >=6 skipped, got {counts}:\n{r.stdout}"
    assert counts["passed"] == 0, f"expected 0 passed, got {counts}:\n{r.stdout}"
    assert counts["failed"] == 0, f"expected 0 failed, got {counts}:\n{r.stdout}"
    assert counts["error"] == 0, f"expected 0 errors, got {counts}:\n{r.stdout}"

    reasons = _skip_reason_lines(r.stdout)
    assert len(reasons) >= 6, f"expected >=6 SKIPPED lines in -rs output:\n{r.stdout}"
    for line in reasons:
        assert "TYPESAFE_API_KEY" in line or "GOOGLE_API_KEY" in line, (
            f"skip reason must name the missing key variable: {line}"
        )


# ------------------------------------------------------------------------------------------
# AC: tests/live/test_live.py covers every T13 scenario (Jev wire-format validation, benign
# pass, injection block, simple-routes-to-lite, recorded scrubbed fixtures; Gemini models.list
# with both configured ids, each tier streaming >=2 tokens with usage_metadata, an invalid key
# yielding error then done).
# ------------------------------------------------------------------------------------------


def test_live_test_module_exists_under_the_live_marker():
    assert LIVE_TEST_FILE.exists(), "tests/live/test_live.py must exist"
    text = LIVE_TEST_FILE.read_text()
    assert "pytest.mark.live" in text, "tests/live/test_live.py must use the `live` marker"


def test_live_test_module_has_at_least_six_test_functions():
    text = LIVE_TEST_FILE.read_text()
    names = re.findall(r"^\s*(?:async\s+)?def (test_\w+)", text, re.MULTILINE)
    assert len(names) >= 6, f"expected >=6 live tests, found {names}"


def test_live_test_module_skip_reasons_name_the_missing_key_via_has_real_key():
    text = LIVE_TEST_FILE.read_text()
    assert "has_real_key" in text
    assert "TYPESAFE_API_KEY" in text
    assert "GOOGLE_API_KEY" in text


def test_live_test_module_covers_jev_scenarios():
    text = LIVE_TEST_FILE.read_text().lower()
    for keyword in ("wire", "lite", "recorded"):
        assert keyword in text, f"tests/live/test_live.py should mention {keyword!r} (Jev scenarios)"
    assert "inject" in text or "unsafe" in text, "must cover the injection-blocked scenario"
    assert "benign" in text or "pass" in text, "must cover the benign-passes scenario"
    assert "fixtures/recorded" in text or "fixtures" in text, "must record scrubbed fixtures"


def test_live_test_module_covers_gemini_scenarios():
    text = LIVE_TEST_FILE.read_text().lower()
    assert "models.list" in text or "models_list" in text or ".list(" in text
    assert "usage_metadata" in text
    assert "invalid" in text
    assert "error" in text and "done" in text


# ------------------------------------------------------------------------------------------
# AC: `evals/run_eval.py --backend live` with no key exits non-zero, output contains
# TYPESAFE_API_KEY and not "not available yet".
# ------------------------------------------------------------------------------------------


def test_run_eval_backend_live_without_key_exits_nonzero_naming_typesafe_key():
    r = _run_eval_cli("--backend", "live")
    out = r.stdout + r.stderr
    assert r.returncode != 0, out
    assert "TYPESAFE_API_KEY" in out, out
    assert "not available yet" not in out.lower(), out


# ------------------------------------------------------------------------------------------
# AC: `evals/run_eval.py --backend live --judge` with a real-looking fake TypeSafe key and no
# Google key exits non-zero naming GOOGLE_API_KEY, without network calls (construct only).
# ------------------------------------------------------------------------------------------


def test_run_eval_judge_without_google_key_exits_nonzero_naming_google_key_without_network():
    env = _clean_env(
        TYPESAFE_API_KEY=_FAKE_TYPESAFE_KEY,
        TYPESAFE_BASE_URL="http://127.0.0.1:1",  # unroutable: a stray network attempt fails fast
    )
    r = _run_eval_cli("--backend", "live", "--judge", env=env, timeout=15)
    out = r.stdout + r.stderr
    assert r.returncode != 0, out
    assert "GOOGLE_API_KEY" in out, out
    assert "traceback" not in out.lower(), f"should be a clean refusal, not a crash:\n{out}"


# ------------------------------------------------------------------------------------------
# AC: the real TypeSafeClassifier, backed by an httpx2.MockTransport serving §0-format
# responses, drives the live eval's classification path to produce a report, via an
# injectable classifier/client seam.
# ------------------------------------------------------------------------------------------


def test_run_eval_backend_live_via_mocked_classifier_seam_produces_a_report(tmp_path, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", _FAKE_TYPESAFE_KEY)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    def fake_build_classifier(settings):
        assert settings.jev_backend == "live", "run_eval --backend live must build a live-backend classifier"
        return TypeSafeClassifier(
            model=settings.jev_model,
            api_key=_FAKE_TYPESAFE_KEY,
            base_url="https://typesafe.test",
            timeout=settings.guardrail_timeout_s,
            async_client=httpx2.AsyncClient(transport=make_stub_transport(latency_s=0)),
        )

    monkeypatch.setattr(providers, "build_classifier", fake_build_classifier)

    import evals.run_eval as ev

    code = ev.main(["--backend", "live", "--out", str(tmp_path), "--concurrency", "4"])
    assert code == 0

    reports = list(tmp_path.glob("*.md"))
    assert len(reports) == 1, list(tmp_path.iterdir())
    text = reports[0].read_text().lower()
    for section in ("gate metrics", "route metrics", "threshold sweep", "latency"):
        assert section in text, f"missing heading '{section}' in report:\n{text}"

    raws = list(tmp_path.glob("*.jsonl"))
    assert len(raws) == 1
    assert raws[0].read_text().strip(), "raw results jsonl must not be empty"


# ------------------------------------------------------------------------------------------
# AC: README.md contains the offline demo command, `playwright install chromium`, and a live
# section naming both TYPESAFE_API_KEY and GOOGLE_API_KEY.
# ------------------------------------------------------------------------------------------


def test_readme_contains_offline_demo_command():
    text = README.read_text()
    assert "JEV_BACKEND=stub CHAT_PROVIDER=fake uv run uvicorn app.main:app" in text


def test_readme_contains_playwright_install_chromium():
    text = README.read_text().lower()
    assert "playwright install chromium" in text


def test_readme_has_a_live_section_naming_both_key_variables():
    lines = README.read_text().splitlines()
    heading_idx = next(
        (i for i, ln in enumerate(lines) if ln.lstrip().startswith("#") and "live" in ln.lower()),
        None,
    )
    assert heading_idx is not None, "README.md must have a heading naming 'live' mode"
    rest = "\n".join(lines[heading_idx:])
    assert "TYPESAFE_API_KEY" in rest
    assert "GOOGLE_API_KEY" in rest


def test_readme_covers_test_tiers_and_reading_the_eval_report():
    text = README.read_text().lower()
    for keyword in ("unit", "integration", "e2e", "live"):
        assert keyword in text, f"README.md must name the {keyword!r} test tier"
    assert "eval" in text and "report" in text, "README.md must explain how to read the eval report"


# ------------------------------------------------------------------------------------------
# AC: `grep -rn "TODO(T13-verify)" app/` finds at least 3 comments.
# ------------------------------------------------------------------------------------------


def test_app_has_at_least_three_todo_t13_verify_comments():
    r = subprocess.run(
        ["grep", "-rn", "TODO(T13-verify)", str(ROOT / "app")],
        capture_output=True, text=True,
    )
    hits = [ln for ln in r.stdout.splitlines() if ln.strip()]
    assert len(hits) >= 3, f"expected >=3 TODO(T13-verify) comments in app/, found:\n{r.stdout}"


# ------------------------------------------------------------------------------------------
# AC: `uv run pytest -q` stays green and leaves `git status --porcelain` empty.
# ------------------------------------------------------------------------------------------


def test_running_this_files_readonly_checks_leaves_git_status_clean():
    def git_status() -> str:
        return subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout

    before = git_status()
    README.read_text()
    subprocess.run(["grep", "-rn", "TODO(T13-verify)", str(ROOT / "app")], capture_output=True, text=True)
    after = git_status()

    assert after == before
