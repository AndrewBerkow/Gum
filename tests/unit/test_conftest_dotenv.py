"""Unit tests for tests/conftest.py: setting GUM_ENV_FILE="" at import time (t1 / Fix 4), and the
pytest_sessionstart self-heal hook for a leftover marked repo-root .env (t1 / Fix 7)."""

import os
import sys

from tests.fake_dotenv import MARKER


def test_reimporting_tests_conftest_sets_gum_env_file_to_empty_string(monkeypatch):
    monkeypatch.delenv("GUM_ENV_FILE", raising=False)
    for name in list(sys.modules):
        if name == "tests.conftest":
            del sys.modules[name]

    import tests.conftest  # noqa: F401

    assert os.environ.get("GUM_ENV_FILE") == ""


def test_sessionstart_heals_marked_repo_root_dotenv_unless_nested(tmp_path, monkeypatch):
    import tests.conftest as conftest

    target = tmp_path / ".env"
    target.write_text(f"{MARKER}\nTYPESAFE_API_KEY=ts_live_test1234567890abcdef\n")
    monkeypatch.setattr(conftest, "_REPO_ROOT_DOTENV", target)

    monkeypatch.setenv("GUM_NESTED_SUITE", "1")
    conftest.pytest_sessionstart(None)
    assert target.exists(), "GUM_NESTED_SUITE=1 must suppress the self-heal hook"

    monkeypatch.delenv("GUM_NESTED_SUITE", raising=False)
    conftest.pytest_sessionstart(None)
    assert not target.exists(), "a non-nested session start must heal the marked leftover file"
