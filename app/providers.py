"""Provider factories: the Jev classifier and the per-tier chat models."""

import httpx2
from langchain_typesafe import TypeSafeClassifier

from app.config import ConfigError, Settings, has_real_key
from app.jev_stub import make_stub_transport

_STUB_BASE_URL = "https://typesafe.test"


def build_classifier(settings: Settings) -> TypeSafeClassifier:
    """The real classifier: over the offline stub transport, or live with a real key."""
    if settings.jev_backend == "stub":
        return TypeSafeClassifier(
            model=settings.jev_model,
            api_key="stub-key",
            base_url=_STUB_BASE_URL,
            timeout=settings.guardrail_timeout_s,
            async_client=httpx2.AsyncClient(transport=make_stub_transport()),
        )
    if not has_real_key(settings.typesafe_api_key):
        raise ConfigError("TYPESAFE_API_KEY is missing or a placeholder; set a real key or JEV_BACKEND=stub")
    assert settings.typesafe_api_key is not None
    return TypeSafeClassifier(
        model=settings.jev_model,
        api_key=settings.typesafe_api_key.get_secret_value(),
        base_url=settings.typesafe_base_url,
        timeout=settings.guardrail_timeout_s,
    )
