import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_gitignore():
    t = (ROOT / ".gitignore").read_text()
    for pat in (r"\.env", r"logs/?", r"\.venv/?"):
        assert re.search(rf"^{pat}$", t, re.M)


def test_env_example_verbatim():
    plan = (ROOT / "PLAN.md").read_text()
    a = plan.index("`.env.example` is committed")
    start = plan.index("```\n", a) + 4
    assert (ROOT / ".env.example").read_text().strip() == plan[start : plan.index("\n```", start)].strip()


def test_readme_records_spike():
    t = (ROOT / "README.md").read_text()
    assert "httpx2" in t and "MockTransport" in t


def test_pyproject_python_and_no_openrouter():
    d = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert d["project"]["requires-python"].startswith(">=3.12")
    assert "openrouter" not in str(d).lower()
