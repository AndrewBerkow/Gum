"""Unit test for PLAN.md rule 6's `# TODO(T13-verify)` comments (t3 / Fix 3).

PLAN.md: "Where something isn't verified, write the code defensively and leave a
`# TODO(T13-verify): ...` comment. For example: the exact response header that carries
`request_id`, whether `gemini-3.8-flash` exists, and the real prices."
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _todo_lines() -> list[str]:
    lines = []
    for path in (ROOT / "app").rglob("*.py"):
        for line in path.read_text().splitlines():
            if "TODO(T13-verify)" in line:
                lines.append(line)
    return lines


def test_required_todo_t13_verify_topics_are_present():
    lines = _todo_lines()
    assert len(lines) >= 3, f"expected >=3 TODO(T13-verify) comments, found:\n{lines}"

    joined = "\n".join(lines).lower()
    assert "request_id" in joined and "header" in joined
    assert "gemini-3.8-flash" in joined
    assert "model_prices" in joined
