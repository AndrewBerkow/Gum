import os

import pytest

# Several integration tests spawn `pytest` as a subprocess and parse its captured stdout (e.g.
# for "SKIPPED ..." summary lines). A forced-color terminal (FORCE_COLOR set in the outer shell)
# would otherwise prefix that output with ANSI escapes and break plain-text matching, in this
# process and in any subprocess that inherits `os.environ`.
os.environ.setdefault("NO_COLOR", "1")

# Offline tests must never read the developer's .env: GUM_ENV_FILE="" tells Settings() (and every
# subprocess these tests spawn -- uvicorn, nested pytest, the eval CLI -- since they inherit
# os.environ) to read no env file, before any Settings is ever built.
os.environ.setdefault("GUM_ENV_FILE", "")

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
