"""Unit test for the one-time evals/reports/ cleanup (t2 / Fix 2)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_no_stray_routing_eval_report_files_remain_and_gitkeep_kept():
    reports = ROOT / "evals" / "reports"
    stray = sorted(p.name for p in reports.glob("routing-eval-*"))
    assert stray == [], f"stray eval report files should have been deleted: {stray}"
    assert (reports / ".gitkeep").exists(), "evals/reports/.gitkeep must be kept"
