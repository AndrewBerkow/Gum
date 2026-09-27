"""Unit tests for .gitignore's eval-report rules (t2 / Fix 2)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_gitignore_ignores_eval_report_jsonl_files():
    lines = (ROOT / ".gitignore").read_text().splitlines()
    assert "evals/reports/*.jsonl" in lines, (
        "real manual eval runs produce both .jsonl and .md reports; "
        "the .jsonl rule should sit next to the existing evals/reports/*.md rule"
    )
