import os

import pytest

_CLEARED_PREFIXES = ("LANGCHAIN_", "LANGSMITH_")
_CLEARED_NAMES = ("TYPESAFE_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Clear tracing variables and provider keys so tests never see a real key."""
    for name in list(os.environ):
        if name in _CLEARED_NAMES or name.startswith(_CLEARED_PREFIXES):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
