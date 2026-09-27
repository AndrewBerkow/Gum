"""Unit tests for evals/run_eval.py (offline; the classifier is an in-process fake)."""

import pytest

import evals.run_eval as ev


def test_parse_sweep_expands_inclusive_range():
    assert ev.parse_sweep("0.5:0.7:0.1") == pytest.approx([0.5, 0.6, 0.7])


def test_parse_sweep_rejects_malformed_spec():
    for bad in ("0.5", "0.5:0.9", "a:b:c", "0.9:0.5:0.1", "0.5:0.9:0"):
        with pytest.raises(ValueError):
            ev.parse_sweep(bad)


def _write(tmp_path, *rows):
    import json

    p = tmp_path / "d.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n\n")
    return p


def _item(id="a", **kw):
    base = {"id": id, "text": "hi", "expect_gate": "pass", "expect_tier": "simple", "notes": ""}
    base.update(kw)
    return base


def test_load_dataset_parses_valid_items_and_skips_blank_lines(tmp_path):
    items = ev.load_dataset(_write(tmp_path, _item("a"), _item("b", context=["q", "a"])))
    assert [i["id"] for i in items] == ["a", "b"]


@pytest.mark.parametrize(
    "bad",
    [
        _item(expect_gate="bogus"),
        _item(expect_tier=None),  # pass needs a tier
        _item(expect_gate="unsafe"),  # non-pass must not carry a tier
        _item(text=""),
        _item(context="not a list"),
    ],
)
def test_load_dataset_rejects_schema_violations(tmp_path, bad):
    with pytest.raises(ValueError):
        ev.load_dataset(_write(tmp_path, bad))


def test_load_dataset_rejects_duplicate_ids(tmp_path):
    with pytest.raises(ValueError, match="duplicate"):
        ev.load_dataset(_write(tmp_path, _item("a"), _item("a")))


def test_latency_stats_interpolates_percentiles():
    s = ev.latency_stats([10.0, 20.0, 30.0, 40.0, 50.0])
    assert s == pytest.approx({"p50": 30.0, "p95": 48.0, "max": 50.0})


def test_latency_stats_single_and_empty():
    assert ev.latency_stats([7.0]) == pytest.approx({"p50": 7.0, "p95": 7.0, "max": 7.0})
    assert ev.latency_stats([]) == {"p50": None, "p95": None, "max": None}


def _r(id, expect_tier, route_tier, p_simple=0.5):
    return {"id": id, "expect_gate": "pass", "expect_tier": expect_tier, "gate": "passed",
            "route_tier": route_tier, "p_simple": p_simple}


ROUTED = [_r("s1", "simple", "lite"), _r("s2", "simple", "lite"), _r("s3", "simple", "flash"),
          _r("c1", "complex", "flash"), _r("c2", "complex", "lite")]


def test_route_metrics_confusion_accuracy_and_rates():
    m = ev.route_metrics(ROUTED)
    assert m["confusion"] == {"simple": {"lite": 2, "flash": 1}, "complex": {"lite": 1, "flash": 1}}
    assert m["accuracy"] == pytest.approx(3 / 5)
    assert m["complex_to_lite_rate"] == pytest.approx(1 / 2)
    assert m["simple_to_flash_rate"] == pytest.approx(1 / 3)
    assert m["lite_share"] == pytest.approx(3 / 5)


def test_route_metrics_ignore_blocked_and_untiered_items():
    extra = [{"id": "u", "expect_gate": "unsafe", "gate": "blocked", "reason": "unsafe"},
             {"id": "n", "expect_gate": "noise", "gate": "passed", "route_tier": "lite"}]
    assert ev.route_metrics(ROUTED + extra) == ev.route_metrics(ROUTED)


def test_route_metrics_empty_has_none_rates():
    m = ev.route_metrics([])
    assert m["accuracy"] is None and m["lite_share"] is None
    assert m["complex_to_lite_rate"] is None and m["simple_to_flash_rate"] is None


def _b(id, expect_gate, reason):
    return {"id": id, "expect_gate": expect_gate, "gate": "blocked", "reason": reason}


def _p(id, expect_gate, tier=None):
    return {"id": id, "expect_gate": expect_gate, "expect_tier": tier, "gate": "passed", "route_tier": "lite"}


