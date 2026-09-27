"""Unit tests for README.md's "Live Jev demo" section (t2 / FEATURE_PLAN.md Task 4).

Each test reads the real README.md and looks at the "Live Jev demo" section only, the same way
tests/unit/test_readme_t13.py checks its own sections.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _readme() -> str:
    return (ROOT / "README.md").read_text()


def _demo_section() -> str:
    """The text from the "Live Jev demo" heading to the next heading."""
    lines = _readme().splitlines()
    start = next(
        i for i, ln in enumerate(lines) if ln.lstrip().startswith("#") and "live jev demo" in ln.lower()
    )
    end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("#")), len(lines))
    return "\n".join(lines[start:end])


def test_readme_has_live_jev_demo_heading():
    lines = _readme().splitlines()
    assert any(
        ln.lstrip().startswith("#") and "live jev demo" in ln.lower() for ln in lines
    ), "README.md must have a 'Live Jev demo' heading"
