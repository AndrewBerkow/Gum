"""Provider factories: the Jev classifier and the per-tier chat models."""

import json
import logging
from collections.abc import Iterator
from typing import Any

import httpx2
from langchain.chat_models import init_chat_model
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage
from langchain_core.messages.ai import UsageMetadata
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_typesafe import TypeSafeClassifier

from app import devlog
from app.config import ConfigError, Settings, has_real_key
from app.jev_stub import make_stub_transport
from app.state import Tier

log = logging.getLogger(__name__)

_STUB_BASE_URL = "https://typesafe.test"


async def _devlog_request_hook(request: httpx2.Request) -> None:
    """Publish the raw Jev request, with `Authorization` redacted, for the active turn."""
    try:
        body = json.loads(request.content) if request.content else None
    except Exception:
        log.exception("devlog request hook: could not parse Jev request body")
        body = None
    devlog.emit(
        "jev.request",
        method=request.method,
        url=str(request.url),
        body=body,
        headers=devlog.redact_headers(dict(request.headers)),
    )


async def _devlog_response_hook(response: httpx2.Response) -> None:
    """Publish the raw Jev response for the active turn."""
    try:
        await response.aread()
        body = response.json()
    except Exception:
        log.exception("devlog response hook: could not parse Jev response body")
        body = None
    devlog.emit(
        "jev.response",
        status=response.status_code,
        body=body,
        request_id=response.headers.get("x-typesafe-request-id"),
    )


_DEVLOG_HOOKS: dict[str, list[Any]] = {
    "request": [_devlog_request_hook],
    "response": [_devlog_response_hook],
}


def build_classifier(settings: Settings) -> TypeSafeClassifier:
    """The real classifier: over the offline stub transport, or live with a real key."""
    if settings.jev_backend == "stub":
        return TypeSafeClassifier(
            model=settings.jev_model,
            api_key="stub-key",
            base_url=_STUB_BASE_URL,
            timeout=settings.guardrail_timeout_s,
            async_client=httpx2.AsyncClient(transport=make_stub_transport(), event_hooks=_DEVLOG_HOOKS),
        )
    if not has_real_key(settings.typesafe_api_key):
        raise ConfigError("TYPESAFE_API_KEY is missing or a placeholder; set a real key or JEV_BACKEND=stub")
    assert settings.typesafe_api_key is not None
    return TypeSafeClassifier(
        model=settings.jev_model,
        api_key=settings.typesafe_api_key.get_secret_value(),
        base_url=settings.typesafe_base_url,
        timeout=settings.guardrail_timeout_s,
        async_client=httpx2.AsyncClient(timeout=settings.guardrail_timeout_s, event_hooks=_DEVLOG_HOOKS),
    )


class FakeChatModel(BaseChatModel):
    """Offline chat model: echoes the last human message, streamed word by word."""

    tier: str

    @property
    def _llm_type(self) -> str:
        return "offline-fake"

    def _reply(self, messages: list[BaseMessage]) -> tuple[list[str], int]:
        text = next((str(m.content) for m in reversed(messages) if isinstance(m, HumanMessage)), "")
        return f"[offline:{self.tier}] You said: {text}".split(), len(text.split())

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        words, n_in = self._reply(messages)
        usage = UsageMetadata(input_tokens=n_in, output_tokens=len(words), total_tokens=n_in + len(words))
        message = AIMessage(" ".join(words), usage_metadata=usage)
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        words, n_in = self._reply(messages)
        for i, word in enumerate(words):
            is_last = i == len(words) - 1
            usage = (
                UsageMetadata(input_tokens=n_in, output_tokens=len(words), total_tokens=n_in + len(words))
                if is_last
                else None
            )
            content = word if i == 0 else f" {word}"
            # chunk_position="last" stops langchain appending an empty usage-less terminal chunk
            message = AIMessageChunk(
                content=content, usage_metadata=usage, chunk_position="last" if is_last else None
            )
            chunk = ChatGenerationChunk(message=message)
            if run_manager:
                run_manager.on_llm_new_token(content, chunk=chunk)
            yield chunk


def build_chat_models(settings: Settings) -> dict[Tier, BaseChatModel]:
    """Per-tier chat models: offline fakes, or Gemini via init_chat_model with streaming on."""
    if settings.chat_provider == "fake":
        return {"flash": FakeChatModel(tier="flash"), "lite": FakeChatModel(tier="lite")}
    if not has_real_key(settings.google_api_key):
        raise ConfigError("GOOGLE_API_KEY is missing or a placeholder; set a real key or CHAT_PROVIDER=fake")
    assert settings.google_api_key is not None
    api_key = settings.google_api_key.get_secret_value()
    ids: dict[Tier, str] = {"flash": settings.chat_model_flash, "lite": settings.chat_model_lite}
    return {
        tier: init_chat_model(model_id, model_provider="google_genai", streaming=True, api_key=api_key)
        for tier, model_id in ids.items()
    }
