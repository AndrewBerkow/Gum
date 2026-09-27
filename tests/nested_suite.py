"""Shared guard against tests recursively spawning the full pytest suite.

A few integration tests run `pytest` (or the whole non-live suite) as a subprocess to prove
something about the suite as a whole. If two such tests exist and neither knows about the other,
each one's spawned child includes the other test file, which spawns another full-suite child, and
so on without bound. `GUM_NESTED_SUITE=1` marks a process as already being such a child: a
suite-spawning test checks `is_nested_suite()` and skips itself instead of spawning again, and
passes `nested_suite_env(...)` to its own child so the marker propagates one level further.
"""

import os

_ENV_VAR = "GUM_NESTED_SUITE"


def is_nested_suite() -> bool:
    return bool(os.environ.get(_ENV_VAR))


def nested_suite_env(base_env: dict[str, str]) -> dict[str, str]:
    return {**base_env, _ENV_VAR: "1"}
