"""Top-level integration tests for t4: the offline routing eval harness (PLAN T11).

Public entry points:
  evals/routing_dataset.jsonl                (data file)
  evals/run_eval.py CLI                      (run as a subprocess, like a user would)
  evals/run_eval.py module-level functions   (loaded by file path; the contract is):
    load_dataset(path) -> list[dict]
    parse_sweep("lo:hi:step") -> list[float]
    gate_metrics(results) -> dict
    route_metrics(results) -> dict
    sweep_thresholds(results, thresholds, target=0.05) -> {"rows": [...], "recommended": float | None}
    latency_stats(latencies_ms) -> {"p50", "p95", "max"}

A result record is a dict:
  {"id", "expect_gate", "expect_tier" (optional), "gate": "passed"|"blocked",
   "reason" (when blocked), "route_tier": "lite"|"flash" (when passed), "p_simple", "latency_ms"}
Tiers: simple prompts belong on "lite", complex prompts on "flash".
Nothing here touches the network: the CLI runs with --backend stub.
"""

import importlib.util
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "evals" / "routing_dataset.jsonl"
RUN_EVAL = ROOT / "evals" / "run_eval.py"

GATES = {"pass", "unsafe", "noise", "out_of_scope"}
TIERS = {"simple", "complex"}


def load_run_eval():
    assert RUN_EVAL.exists(), "evals/run_eval.py does not exist"
    spec = importlib.util.spec_from_file_location("run_eval_under_test", RUN_EVAL)
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_eval_under_test"] = module
    spec.loader.exec_module(module)
    return module


def read_dataset():
    assert DATASET.exists(), "evals/routing_dataset.jsonl does not exist"
    lines = [ln for ln in DATASET.read_text().splitlines() if ln.strip()]
    return [json.loads(ln) for ln in lines]


def run_cli(*args, cwd=ROOT):
    return subprocess.run(
        [sys.executable, str(RUN_EVAL), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=180,
        env=_clean_env(),
    )


def _clean_env():
    import os

    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("LANGCHAIN_", "LANGSMITH_"))
        and k not in ("TYPESAFE_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY")
    }
    env["PYTHONPATH"] = str(ROOT)
    return env


# ------------------------------------------------------------------ dataset schema


def test_dataset_every_item_matches_schema():
    items = read_dataset()
    assert items, "dataset is empty"
    for it in items:
        assert isinstance(it["id"], str) and it["id"]
        assert isinstance(it["text"], str) and it["text"].strip()
        assert it["expect_gate"] in GATES, it
        assert isinstance(it["notes"], str), it
        if "context" in it:
            assert isinstance(it["context"], list)
            assert all(isinstance(c, str) for c in it["context"])
        if it["expect_gate"] == "pass":
            assert it.get("expect_tier") in TIERS, f"passing item needs expect_tier: {it}"
        else:
            assert it.get("expect_tier") is None, f"non-pass item must not have a tier: {it}"


def test_dataset_ids_are_unique():
    ids = [it["id"] for it in read_dataset()]
    dupes = [i for i, n in Counter(ids).items() if n > 1]
    assert not dupes, f"duplicate ids: {dupes}"


def test_dataset_label_counts_meet_plan_t11_minimums():
    items = read_dataset()
    assert len(items) >= 110  # ~120 items
    gate = Counter(it["expect_gate"] for it in items)
    tier = Counter(it.get("expect_tier") for it in items if it["expect_gate"] == "pass")
    assert tier["simple"] >= 40
    assert tier["complex"] >= 40
    assert gate["unsafe"] >= 12
    assert gate["noise"] + gate["out_of_scope"] >= 8
    adversarial = [it for it in items if "adversarial" in it["notes"].lower()]
    assert len(adversarial) >= 20


def test_dataset_adversarial_items_include_context_dependent_followups():
    items = read_dataset()
    adversarial_with_context = [
        it for it in items if "adversarial" in it["notes"].lower() and it.get("context")
    ]
    assert adversarial_with_context, "need follow-ups whose complexity depends on context"


# ------------------------------------------------------------------ metric functions


def _r(id, expect_tier, route_tier, p_simple=0.5, expect_gate="pass", gate="passed", **kw):
    return {
        "id": id,
        "expect_gate": expect_gate,
        "expect_tier": expect_tier,
        "gate": gate,
        "route_tier": route_tier,
        "p_simple": p_simple,
        "latency_ms": 10.0,
        **kw,
    }


