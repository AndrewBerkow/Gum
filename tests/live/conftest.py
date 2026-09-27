"""Opt-in for the live tier: default GUM_ENV_FILE to the repo-root .env (FIX_PLAN_2.md Fix 5).

tests/conftest.py sets GUM_ENV_FILE="" whenever it's unset, so offline tests never read a .env.
That default would otherwise stop `uv run pytest -m live` from finding a real .env when a developer
runs it on purpose without exporting GUM_ENV_FILE themselves. This fixture is autouse but scoped to
this directory, so it only runs for tests actually collected under tests/live/ -- never for the
offline suite -- and only fills in the repo-root .env when GUM_ENV_FILE is falsy (unset or "").  An
explicit non-empty value (including one pointing at an empty file, the trick used to hide .env on
purpose, e.g. in test_fix3_live_scaffold.py) is left untouched.
"""

import os
from pathlib import Path

import pytest

REPO_ROOT_DOTENV = Path(__file__).resolve().parents[2] / ".env"


def _apply_default_gum_env_file(monkeypatch) -> None:
    if not os.environ.get("GUM_ENV_FILE"):
        monkeypatch.setenv("GUM_ENV_FILE", str(REPO_ROOT_DOTENV))


@pytest.fixture(autouse=True)
def _default_gum_env_file_to_repo_root_dotenv(monkeypatch):
    _apply_default_gum_env_file(monkeypatch)
