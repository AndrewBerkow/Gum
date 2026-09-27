"""Unit tests for README.md's T13 sections (t3 / Fix 3): setup, offline demo, live mode, test
tiers, architecture, reading the eval report, adding a question/tier, and the manual checklist.

Each test reads the real README.md and looks for the section under test. tests/unit/test_scaffold.py
already covers the existing httpx2/MockTransport spike note; these tests don't repeat that check.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _readme() -> str:
    return (ROOT / "README.md").read_text()


def _section(heading_substring: str) -> str:
    """The text from the first heading containing `heading_substring` to the next heading."""
    lines = _readme().splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.lstrip().startswith("#") and heading_substring in ln.lower())
    end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("#")), len(lines))
    return "\n".join(lines[start:end])


def test_readme_setup_and_offline_demo_section():
    text = _readme()
    assert "uv sync" in text
    assert "uv run playwright install chromium" in text
    assert "JEV_BACKEND=stub CHAT_PROVIDER=fake uv run uvicorn app.main:app" in text


def test_readme_live_mode_section_names_both_keys():
    section = _section("live")
    assert "TYPESAFE_API_KEY" in section
    assert "GOOGLE_API_KEY" in section


def test_readme_test_tiers_section():
    section = _section("test tier")
    lower = section.lower()
    for tier in ("unit", "integration", "e2e", "live"):
        assert tier in lower


def test_readme_architecture_section():
    section = _section("architecture")
    lower = section.lower()
    assert "jev" in lower
    assert "lite" in lower and "flash" in lower


def test_readme_reading_the_eval_report_section():
    section = _section("reading").lower()
    assert "gate metrics" in section or "gate metric" in section
    assert "route metric" in section
    assert "threshold sweep" in section
    assert "latency" in section


def test_readme_adding_a_question_or_tier_section():
    section = _section("adding").lower()
    assert "question" in section
    assert "tier" in section


def test_readme_t13_manual_checklist():
    section = _section("run t13 manually").lower()
    for keyword in ("fixture", "model_prices", "--judge", "commit", "route_lite_threshold"):
        assert keyword in section, f"checklist missing {keyword!r}:\n{section}"