def _blocked(id, expect_gate, reason):
    return {
        "id": id,
        "expect_gate": expect_gate,
        "gate": "blocked",
        "reason": reason,
        "latency_ms": 10.0,
    }


def test_route_metrics_confusion_matrix_is_exact():
    ev = load_run_eval()
    results = [
        _r("s1", "simple", "lite"),
        _r("s2", "simple", "lite"),
        _r("s3", "simple", "lite"),
        _r("s4", "simple", "flash"),
        _r("c1", "complex", "flash"),
        _r("c2", "complex", "flash"),
        _r("c3", "complex", "lite"),
        _r("c4", "complex", "flash"),
    ]
    m = ev.route_metrics(results)
    assert m["confusion"]["simple"]["lite"] == 3
    assert m["confusion"]["simple"]["flash"] == 1
    assert m["confusion"]["complex"]["lite"] == 1
    assert m["confusion"]["complex"]["flash"] == 3
    assert m["accuracy"] == pytest.approx(6 / 8)


def test_route_metrics_misroute_rates_and_lite_share_are_exact():
    ev = load_run_eval()
    results = [
        _r("s1", "simple", "lite"),
        _r("s2", "simple", "lite"),
        _r("s3", "simple", "lite"),
        _r("s4", "simple", "flash"),
        _r("c1", "complex", "flash"),
        _r("c2", "complex", "flash"),
        _r("c3", "complex", "lite"),
        _r("c4", "complex", "flash"),
    ]
    m = ev.route_metrics(results)
    assert m["complex_to_lite_rate"] == pytest.approx(1 / 4)
    assert m["simple_to_flash_rate"] == pytest.approx(1 / 4)
    assert m["lite_share"] == pytest.approx(4 / 8)


def test_route_metrics_ignore_blocked_items():
    ev = load_run_eval()
    results = [
        _r("s1", "simple", "lite"),
        _r("c1", "complex", "flash"),
        _blocked("u1", "unsafe", "unsafe"),
        _blocked("n1", "noise", "noise"),
    ]
    m = ev.route_metrics(results)
    assert m["accuracy"] == pytest.approx(1.0)
    assert m["lite_share"] == pytest.approx(1 / 2)
    assert sum(sum(row.values()) for row in m["confusion"].values()) == 2


def test_gate_metrics_precision_recall_false_blocks_and_noise_catch_are_exact():
    ev = load_run_eval()
    results = [
        _blocked("u1", "unsafe", "unsafe"),
        _blocked("u2", "unsafe", "unsafe"),
        _blocked("u3", "unsafe", "unsafe"),
        _r("u4", None, "lite", expect_gate="unsafe"),  # missed unsafe
        _blocked("b1", "pass", "unsafe"),  # false block on a benign item
        _r("b2", "simple", "lite"),
        _r("b3", "complex", "flash"),
        _r("b4", "simple", "lite"),
        _blocked("n1", "noise", "noise"),
        _r("n2", None, "lite", expect_gate="noise"),  # missed noise
    ]
    m = ev.gate_metrics(results)
    assert m["unsafe_recall"] == pytest.approx(3 / 4)
    assert m["unsafe_precision"] == pytest.approx(3 / 4)  # 4 blocked as unsafe, 3 truly unsafe
    assert m["false_block_rate"] == pytest.approx(1 / 4)  # 1 of 4 benign items
    assert m["noise_catch_rate"] == pytest.approx(1 / 2)


def test_parse_sweep_expands_inclusive_range():
    ev = load_run_eval()
    got = ev.parse_sweep("0.5:0.95:0.05")
    assert got == pytest.approx([0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95])


SWEEP_RESULTS = [
    _r("c1", "complex", "flash", p_simple=0.85),
    _r("c2", "complex", "flash", p_simple=0.6),
    _r("c3", "complex", "flash", p_simple=0.3),
    _r("c4", "complex", "flash", p_simple=0.2),
    _r("s1", "simple", "lite", p_simple=0.95),
    _r("s2", "simple", "lite", p_simple=0.9),
    _r("s3", "simple", "lite", p_simple=0.8),
    _r("s4", "simple", "lite", p_simple=0.65),
]


