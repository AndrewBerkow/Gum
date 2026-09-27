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