GATED = [_b("u1", "unsafe", "unsafe"), _b("u2", "unsafe", "unsafe"), _p("u3", "unsafe"),
         _b("b1", "pass", "unsafe"), _p("b2", "pass", "simple"), _p("b3", "pass", "complex"),
         _p("b4", "pass", "simple"), _b("n1", "noise", "noise"), _p("n2", "out_of_scope")]


def test_gate_metrics_exact_rates():
    m = ev.gate_metrics(GATED)
    assert m["unsafe_recall"] == pytest.approx(2 / 3)
    assert m["unsafe_precision"] == pytest.approx(2 / 3)
    assert m["false_block_rate"] == pytest.approx(1 / 4)
    assert m["noise_catch_rate"] == pytest.approx(1 / 2)


def test_gate_metrics_undefined_rates_are_none():
    m = ev.gate_metrics([_p("b", "pass", "simple")])
    assert m["unsafe_recall"] is None and m["unsafe_precision"] is None and m["noise_catch_rate"] is None
    assert m["false_block_rate"] == 0.0


SWEEP = [_r("c1", "complex", "flash", 0.85), _r("c2", "complex", "flash", 0.6),
         _r("c3", "complex", "flash", 0.3), _r("c4", "complex", "flash", 0.2),
         _r("s1", "simple", "lite", 0.95), _r("s2", "simple", "lite", 0.9),
         _r("s3", "simple", "lite", 0.8), _r("s4", "simple", "lite", 0.65)]


def test_sweep_rows_recompute_routing_from_p_simple():
    out = ev.sweep_thresholds(SWEEP, [0.5, 0.7, 0.9], target=0.25)
    rows = {r["threshold"]: r for r in out["rows"]}
    assert rows[0.5]["lite_share"] == pytest.approx(6 / 8) and rows[0.5]["misroute_rate"] == pytest.approx(0.5)
    assert rows[0.7]["lite_share"] == pytest.approx(4 / 8) and rows[0.7]["misroute_rate"] == pytest.approx(0.25)
    assert rows[0.9]["lite_share"] == pytest.approx(2 / 8) and rows[0.9]["misroute_rate"] == 0.0


def test_sweep_threshold_boundary_is_inclusive():
    out = ev.sweep_thresholds([_r("s", "simple", "lite", 0.7)], [0.7, 0.71])
    assert [r["lite_share"] for r in out["rows"]] == [1.0, 0.0]


def test_sweep_recommends_lowest_threshold_meeting_target_else_none():
    assert ev.sweep_thresholds(SWEEP, [0.5, 0.7, 0.9], target=0.25)["recommended"] == 0.7
    hopeless = [_r("c", "complex", "flash", 0.99)]
    assert ev.sweep_thresholds(hopeless, [0.5, 0.9], target=0.05)["recommended"] is None


def test_sweep_estimates_cost_savings_from_lite_share():
    out = ev.sweep_thresholds(SWEEP, [0.5], lite_cost_ratio=0.2)
    assert out["rows"][0]["est_savings"] == pytest.approx(6 / 8 * 0.8)


# ---- evaluate_item / run_all (fake classifier, no network)
import asyncio  # noqa: E402

from app.config import Settings  # noqa: E402
from tests.unit.test_evaluate import resp  # noqa: E402


class FakeClassifier:
    def __init__(self, response=None, exc=None, delay=0.0):
        self.response, self.exc, self.delay = response, exc, delay
        self.requests, self.active, self.max_active = [], 0, 0

    async def ainvoke(self, req, *a, **k):
        self.requests.append(req)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(self.delay)
        finally:
            self.active -= 1
        if self.exc:
            raise self.exc
        return self.response


SETTINGS = Settings(_env_file=None, jev_backend="stub", chat_provider="fake")
ITEM = {"id": "x", "text": "hello", "expect_gate": "pass", "expect_tier": "simple", "notes": ""}


async def test_evaluate_item_passed_record_carries_route_and_probabilities():
    rec = await ev.evaluate_item(ITEM, FakeClassifier(resp(p_simple=0.88)), SETTINGS)
    assert rec["id"] == "x" and rec["expect_gate"] == "pass" and rec["expect_tier"] == "simple"
    assert rec["gate"] == "passed" and rec["route_tier"] == "lite"
    assert rec["p_simple"] == pytest.approx(0.88) and rec["p_unsafe"] == pytest.approx(0.05)
    assert rec["latency_ms"] > 0


