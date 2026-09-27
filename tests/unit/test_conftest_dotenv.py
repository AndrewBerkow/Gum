"""Unit test for tests/conftest.py setting GUM_ENV_FILE="" at import time (t1 / Fix 4)."""

import os
import sys


def test_reimporting_tests_conftest_sets_gum_env_file_to_empty_string(monkeypatch):
    monkeypatch.delenv("GUM_ENV_FILE", raising=False)
    for name in list(sys.modules):
        if name == "tests.conftest":
            del sys.modules[name]

    import tests.conftest  # noqa: F401

    assert os.environ.get("GUM_ENV_FILE") == ""
