"""Top-level integration tests for t2 / Fix 5: the live code paths must read keys from `.env`.

Public entry points used:
  `evals/run_eval.py` CLI (`--backend live`, `--backend live --judge`, `--backend stub`) --
                             invoked both in-process via `evals.run_eval.main(...)` (with the
                             classifier seam substituted, exactly like `test_fix3_live_scaffold.py`)
                             and as a real subprocess.
  `pytest -m live`         -- the live-marked suite, run as a subprocess, exactly like
                             `test_fix3_live_scaffold.py`'s "no keys -> only skips" check.
  `app.providers.build_classifier` -- the injectable seam the live eval path must call through,
                             patched here to substitute a real `TypeSafeClassifier` wired to an
                             offline `httpx2.MockTransport` (never the network).
  `README.md`              -- read as text, never executed.
  `pytest`, `git status --porcelain` -- the global-acceptance oracle, exactly like Fix 4.

Nothing here holds a real API key. `has_real_key()` rejects anything containing "xxxx", so a
fake-but-real-looking key like "ts_live_test1234567890abcdef" is used only to reach "the key was
read" code paths; the classifier that actually produces a report is always the MockTransport-backed
one substituted via monkeypatch, never a classifier that talks to a real host. Following
FIX_PLAN_2.md's rule, any fake `.env` this file places at the repo root is created only when none
already exists, and removed in a `finally`; an existing `.env` is never modified.
"""

import os
import re
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import httpx2
import pytest
from langchain_typesafe import TypeSafeClassifier

from app import providers
from app.jev_stub import make_stub_transport
from tests.nested_suite import is_nested_suite, nested_suite_env

ROOT = Path(__file__).resolve().parents[2]
THIS_FILE = "tests/integration/test_fix5_live_reads_dotenv.py"
# tests/integration/test_fix4_dotenv_isolation.py's own regression check asserts no real `.env`
# exists at the repo root; that exact "full suite is green with a fake .env present" property is
# already exhaustively covered there (t1's job), so this file's own "with a fake .env" run below
# ignores it too, rather than re-deriving a workaround for a precondition that file already owns.
FIX4_FILE = "tests/integration/test_fix4_dotenv_isolation.py"
RUN_EVAL = ROOT / "evals" / "run_eval.py"
README = ROOT / "README.md"

_FAKE_TYPESAFE_KEY = "ts_live_test1234567890abcdef"
_FAKE_GOOGLE_KEY = "AIzaTEST1234567890abcdefghijklmnopqrs"