def test_sweep_rows_report_exact_lite_share_and_misroute_per_threshold():
    ev = load_run_eval()
    out = ev.sweep_thresholds(SWEEP_RESULTS, [0.5, 0.7, 0.9], target=0.25)
    by_t = {round(r["threshold"], 2): r for r in out["rows"]}
    assert by_t[0.5]["lite_share"] == pytest.approx(6 / 8)
    assert by_t[0.5]["misroute_rate"] == pytest.approx(2 / 4)
    assert by_t[0.7]["lite_share"] == pytest.approx(4 / 8)
    assert by_t[0.7]["misroute_rate"] == pytest.approx(1 / 4)
    assert by_t[0.9]["lite_share"] == pytest.approx(2 / 8)
    assert by_t[0.9]["misroute_rate"] == pytest.approx(0.0)


def test_sweep_recommends_lowest_threshold_meeting_misroute_target():
    ev = load_run_eval()
    out = ev.sweep_thresholds(SWEEP_RESULTS, [0.5, 0.7, 0.9], target=0.25)
    assert out["recommended"] == pytest.approx(0.7)  # 0.5 misses (0.5 > 0.25); 0.7 is the lowest that meets it


def test_sweep_recommends_none_when_no_threshold_meets_target():
    ev = load_run_eval()
    results = [_r("c1", "complex", "flash", p_simple=0.99), _r("s1", "simple", "lite", p_simple=0.99)]
    out = ev.sweep_thresholds(results, [0.5, 0.7, 0.9], target=0.05)
    assert out["recommended"] is None


def test_latency_stats_p50_p95_max_are_exact():
    ev = load_run_eval()
    stats = ev.latency_stats([float(x) for x in range(1, 101)])
    assert stats["max"] == pytest.approx(100.0)
    assert stats["p50"] == pytest.approx(50.5, abs=0.6)
    assert stats["p95"] == pytest.approx(95.0, abs=1.1)


# ------------------------------------------------------------------ CLI end to end


@pytest.fixture(scope="module")
def stub_run(tmp_path_factory):
    out = tmp_path_factory.mktemp("eval_out")
    proc = run_cli("--backend", "stub", "--threshold-sweep", "0.5:0.95:0.05", "--out", str(out))
    return proc, out


def test_cli_stub_run_exits_zero(stub_run):
    proc, _ = stub_run
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_cli_stub_run_writes_dated_markdown_report_with_every_section_heading(stub_run):
    proc, out = stub_run
    assert proc.returncode == 0, proc.stdout + proc.stderr
    reports = list(Path(out).glob("*.md"))
    assert len(reports) == 1, list(Path(out).iterdir())
    text = reports[0].read_text().lower()
    headings = [ln for ln in text.splitlines() if ln.lstrip().startswith("#")]
    joined = "\n".join(headings)
    for section in ("gate metrics", "route metrics", "threshold sweep", "latency"):
        assert section in joined, f"missing heading '{section}' in:\n{joined}"
    assert any(ch.isdigit() for ch in reports[0].name), "report filename should be dated"


def test_cli_stub_run_writes_raw_results_jsonl_covering_every_dataset_item(stub_run):
    proc, out = stub_run
    assert proc.returncode == 0, proc.stdout + proc.stderr
    raws = list(Path(out).glob("*.jsonl"))
    assert len(raws) == 1, list(Path(out).iterdir())
    rows = [json.loads(ln) for ln in raws[0].read_text().splitlines() if ln.strip()]
    assert {r["id"] for r in rows} == {it["id"] for it in read_dataset()}
    for r in rows:
        assert "latency_ms" in r


def test_cli_stub_run_records_raw_probabilities_for_passing_items(stub_run):
    proc, out = stub_run
    assert proc.returncode == 0, proc.stdout + proc.stderr
    raw = next(Path(out).glob("*.jsonl"))
    rows = [json.loads(ln) for ln in raw.read_text().splitlines() if ln.strip()]
    passed = [r for r in rows if r.get("gate") == "passed"]
    assert passed
    assert all(0.0 <= r["p_simple"] <= 1.0 for r in passed)


def test_cli_judge_with_stub_backend_refuses_with_clear_message(tmp_path):
    proc = run_cli("--backend", "stub", "--judge", "--out", str(tmp_path))
    assert proc.returncode != 0
    msg = (proc.stdout + proc.stderr).lower()
    assert "judge" in msg and "live" in msg
    assert "traceback" not in msg, "should be a clean refusal, not a crash"
    assert not list(tmp_path.glob("*.md")), "no report should be written on refusal"
