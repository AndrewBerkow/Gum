"""Unit tests for `app.jev.explain_decision`: the rich `jev.decision` payload built from
`evaluate`'s own `JevDecision` / `RouteDecision` outputs (FEATURE_PLAN.md Task 2)."""

import pytest
from langchain_typesafe import ClassifierResponse

from app.jev import evaluate, explain_decision
from tests.unit.test_evaluate import resp

TIERS = {"flash": "m-flash", "lite": "m-lite"}
BLOCK = 0.70
LITE = 0.70


def explain(response, tier="auto", block=BLOCK, lite=LITE):
    decision, route = evaluate(
        response,
        block_threshold=block,
        route_lite_threshold=lite,
        requested_tier=tier,
        tiers=TIERS,
        latency_ms=3.0,
        jev_model="jev-latest",
    )
    return explain_decision(
        response, decision, route, block_threshold=block, route_lite_threshold=lite
    )


# ----------------------------------------------------------------- 1-2: unsafe detail


def test_unsafe_detail_reports_safe_verdict_when_passed():
    d = explain(resp(p_unsafe=0.04))
    assert d["unsafe"] == {"p": pytest.approx(0.04), "threshold": pytest.approx(0.70),
                            "comparison": ">", "verdict": "safe"}


def test_unsafe_detail_reports_blocked_verdict_and_respects_strict_greater_than_boundary():
    d = explain(resp(p_unsafe=0.71))
    assert d["unsafe"]["verdict"] == "blocked"

    d = explain(resp(p_unsafe=0.70))
    assert d["unsafe"]["verdict"] == "safe"
    assert d["outcome"] == "passed"


# ----------------------------------------------------------------- 3-4: scope detail


def test_scope_detail_reports_safe_verdict_for_valid_request_and_ambiguous_but_passed():
    d = explain(resp(scope=("valid_request", 0.92)))
    s = d["scope"]
    assert s["choice"] == "valid_request"
    assert set(s["probabilities"]) == {"valid_request", "noise", "out_of_scope"}
    assert s["threshold"] == pytest.approx(0.70)
    assert s["comparison"] == ">"
    assert s["verdict"] == "safe"

    # ambiguous_scope: non-valid_request choice at or below block_threshold is still passed.
    d = explain(resp(p_unsafe=0.1, scope=("noise", 0.6)))
    assert d["outcome"] == "passed"
    assert d["scope"]["choice"] == "noise"
    assert d["scope"]["verdict"] == "safe"


def test_scope_detail_reports_blocked_verdict_and_respects_strict_greater_than_boundary():
    d = explain(resp(p_unsafe=0.1, scope=("noise", 0.71)))
    assert d["outcome"] == "blocked"
    assert d["scope"]["verdict"] == "blocked"

    d = explain(resp(p_unsafe=0.1, scope=("noise", 0.70)))
    assert d["outcome"] == "passed"
    assert d["scope"]["verdict"] == "safe"


# ----------------------------------------------------------------- 5: complexity detail


def test_complexity_detail_is_populated_even_when_blocked_and_respects_greater_equal_boundary():
    d = explain(resp(p_unsafe=0.97, p_simple=0.5))
    assert d["outcome"] == "blocked"
    c = d["complexity"]
    assert c["p_simple"] == pytest.approx(0.5)
    assert c["threshold"] == pytest.approx(0.70)
    assert c["comparison"] == "≥"
    assert c["tier"] == "flash"

    assert explain(resp(p_simple=0.70))["complexity"]["tier"] == "lite"
    assert explain(resp(p_simple=0.69))["complexity"]["tier"] == "flash"


# ----------------------------------------------------------------- 6: distribution_concentration


def test_distribution_concentration_reports_raw_confidence_not_label_probability():
    body = {
        "model": "jev-latest",
        "answers": {
            "unsafe": {"type": "noul", "noul": 0.05},
            "scope": {"type": "choice", "choice": "valid_request",
                      "probabilities": {"valid_request": 0.92, "noise": 0.04, "out_of_scope": 0.04},
                      "confidence": 0.55},
            "complexity": {"type": "choice", "choice": "simple",
                           "probabilities": {"simple": 0.88, "complex": 0.12},
                           "confidence": 0.4},
        },
    }
    response = ClassifierResponse.model_validate(body)
    d = explain(response)
    dc = d["distribution_concentration"]
    assert dc == {"scope": pytest.approx(0.55), "complexity": pytest.approx(0.4)}
    assert dc["scope"] != d["scope"]["probabilities"][d["scope"]["choice"]]
    assert dc["complexity"] != d["complexity"]["p_simple"]


# ----------------------------------------------------------------- 7: route detail


def test_route_detail_is_none_when_blocked_and_reports_both_tiers_on_override():
    d = explain(resp(p_unsafe=0.97))
    assert d["outcome"] == "blocked"
    assert d["route"] is None

    d = explain(resp(p_simple=0.9), tier="flash")
    assert d["route"] == {"jev_tier": "lite", "tier": "flash", "source": "override"}

    d = explain(resp(p_simple=0.3))
    assert d["route"] == {"jev_tier": "flash", "tier": "flash", "source": "jev"}


# ----------------------------------------------------------------- 8: error case


def test_error_case_reports_no_question_detail():
    response = ClassifierResponse.model_validate({
        "model": "jev-latest",
        "answers": {
            "scope": {"type": "choice", "choice": "valid_request",
                      "probabilities": {"valid_request": 0.9}, "confidence": 0.8},
            "complexity": {"type": "choice", "choice": "simple",
                           "probabilities": {"simple": 0.9, "complex": 0.1}, "confidence": 0.8},
        },
    })
    d = explain(response)
    assert d["outcome"] == "error"
    assert d["reason"] == "jev_error"
    assert d["unsafe"] is None
    assert d["scope"] is None
    assert d["complexity"] is None
    assert d["distribution_concentration"] is None
    assert d["route"] is None
    assert isinstance(d["explanation"], str) and d["explanation"]


# ----------------------------------------------------------------- 9-10: one-liner


def test_explanation_matches_plan_one_liner_for_passing_turn():
    d = explain(resp(p_unsafe=0.04, scope=("valid_request", 0.92), p_simple=0.88))
    assert d["explanation"] == (
        "p_unsafe 0.04 ≤ 0.70 · scope valid_request 0.92 · p_simple 0.88 ≥ 0.70 → lite"
    )


def test_explanation_for_blocked_turns_names_the_reason():
    d = explain(resp(p_unsafe=0.97))
    assert d["explanation"].endswith("→ blocked (unsafe)")
    assert "scope" not in d["explanation"]
    assert "p_simple" not in d["explanation"]

    d = explain(resp(p_unsafe=0.1, scope=("noise", 0.85)))
    assert d["explanation"].endswith("→ blocked (noise)")
    assert "p_simple" not in d["explanation"]
