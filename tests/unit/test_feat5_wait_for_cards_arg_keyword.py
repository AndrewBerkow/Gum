"""Unit test for t1 MT1 (FEATURE_PLAN_2.md Task A): `wait_for_cards` in
`test_feat3_console_ui.py` must pass its `n` argument to `Page.wait_for_function` as the
keyword-only `arg=n`, not positionally -- Playwright 1.63.0's
`Page.wait_for_function(expression, *, arg=None, ...)` takes `arg` keyword-only, so a second
positional argument raises `TypeError` before the call ever reaches the page.
"""

import ast
from pathlib import Path

TARGET = Path(__file__).resolve().parents[2] / "tests" / "integration" / "test_feat3_console_ui.py"


def _wait_for_function_call_in_wait_for_cards() -> ast.Call:
    tree = ast.parse(TARGET.read_text(), filename=str(TARGET))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "wait_for_cards":
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "wait_for_function"
                ):
                    return inner
    raise AssertionError("no wait_for_function call found inside wait_for_cards")


def test_wait_for_cards_passes_arg_as_keyword():
    call = _wait_for_function_call_in_wait_for_cards()
    assert len(call.args) == 1, "wait_for_function must take only the expression positionally"
    keyword_names = {kw.arg for kw in call.keywords}
    assert "arg" in keyword_names, "the count must be passed as arg=n, not positionally"
