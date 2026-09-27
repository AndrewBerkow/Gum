"""Unit tests for tests.nested_suite, the GUM_NESTED_SUITE recursion guard (t2 / Fix 2)."""

from tests.nested_suite import is_nested_suite


def test_is_nested_suite_reflects_env_var(monkeypatch):
    monkeypatch.delenv("GUM_NESTED_SUITE", raising=False)
    assert is_nested_suite() is False

    monkeypatch.setenv("GUM_NESTED_SUITE", "1")
    assert is_nested_suite() is True
