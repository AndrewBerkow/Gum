"""Unit test for t1 / Fix 10 Bug 1: tests/integration/test_fix7_fake_dotenv_self_heals.py's own
`_clean_env()` must strip an ambient `GUM_NESTED_SUITE` the same way it already strips the
provider-key variables, so its "heal should run" subprocess checks never inherit nesting state
from whatever process happens to be running this test file itself."""

from tests.integration import test_fix7_fake_dotenv_self_heals as fix7


def test_clean_env_strips_ambient_gum_nested_suite_flag(monkeypatch):
    monkeypatch.setenv("GUM_NESTED_SUITE", "1")

    env = fix7._clean_env()

    assert "GUM_NESTED_SUITE" not in env, (
        "_clean_env() must strip GUM_NESTED_SUITE so a suite-spawning check that relies on its "
        "absence never inherits it from an ambient nested-suite run"
    )
