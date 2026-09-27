"""Unit tests for tests/live/test_live.py's skip-gating and fixture recording (PLAN T13).

These call the live test functions directly instead of running them under `pytest -m live`, so
their skip behavior is provable without a real key. See
tests/integration/test_fix3_live_scaffold.py for the top-level check that running the whole
`-m live` suite reports only skips.
"""

import json
import os

import pytest

from tests.live import conftest as live_conftest
from tests.live import test_live as live

JEV_GATED = [
    live.test_jev_real_response_validates_wire_format,
    live.test_jev_benign_prompt_passes_gate,
    live.test_jev_injection_prompt_is_blocked,
    live.test_jev_simple_prompt_routes_to_lite,
]

GEMINI_GATED = [
    live.test_gemini_models_list_contains_both_configured_ids,
    lambda: live.test_gemini_tier_streams_at_least_two_tokens_with_usage_metadata("flash"),
    lambda: live.test_gemini_tier_streams_at_least_two_tokens_with_usage_metadata("lite"),
    live.test_gemini_invalid_key_yields_error_then_done,
]


@pytest.mark.parametrize("fn", JEV_GATED, ids=[f.__name__ for f in JEV_GATED])
async def test_jev_gated_tests_skip_citing_typesafe_api_key(fn, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(pytest.skip.Exception, match="TYPESAFE_API_KEY"):
        await fn()


@pytest.mark.parametrize("fn", GEMINI_GATED, ids=[getattr(f, "__name__", "tier") for f in GEMINI_GATED])
async def test_gemini_gated_tests_skip_citing_google_api_key(fn, monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(pytest.skip.Exception, match="GOOGLE_API_KEY"):
        await fn()


@pytest.mark.parametrize("value", [None, ""], ids=["unset", "empty_string"])
def test_live_conftest_defaults_gum_env_file_to_repo_root_dotenv_when_unset_or_empty(value, monkeypatch):
    if value is None:
        monkeypatch.delenv("GUM_ENV_FILE", raising=False)
    else:
        monkeypatch.setenv("GUM_ENV_FILE", value)

    live_conftest._apply_default_gum_env_file(monkeypatch)

    assert os.environ.get("GUM_ENV_FILE") == str(live_conftest.REPO_ROOT_DOTENV)


def test_live_conftest_leaves_an_explicit_gum_env_file_value_untouched(tmp_path, monkeypatch):
    explicit = tmp_path / "custom.env"
    monkeypatch.setenv("GUM_ENV_FILE", str(explicit))

    live_conftest._apply_default_gum_env_file(monkeypatch)

    assert os.environ.get("GUM_ENV_FILE") == str(explicit)


def test_record_fixture_scrubs_request_id_and_writes_json(tmp_path):
    path = live.record_fixture(
        "benign_pass", {"request_id": "req-secret-123", "model": "jev-latest", "answers": {}},
        directory=tmp_path,
    )
    assert path.exists()
    written = json.loads(path.read_text())
    assert "request_id" not in written
    assert "req-secret-123" not in path.read_text()
    assert written["model"] == "jev-latest"