# The four T13 live tests gated on TYPESAFE_API_KEY (see tests/live/test_live.py); used to prove
# the live tier is *attempted*, not skipped, without waiting on the four Gemini-gated ones (which
# have no offline-reachable base-url override).
LIVE_JEV_NODEIDS = [
    "tests/live/test_live.py::test_jev_real_response_validates_wire_format",
    "tests/live/test_live.py::test_jev_benign_prompt_passes_gate",
    "tests/live/test_live.py::test_jev_injection_prompt_is_blocked",
    "tests/live/test_live.py::test_jev_simple_prompt_routes_to_lite",
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
# AC: `run_eval.py --backend live` with `GUM_ENV_FILE` pointing at a temp env file holding a fake
# TypeSafe key gets past the missing-key check -- proven via the real `TypeSafeClassifier` on an
# `httpx2.MockTransport`, patched in through the `app.providers.build_classifier` seam -- and never
# touches the network.
# ------------------------------------------------------------------------------------------


def test_run_eval_backend_live_reads_typesafe_key_from_gum_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / "typesafe.env"
    env_file.write_text(f"TYPESAFE_API_KEY={_FAKE_TYPESAFE_KEY}\n")
    monkeypatch.setenv("GUM_ENV_FILE", str(env_file))
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    captured: dict = {}

    def fake_build_classifier(settings):
        captured["settings"] = settings
        return TypeSafeClassifier(
            model=settings.jev_model,
            api_key=_FAKE_TYPESAFE_KEY,
            base_url="https://typesafe.test",
            timeout=settings.guardrail_timeout_s,
            async_client=httpx2.AsyncClient(transport=make_stub_transport(latency_s=0)),
        )

    monkeypatch.setattr(providers, "build_classifier", fake_build_classifier)

    import evals.run_eval as ev

    out_dir = tmp_path / "out"
    code = ev.main(["--backend", "live", "--out", str(out_dir), "--concurrency", "4"])

    assert "settings" in captured, "run_eval --backend live must call app.providers.build_classifier"
    key = captured["settings"].typesafe_api_key
    assert key is not None and key.get_secret_value() == _FAKE_TYPESAFE_KEY, (
        "run_eval --backend live must read TYPESAFE_API_KEY from the .env file GUM_ENV_FILE points "
        "at, instead of forcing _env_file=None"
    )
    assert code == 0, "must get past the missing-key check once the key is read from the .env file"

    reports = list(out_dir.glob("*.md"))
    assert len(reports) == 1, list(out_dir.iterdir())


# ------------------------------------------------------------------------------------------
# AC: `run_eval.py --backend live` with `GUM_ENV_FILE` pointing at an empty temp file still exits
# non-zero, naming `TYPESAFE_API_KEY`.
# ------------------------------------------------------------------------------------------


def test_run_eval_backend_live_with_empty_gum_env_file_exits_nonzero_naming_typesafe_key(tmp_path):
    empty_env_file = tmp_path / "empty.env"
    empty_env_file.write_text("")

    r = _run_eval_cli("--backend", "live", env=_clean_env(GUM_ENV_FILE=str(empty_env_file)))
    out = r.stdout + r.stderr

    assert r.returncode != 0, out
    assert "TYPESAFE_API_KEY" in out, out


# ------------------------------------------------------------------------------------------
# AC: `run_eval.py --backend live --judge` with a temp env file holding only a fake TypeSafe key
# exits non-zero naming `GOOGLE_API_KEY`, without ever touching the network.
# ------------------------------------------------------------------------------------------


def test_run_eval_judge_with_only_typesafe_key_in_gum_env_file_exits_nonzero_naming_google_key(tmp_path):
    env_file = tmp_path / "typesafe_only.env"
    env_file.write_text(f"TYPESAFE_API_KEY={_FAKE_TYPESAFE_KEY}\n")

    env = _clean_env(
        GUM_ENV_FILE=str(env_file),
        TYPESAFE_BASE_URL="http://127.0.0.1:1",  # unroutable: a stray network attempt fails fast
    )
    r = _run_eval_cli("--backend", "live", "--judge", env=env, timeout=15)
    out = r.stdout + r.stderr

    assert r.returncode != 0, out
    assert "GOOGLE_API_KEY" in out, out
    assert "traceback" not in out.lower(), f"should be a clean refusal, not a crash:\n{out}"


# ------------------------------------------------------------------------------------------
# AC: `run_eval.py --backend stub` still ignores env files (`_env_file=None`), so stub reports
# stay deterministic regardless of what a `.env` (or `GUM_ENV_FILE`) might contain.
# ------------------------------------------------------------------------------------------


def test_run_eval_backend_stub_keeps_passing_env_file_none(tmp_path, monkeypatch):
    env_file = tmp_path / "stub_should_ignore.env"
    env_file.write_text(f"TYPESAFE_API_KEY={_FAKE_TYPESAFE_KEY}\nGOOGLE_API_KEY={_FAKE_GOOGLE_KEY}\n")
    monkeypatch.setenv("GUM_ENV_FILE", str(env_file))

    import evals.run_eval as ev

    real_settings_cls = ev.Settings
    calls: list[dict] = []

    class RecordingSettings(real_settings_cls):
        def __init__(self, **data):
            calls.append(dict(data))
            super().__init__(**data)

    monkeypatch.setattr(ev, "Settings", RecordingSettings)

    out_dir = tmp_path / "out"
    code = ev.main(["--backend", "stub", "--out", str(out_dir)])

    assert code == 0
    assert calls, "Settings must be constructed for --backend stub"
    assert calls[0].get("_env_file") is None, (
        "run_eval --backend stub must keep passing _env_file=None, unaffected by GUM_ENV_FILE"
    )


# ------------------------------------------------------------------------------------------
# AC: the live tier, run in a subprocess with `GUM_ENV_FILE` unset (the way a developer running
# `uv run pytest -m live` on purpose would leave it) and a fake `.env` at the repo root, does NOT
# skip the TypeSafe-key-gated tests: it attempts them, and they error on the blocked (unroutable)
# network, proving the opt-in reads the repo-root `.env` by default.
# ------------------------------------------------------------------------------------------


def test_live_tier_reads_repo_root_dotenv_by_default_and_attempts_jev_gated_tests():
    env = _clean_env(TYPESAFE_BASE_URL="http://127.0.0.1:1")
    env.pop("GUM_ENV_FILE", None)  # simulate a real user who never set this

    with _fake_dotenv_at_repo_root():
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "-m", "live", "-q", "-rs", "--no-header", *LIVE_JEV_NODEIDS],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=30,
        )

    counts = _summary_counts(r.stdout)
    assert counts["skipped"] == 0, (
        f"with a real .env at the repo root and GUM_ENV_FILE unset, the live tier must attempt "
        f"the TypeSafe-gated tests instead of skipping them, got {counts}:\n{r.stdout}"
    )
    assert counts["failed"] + counts["error"] > 0, (
        f"the attempted tests must error/fail against the blocked network, got {counts}:\n{r.stdout}"
    )


# ------------------------------------------------------------------------------------------
# AC: an explicit, user-set `GUM_ENV_FILE` pointing at a temp file with a fake real-looking key is
# still honoured by the live tier (the opt-in must not override a deliberate user choice).
# ------------------------------------------------------------------------------------------


