import pytest
from pydantic import ValidationError

from app.config import ConfigError, Settings, has_real_key


def test_defaults():
    s = Settings(_env_file=None)
    assert s.jev_backend == "live" and s.block_threshold == 0.7
    assert s.chat_model_lite == "gemini-3.5-flash-lite"
    assert s.model_prices == {} and s.google_api_key is None


def test_env_override(monkeypatch):
    monkeypatch.setenv("CHAT_MODEL_LITE", "x")
    monkeypatch.setenv("GUARDRAIL_TIMEOUT_S", "5")
    s = Settings(_env_file=None)
    assert s.chat_model_lite == "x" and s.guardrail_timeout_s == 5.0


@pytest.mark.parametrize("field", ["block_threshold", "route_lite_threshold"])
@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_thresholds_bounds(field, bad):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: bad})


def test_model_prices(monkeypatch):
    monkeypatch.setenv("MODEL_PRICES", '{"m":{"input_per_mtok":1,"output_per_mtok":2}}')
    assert Settings(_env_file=None).model_prices["m"].output_per_mtok == 2
    monkeypatch.setenv("MODEL_PRICES", "{bad")
    with pytest.raises(ValueError):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    "v,e", [("ts_live_xxxx", False), ("AIzaxxxxxx", False), ("", False), (None, False), ("ts_live_abc123", True)]
)
def test_has_real_key(v, e):
    assert has_real_key(v) is e


def test_has_real_key_accepts_secretstr():
    from pydantic import SecretStr

    assert has_real_key(SecretStr("ts_live_abc123")) is True
    assert has_real_key(SecretStr("")) is False


def test_config_error():
    assert issubclass(ConfigError, Exception)


def test_gemini_fallback(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaTEST123")
    assert Settings(_env_file=None).google_api_key.get_secret_value() == "AIzaTEST123"


def test_settings_reads_key_from_custom_gum_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / "custom.env"
    env_file.write_text("TYPESAFE_API_KEY=ts_test_fromfile_1234567890\n")
    monkeypatch.setenv("GUM_ENV_FILE", str(env_file))

    assert Settings().typesafe_api_key.get_secret_value() == "ts_test_fromfile_1234567890"


def test_settings_reads_no_file_when_gum_env_file_is_empty_string(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("TYPESAFE_API_KEY=ts_test_shouldnotload_123\n")
    monkeypatch.setenv("GUM_ENV_FILE", "")

    assert Settings().typesafe_api_key is None
