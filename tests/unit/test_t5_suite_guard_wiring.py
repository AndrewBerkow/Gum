"""Unit tests for the GUM_NESTED_SUITE guard wired into test_t5_frontend_e2e.py (t2 / Fix 2).

These load the real integration test file as an isolated module, call its test function
directly, and stub out subprocess.run on that module so no real subprocess -- let alone a real
nested suite run -- is ever spawned here, even before the skip guard exists.
"""

import subprocess

import pytest

from tests.unit._load_test_module import load


def _load_t5_with_stubbed_subprocess_run(monkeypatch):
    t5 = _load_t5()
    monkeypatch.setattr(
        t5.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "", "")
    )
    return t5


def _load_t5():
    return load(
        "tests/integration/test_t5_frontend_e2e.py", "unit_test_view_of_test_t5_frontend_e2e"
    )


def test_full_suite_spawn_test_skips_when_already_nested(monkeypatch):
    monkeypatch.setenv("GUM_NESTED_SUITE", "1")
    t5 = _load_t5_with_stubbed_subprocess_run(monkeypatch)

    with pytest.raises(pytest.skip.Exception):
        t5.test_full_not_live_suite_green_with_no_env_file()