def test_live_tier_honors_an_explicit_gum_env_file_and_attempts_jev_gated_tests(tmp_path):
    env_file = tmp_path / "typesafe.env"
    env_file.write_text(f"TYPESAFE_API_KEY={_FAKE_TYPESAFE_KEY}\n")

    env = _clean_env(GUM_ENV_FILE=str(env_file), TYPESAFE_BASE_URL="http://127.0.0.1:1")
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-m", "live", "-q", "-rs", "--no-header", *LIVE_JEV_NODEIDS],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=30,
    )

    counts = _summary_counts(r.stdout)
    assert counts["skipped"] == 0, f"expected the gated tests to be attempted, got {counts}:\n{r.stdout}"
    assert counts["failed"] + counts["error"] > 0, f"expected network failures, got {counts}:\n{r.stdout}"


# ------------------------------------------------------------------------------------------
# AC: `uv run pytest -m live` with an empty env file reports only skips naming missing keys, even
# when a real `.env` exists at the repo root -- proving the `GUM_ENV_FILE`-pointed-at-an-empty-file
# trick still hides the `.env` after the live tier gets its default-reading opt-in. This is also
# the mechanism `test_fix3_live_scaffold.py`'s "no keys -> only skips" check must adopt to keep
# passing once a real `.env` exists (FIX_PLAN_2.md Fix 5).
# ------------------------------------------------------------------------------------------


def test_live_marker_suite_with_empty_gum_env_file_only_skips_even_with_repo_root_dotenv(tmp_path):
    empty_env_file = tmp_path / "empty.env"
    empty_env_file.write_text("")

    with _fake_dotenv_at_repo_root():
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "-m", "live", "-q", "-rs", "--no-header"],
            cwd=ROOT, env=_clean_env(GUM_ENV_FILE=str(empty_env_file)), capture_output=True, text=True, timeout=60,
        )
    assert r.returncode == 0, r.stdout + r.stderr

    counts = _summary_counts(r.stdout)
    assert counts["skipped"] >= 6, f"expected >=6 skipped, got {counts}:\n{r.stdout}"
    assert counts["passed"] == 0, f"expected 0 passed, got {counts}:\n{r.stdout}"
    assert counts["failed"] == 0, f"expected 0 failed, got {counts}:\n{r.stdout}"
    assert counts["error"] == 0, f"expected 0 errors, got {counts}:\n{r.stdout}"

    reasons = [ln for ln in r.stdout.splitlines() if ln.startswith("SKIPPED")]
    for line in reasons:
        assert "TYPESAFE_API_KEY" in line or "GOOGLE_API_KEY" in line, (
            f"skip reason must name the missing key variable: {line}"
        )


# ------------------------------------------------------------------------------------------
# AC: README.md's live-mode section says keys go in `.env` (`cp .env.example .env && chmod 600
# .env`), explains why exported shell variables aren't read by the tests, and documents
# `GUM_ENV_FILE`.
# ------------------------------------------------------------------------------------------


def _live_section_text() -> str:
    lines = README.read_text().splitlines()
    heading_idx = next(
        (i for i, ln in enumerate(lines) if ln.lstrip().startswith("#") and "live" in ln.lower()),
        None,
    )
    assert heading_idx is not None, "README.md must have a heading naming 'live' mode"
    return "\n".join(lines[heading_idx:])


def test_readme_live_section_documents_env_file_setup_commands():
    rest = _live_section_text()
    assert "cp .env.example .env" in rest, "README's live section must document `cp .env.example .env`"
    assert "chmod 600 .env" in rest, "README's live section must document `chmod 600 .env`"


def test_readme_live_section_explains_exported_shell_vars_are_not_read_by_tests():
    rest = _live_section_text().lower()
    assert "export" in rest or "shell" in rest, (
        "README's live section must mention exported shell variables"
    )
    assert "test" in rest, "README's live section must explain this in relation to the tests"


def test_readme_live_section_documents_gum_env_file():
    rest = _live_section_text()
    assert "GUM_ENV_FILE" in rest, "README's live section must document GUM_ENV_FILE"


# ------------------------------------------------------------------------------------------
# AC (global acceptance): `uv run pytest -q` is green both with and without a fake `.env` at the
# repo root, and leaves `git status --porcelain` unchanged after a run.
# ------------------------------------------------------------------------------------------


def test_full_not_live_suite_with_fake_dotenv_is_green_and_leaves_git_status_unchanged():
    if is_nested_suite():
        pytest.skip("already running inside a nested full-suite invocation")

    before = _git_status()
    with _fake_dotenv_at_repo_root():
        r = subprocess.run(
            [
                sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                f"--ignore={THIS_FILE}", f"--ignore={FIX4_FILE}",
            ],
            cwd=ROOT, env=nested_suite_env(_clean_env()), capture_output=True, text=True, timeout=500,
        )
    after = _git_status()

    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-1000:]
    assert _failed_count(r.stdout) == 0, r.stdout[-4000:]
    assert after == before, f"full suite run left new/changed git-status lines: {after - before}"


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