async def test_evaluate_item_blocked_record_has_reason_and_no_route():
    rec = await ev.evaluate_item(ITEM, FakeClassifier(resp(p_unsafe=0.95)), SETTINGS)
    assert rec["gate"] == "blocked" and rec["reason"] == "unsafe"
    assert rec.get("route_tier") is None and rec.get("p_simple") is None


async def test_evaluate_item_uses_context_as_alternating_history():
    fake = FakeClassifier(resp())
    await ev.evaluate_item({**ITEM, "context": ["what is a mutex?", "A lock."]}, fake, SETTINGS)
    (req,) = fake.requests
    assert req["state"]["latest"].content == "hello"
    assert [type(m).__name__ for m in req["state"]["recent"]] == ["HumanMessage", "AIMessage"]


async def test_evaluate_item_classifier_error_is_recorded_not_raised():
    rec = await ev.evaluate_item(ITEM, FakeClassifier(exc=RuntimeError("boom")), SETTINGS)
    assert rec["gate"] == "error" and rec["reason"] == "jev_error" and rec["latency_ms"] > 0


async def test_run_all_preserves_order_and_bounds_concurrency():
    items = [{**ITEM, "id": f"i{n}"} for n in range(12)]
    fake = FakeClassifier(resp(), delay=0.01)
    results = await ev.run_all(items, fake, SETTINGS, concurrency=3)
    assert [r["id"] for r in results] == [f"i{n}" for n in range(12)]
    assert 1 < fake.max_active <= 3


# ---- report, outputs, CLI
import datetime as dt  # noqa: E402
import json  # noqa: E402

REPORT_RESULTS = [*SWEEP, *GATED[:3]]
for _r_ in REPORT_RESULTS:
    _r_.setdefault("latency_ms", 12.0)


def _report():
    sweep = ev.sweep_thresholds(REPORT_RESULTS, [0.5, 0.7], target=0.25)
    return ev.render_report(REPORT_RESULTS, sweep, date=dt.date(2026, 1, 2), backend="stub")


def test_render_report_has_every_section_heading():
    headings = [ln for ln in _report().splitlines() if ln.startswith("#")]
    text = "\n".join(headings).lower()
    for section in ("gate metrics", "route metrics", "threshold sweep", "latency"):
        assert section in text


def test_render_report_shows_date_backend_recommendation_and_confusion_counts():
    text = _report()
    assert "2026-01-02" in text and "stub" in text
    assert "0.70" in text and "recommended" in text.lower()
    assert "complex" in text and "lite" in text and "flash" in text


def test_render_report_says_so_when_no_threshold_meets_target():
    sweep = ev.sweep_thresholds([_r("c", "complex", "flash", 0.99)], [0.5], target=0.05)
    text = ev.render_report([_r("c", "complex", "flash", 0.99)], sweep, date=dt.date(2026, 1, 2), backend="stub")
    assert "no threshold" in text.lower()


def test_write_outputs_creates_dated_report_and_raw_jsonl(tmp_path):
    md, raw = ev.write_outputs(tmp_path / "nested", "# hi\n", REPORT_RESULTS, dt.date(2026, 1, 2))
    assert md.name == "routing-eval-2026-01-02.md" and md.read_text() == "# hi\n"
    assert raw.name == "routing-eval-2026-01-02.jsonl"
    assert [json.loads(ln)["id"] for ln in raw.read_text().splitlines()] == [r["id"] for r in REPORT_RESULTS]


def test_main_stub_run_writes_report_and_raw_results(tmp_path, capsys):
    ds = _write(tmp_path, _item("a"), _item("b", text="explain why the sky is blue step by step and compare",
                                             expect_tier="complex"))
    code = ev.main(["--backend", "stub", "--dataset", str(ds), "--out", str(tmp_path / "o"),
                    "--threshold-sweep", "0.5:0.9:0.2"])
    assert code == 0
    assert len(list((tmp_path / "o").glob("*.md"))) == 1 and len(list((tmp_path / "o").glob("*.jsonl"))) == 1


def test_main_judge_without_live_backend_refuses_cleanly(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        ev.main(["--backend", "stub", "--judge", "--out", str(tmp_path)])
    assert exc.value.code != 0
    err = capsys.readouterr().err.lower()
    assert "judge" in err and "live" in err
    assert not list(tmp_path.glob("*"))
