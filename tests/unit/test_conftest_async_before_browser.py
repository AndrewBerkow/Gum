"""Unit tests for tests/conftest.py's pytest_collection_modifyitems: within a module, coroutine
tests run before tests that use the sync-Playwright `browser`/`page` fixtures, because the
module-scoped sync Playwright fixture leaves an event loop running in the thread and would make
every later async test fail with "Runner.run() cannot be called from a running event loop"."""

from types import SimpleNamespace

import tests.conftest as conftest


def _item(name, module, *, fixtures=(), is_async=False):
    async def coro():
        pass

    def sync():
        pass

    return SimpleNamespace(
        name=name,
        module=module,
        fixturenames=list(fixtures),
        obj=coro if is_async else sync,
    )


def _names(items):
    return [i.name for i in items]


def test_async_tests_move_ahead_of_browser_tests_within_a_module():
    m = object()
    items = [
        _item("ui1", m, fixtures=["page", "browser"]),
        _item("ui2", m, fixtures=["page"]),
        _item("api1", m, is_async=True, fixtures=["offline_url"]),
        _item("api2", m, is_async=True),
    ]
    conftest.pytest_collection_modifyitems(None, items)
    assert _names(items) == ["api1", "api2", "ui1", "ui2"]


def test_order_is_otherwise_stable_and_modules_are_not_interleaved():
    a, b = object(), object()
    items = [
        _item("a_sync", a),
        _item("a_ui", a, fixtures=["page"]),
        _item("b_ui", b, fixtures=["browser"]),
        _item("b_async", b, is_async=True),
        _item("b_sync", b),
    ]
    conftest.pytest_collection_modifyitems(None, items)
    assert _names(items) == ["a_sync", "a_ui", "b_async", "b_sync", "b_ui"]
