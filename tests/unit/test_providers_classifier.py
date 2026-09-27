import pytest
from langchain_core.messages import HumanMessage
from langchain_typesafe import ClassifierResponse, TypeSafeClassifier

from app.config import ConfigError, Settings
from app.jev import build_request
from app.providers import build_classifier


def s(**kw):
    return Settings(_env_file=None, **kw)


async def test_build_classifier_stub_answers_without_any_key():
    classifier = build_classifier(s(jev_backend="stub"))
    assert isinstance(classifier, TypeSafeClassifier)
    resp = await classifier.ainvoke(build_request([HumanMessage("hi there")], 2))
    assert isinstance(resp, ClassifierResponse)
    assert set(resp.answers) == {"unsafe", "scope", "complexity"}


@pytest.mark.parametrize("key", [None, "", "  ", "ts_live_xxxxxxxxxxxx"])
def test_build_classifier_live_rejects_missing_or_placeholder_key(key):
    with pytest.raises(ConfigError, match="TYPESAFE_API_KEY"):
        build_classifier(s(jev_backend="live", typesafe_api_key=key))


def test_build_classifier_live_uses_settings_for_model_url_and_timeout():
    c = build_classifier(
        s(
            jev_backend="live",
            typesafe_api_key="ts_live_test123",
            jev_model="jev-x",
            typesafe_base_url="https://example.test",
            guardrail_timeout_s=3.0,
        )
    )
    assert c.model == "jev-x"
    assert c.base_url == "https://example.test"
    assert c.timeout == 3.0


def test_build_classifier_stub_async_client_has_devlog_event_hooks():
    classifier = build_classifier(s(jev_backend="stub"))
    hooks = classifier.async_client.event_hooks
    assert hooks.get("request") and hooks.get("response")


def test_build_classifier_live_async_client_has_devlog_hooks_and_configured_timeout():
    import httpx2

    classifier = build_classifier(
        s(jev_backend="live", typesafe_api_key="ts_live_test123", guardrail_timeout_s=3.5)
    )
    client = classifier.async_client
    assert client is not None
    assert client.timeout == httpx2.Timeout(3.5)
    hooks = client.event_hooks
    assert hooks.get("request") and hooks.get("response")
