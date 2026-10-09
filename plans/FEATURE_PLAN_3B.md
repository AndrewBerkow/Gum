# Feature Plan 3b: fix the devlog `Stream` test helper

**One tiny task. Don't split it. Don't change app code.** `FEATURE_PLAN_3.md` is implemented (commits `f709cf5`…`4e4d810`): the console starts empty on reload, the Clear button works, `/clear` shares the reset, and `/api/devlog?replay=0` works. 19 of its 20 top-level tests pass. The one failure is a bug in the test file's own helper, as confirmed in tdd-execute run `5b56b84e`'s `t1/diagnosis.md`.

A real `.env` exists in the developer's checkout: don't touch it, and make no real API calls.

## The bug
`tests/integration/test_feat7_console_clear.py::test_devlog_replay_0_skips_history_then_delivers_a_new_turns_events` fails with `httpx.StreamConsumed` at the second `read_until` call (around line 208 → 263). The `Stream` helper calls `self._resp.aiter_lines()` again on every `read_until`, but an httpx streaming response can only be iterated once. The first phase already proves the server skips history. The second phase (a new turn's events arrive on the same stream) never gets checked.

## Fix
**This task may edit `tests/integration/test_feat7_console_clear.py`**, for this helper only. Create the line iterator once, e.g. store `self._lines = self._resp.aiter_lines()` when the stream opens, and have `read_until` keep consuming that same iterator, with its existing timeout behaviour. Don't weaken, remove or skip any assertion. The test must still prove that `?replay=0` delivers **no** history and then **exactly one** new turn (`turn.start` … `turn.end`).

`test_feat7_console_clear.py` was never committed by the previous run. It gets committed as part of this task.

## Tests first (`tests/integration/test_feat8_stream_helper.py`)
- A subprocess run of `pytest tests/integration/test_feat7_console_clear.py -q` gives 0 failures, with at least 5 passed.
- The `Stream` helper in `test_feat7_console_clear.py` calls `aiter_lines()` at most once per stream (a source check is fine).

## Test command (keep it fast)
`uv run pytest tests/integration/test_feat8_stream_helper.py tests/integration/test_feat7_console_clear.py tests/integration/test_feat3_console_ui.py -q`

## Accept when
All of those pass.
