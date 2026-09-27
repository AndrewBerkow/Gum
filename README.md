# Gum: Jev-gated, Jev-routed chat harness

See `PLAN.md` for the architecture and task list. Setup: `uv sync`, then `uv run pytest`.

## Spike: httpx2 offline transport

Checked on `httpx2` as installed by `langchain-typesafe==0.0.1a3`: `httpx2.MockTransport` exists and
`httpx2.AsyncClient(transport=httpx2.MockTransport(handler))` works, so no custom `AsyncBaseTransport`
subclass is needed. Offline tests inject that client via `TypeSafeClassifier(async_client=...)`.
