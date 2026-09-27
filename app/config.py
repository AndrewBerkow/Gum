from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(Exception):
    """Raised when required configuration (e.g. a real API key) is missing."""


class Price(BaseModel):
    input_per_mtok: float
    output_per_mtok: float


def has_real_key(value: "str | SecretStr | None") -> bool:
    """A key is real when non-empty and not a placeholder (contains 'xxxx')."""
    if isinstance(value, SecretStr):
        value = value.get_secret_value()
    if not value or not value.strip():
        return False
    return "xxxx" not in value.lower()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    typesafe_api_key: SecretStr | None = None
    google_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("GOOGLE_API_KEY", "GEMINI_API_KEY")
    )

    jev_backend: Literal["live", "stub"] = "live"
    jev_model: str = "jev-latest"
    typesafe_base_url: str = "https://api.typesafe.ai"

    chat_provider: Literal["google_genai", "fake"] = "google_genai"
    chat_model_flash: str = "gemini-3.8-flash"
    chat_model_lite: str = "gemini-3.5-flash-lite"

    block_threshold: float = Field(default=0.7, ge=0, le=1)
    route_lite_threshold: float = Field(default=0.7, ge=0, le=1)
    guardrail_timeout_s: float = 2.0
    guardrail_context_turns: int = 2
    max_message_chars: int = 4000

    log_messages: bool = False
    decision_log_path: str = "logs/decisions.jsonl"
    model_prices: dict[str, Price] = {}
