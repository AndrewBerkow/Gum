"""FastAPI app: /api/chat (SSE), /api/devlog (SSE), /api/stats, /healthz and the static front end."""

import json
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.config import Settings
from app.devlog import DevLogBus
from app.graph import build_graph
from app.providers import build_chat_models, build_classifier
from app.sse import stream_turn
from app.telemetry import DecisionLog, Stats, TurnRecord

_LOOPBACK_HOSTS = ("127.0.0.1", "::1")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


class _LazyASGIApp:
    """Defers calling `builder` until the wrapper is used as an ASGI app."""

    def __init__(self, builder: Any) -> None:
        self._builder = builder
        self._app: Any = None

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if self._app is None:
            self._app = self._builder()
        await self._app(scope, receive, send)


def create_app(
    settings: Settings | None = None, graph: Any = None, log: DecisionLog | None = None
) -> FastAPI:
    settings = settings or Settings()
    if graph is None:
        # Raises ConfigError here when a live backend has no real key: never fall back to the stub.
        graph = build_graph(build_classifier(settings), build_chat_models(settings), settings)
    log = log or DecisionLog(settings.decision_log_path)
    stats = Stats()
    bus = DevLogBus()

    class ChatRequest(BaseModel):
        thread_id: str = Field(min_length=1)
        message: str = Field(min_length=1, max_length=settings.max_message_chars)
        tier: Literal["auto", "flash", "lite"] = "auto"

    async def record_turn(record: TurnRecord) -> None:
        stats.add(record)
        await log.append(record.to_log_dict(settings.log_messages))

    app = FastAPI(title="Gum")

    @app.post("/api/chat")
    async def chat(req: ChatRequest) -> EventSourceResponse:
        return EventSourceResponse(
            stream_turn(
                graph,
                req.thread_id,
                req.message,
                req.tier,
                settings=settings,
                on_record=record_turn,
                bus=bus,
            )
        )

    @app.get("/api/devlog")
    async def devlog_stream(request: Request, replay: str = "1") -> EventSourceResponse:
        if not settings.devlog_enabled:
            raise HTTPException(status_code=404)
        host = request.client.host if request.client else None
        if host not in _LOOPBACK_HOSTS:
            raise HTTPException(status_code=403)

        async def gen():
            async for name, data in bus.stream(replay=replay != "0"):
                yield {"event": name, "data": json.dumps(data)}

        return EventSourceResponse(gen())

    @app.get("/api/stats")
    async def get_stats() -> dict[str, Any]:
        return stats.summary()

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {
            "jev_backend": settings.jev_backend,
            "chat_provider": settings.chat_provider,
            "tiers": {"flash": settings.chat_model_flash, "lite": settings.chat_model_lite},
            "route_lite_threshold": settings.route_lite_threshold,
        }

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


app = _LazyASGIApp(create_app)
