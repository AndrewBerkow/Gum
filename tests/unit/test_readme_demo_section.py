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


def test_readme_demo_section_has_live_run_command():
    section = _demo_section()
    assert "uv run uvicorn app.main:app --port 8000" in section, (
        "the demo section must document the live run command on port 8000"
    )


def test_readme_demo_section_has_offline_run_command():
    section = _demo_section()
    assert "JEV_BACKEND=stub" in section and "CHAT_PROVIDER=fake" in section, (
        "the demo section must document the offline (JEV_BACKEND=stub CHAT_PROVIDER=fake) run "
        "command for demoing without real keys"
    )


def test_readme_demo_section_lists_six_prompts():
    section = _demo_section().lower()
    expected = ["simple", "complex", "injection", "noise", "/model flash", "/stats"]
    missing = [kw for kw in expected if kw not in section]
    assert not missing, f"demo section is missing these demo-script prompts/commands: {missing}"


def test_readme_demo_section_explains_console_elements():
    section = _demo_section().lower()
    expected = ["badge", "probability", "threshold", "timing"]
    missing = [kw for kw in expected if kw not in section]
    assert not missing, f"demo section doesn't explain these console elements: {missing}"


def test_readme_demo_section_explains_confidence_vs_probability():
    section = _demo_section().lower()
    assert "confidence" in section and "probability" in section, (
        "the demo section must explain confidence vs probability"
    )
    assert "concentrat" in section, (
        "the demo section must explain that confidence measures how concentrated the "
        "distribution is, not the probability of the chosen label (PLAN.md §0)"
    )
