"""Feature 8 (FEATURE_PLAN_3B): the devlog `Stream` test helper iterates `aiter_lines()` once.

An httpx streaming response can only be iterated once, so a helper that calls `aiter_lines()`
on every `read_until` raises `httpx.StreamConsumed` on the second call. These tests guard the fix
in `tests/integration/test_feat7_console_clear.py` from the outside: a source check on the helper
and a subprocess run of that file. No app code is touched and no real API calls are made.
"""

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

from tests.nested_suite import nested_suite_env

ROOT = Path(__file__).resolve().parent.parent.parent
FEAT7 = ROOT / "tests" / "integration" / "test_feat7_console_clear.py"
REPLAY_TEST = "test_devlog_replay_0_skips_history_then_delivers_a_new_turns_events"


def _clean_env() -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("TYPESAFE_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY")
        and not k.startswith(("LANGCHAIN_", "LANGSMITH_"))
    }
    env["LANGCHAIN_TRACING_V2"] = "false"
    env["LANGSMITH_TRACING"] = "false"
    return nested_suite_env(env)


def _run_feat7(*extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(FEAT7.relative_to(ROOT)), "-q", *extra],
        cwd=ROOT,
        env=_clean_env(),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def _stream_class() -> ast.ClassDef:
    tree = ast.parse(FEAT7.read_text())
    return next(
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Stream"
    )


def _aiter_lines_calls_by_method(cls: ast.ClassDef) -> dict[str, int]:
    counts = {}
    for fn in cls.body:
        if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            counts[fn.name] = sum(
                1
                for n in ast.walk(fn)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "aiter_lines"
            )
    return counts


def _assert_replay_0_test_keeps_its_assertions():
    """No assertion weakened or removed: no history, then exactly one new turn."""
    tree = ast.parse(FEAT7.read_text())
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
        and n.name == REPLAY_TEST
    )
    src = ast.get_source_segment(FEAT7.read_text(), fn)
    assert "replay=0" in src
    # "no history": the first read_until must time out empty and no events are held
    assert "assert not replayed" in src and "assert stream.events == []" in src
    # "exactly one new turn": waits for a turn.end, then exactly one turn.start / turn_id
    assert "_turn_ends(evs) >= 1" in src and "assert ok" in src
    assert 'names[0] == "turn.start" and names.count("turn.start") == 1' in src
    assert 'len({d["turn_id"] for _, d in stream.events}) == 1' in src
    assert src.count("read_until(") == 2
    assert not any(
        isinstance(d, ast.Attribute | ast.Call) and "skip" in ast.unparse(d)
        for d in fn.decorator_list
    )


def test_stream_helper_calls_aiter_lines_at_most_once_per_stream_not_per_read_until():
    counts = _aiter_lines_calls_by_method(_stream_class())
    assert counts.get("read_until", 0) == 0, (
        "read_until re-creates the aiter_lines() iterator on every call (httpx.StreamConsumed)"
    )
    assert sum(counts.values()) <= 1, f"aiter_lines() called more than once: {counts}"


def test_stream_helper_creates_its_line_iterator_once_when_the_stream_opens():
    counts = _aiter_lines_calls_by_method(_stream_class())
    assert counts.get("open", 0) == 1 or counts.get("__init__", 0) == 1, (
        f"the Stream helper must create its aiter_lines() iterator once at open: {counts}"
    )


def test_feat7_console_clear_suite_has_no_failures_and_at_least_5_passed():
    r = _run_feat7()
    out = r.stdout + r.stderr
    assert r.returncode == 0, out[-3000:]
    assert not re.search(r"\d+ failed", out), out[-3000:]
    m = re.search(r"(\d+) passed", out)
    assert m and int(m.group(1)) >= 5, out[-3000:]


def test_devlog_replay_0_test_passes_and_is_not_skipped_or_deselected():
    r = _run_feat7("-k", REPLAY_TEST, "-rs")
    out = r.stdout + r.stderr
    assert r.returncode == 0, out[-3000:]
    assert "StreamConsumed" not in out
    assert re.search(r"\b1 passed\b", out), out[-3000:]
    assert "skipped" not in out
    _assert_replay_0_test_keeps_its_assertions()
