import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import ConfigError, Settings
from app.providers import build_chat_models


def s(**kw):
    return Settings(_env_file=None, **kw)


async def test_fake_model_streams_offline_echo_word_by_word():
    model = build_chat_models(s(chat_provider="fake"))["lite"]
    chunks = [c async for c in model.astream([HumanMessage("hello big world")])]
    assert "".join(c.content for c in chunks) == "[offline:lite] You said: hello big world"
    assert len([c for c in chunks if c.content]) >= 6


async def test_fake_model_echoes_last_human_message_only():
    model = build_chat_models(s(chat_provider="fake"))["flash"]
    out = await model.ainvoke([HumanMessage("first"), AIMessage("reply"), HumanMessage("second")])
    assert out.content == "[offline:flash] You said: second"


async def test_fake_model_usage_metadata_on_last_chunk():
    model = build_chat_models(s(chat_provider="fake"))["flash"]
    chunks = [c async for c in model.astream([HumanMessage("a b c")])]
    usage = chunks[-1].usage_metadata
    assert usage is not None
    assert usage["input_tokens"] == 3
    assert usage["output_tokens"] == len("[offline:flash] You said: a b c".split())
    assert usage["total_tokens"] == usage["input_tokens"] + usage["output_tokens"]
    assert all(c.usage_metadata is None for c in chunks[:-1])


async def test_fake_model_is_reusable_across_calls():
    model = build_chat_models(s(chat_provider="fake"))["lite"]
    a = await model.ainvoke([HumanMessage("one")])
    b = await model.ainvoke([HumanMessage("two")])
    assert a.content.endswith("one") and b.content.endswith("two")


def test_build_chat_models_fake_returns_both_tiers_needing_no_key():
    models = build_chat_models(s(chat_provider="fake"))
    assert set(models) == {"flash", "lite"}
    assert models["flash"] is not models["lite"]


@pytest.mark.parametrize("key", [None, "", "AIzaxxxxxxxxxxxxxxxx"])
def test_build_chat_models_google_config_error_names_google_api_key(key):
    with pytest.raises(ConfigError, match="GOOGLE_API_KEY"):
        build_chat_models(s(chat_provider="google_genai", google_api_key=key))


def test_build_chat_models_google_builds_streaming_models_with_configured_ids():
    cfg = s(chat_provider="google_genai", google_api_key="AIzaTEST123")
    models = build_chat_models(cfg)
    assert all(isinstance(m, ChatGoogleGenerativeAI) for m in models.values())
    assert models["flash"].model.endswith(cfg.chat_model_flash)
    assert models["lite"].model.endswith(cfg.chat_model_lite)
    assert all(m.streaming is True for m in models.values())


def test_build_chat_models_google_lite_override_leaves_flash_alone():
    base = build_chat_models(s(chat_provider="google_genai", google_api_key="AIzaTEST123"))
    over = build_chat_models(
        s(chat_provider="google_genai", google_api_key="AIzaTEST123", chat_model_lite="custom-lite")
    )
    assert over["flash"].model == base["flash"].model
    assert over["lite"].model.endswith("custom-lite")
