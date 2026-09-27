import pytest
from langchain_typesafe import ClassifierResponse

from app.jev import evaluate

TIERS = {"flash": "m-flash", "lite": "m-lite"}


def resp(p_unsafe=0.05, scope=("valid_request", 0.92), p_simple=0.88, drop=(), rid=None):
    label, p = scope
    probs = {k: (1 - p) / 2 for k in ("valid_request", "noise", "out_of_scope")}
    probs[label] = p
    a = {
        "unsafe": {"type": "noul", "noul": p_unsafe},
        "scope": {"type": "choice", "choice": label, "probabilities": probs, "confidence": 0.8},
        "complexity": {"type": "choice", "choice": "simple" if p_simple >= 0.5 else "complex",
                       "probabilities": {"simple": p_simple, "complex": 1 - p_simple}, "confidence": 0.77},
    }
    for d in drop:
        a.pop(d)
    return ClassifierResponse.model_validate({"model": "jev-latest", "answers": a, "request_id": rid})


def ev(r, tier="auto", block=0.7, lite=0.7):
    return evaluate(r, block_threshold=block, route_lite_threshold=lite, requested_tier=tier,
                    tiers=TIERS, latency_ms=3.0, jev_model="jev-latest")


@pytest.mark.parametrize("pu,scope,status,reason,conf", [
    (0.95, ("valid_request", 0.9), "blocked", "unsafe", 0.95),
    (0.71, ("valid_request", 0.9), "blocked", "unsafe", 0.71),
    (0.70, ("valid_request", 0.9), "passed", None, None),
    (0.1, ("noise", 0.85), "blocked", "noise", 0.85),
    (0.1, ("out_of_scope", 0.9), "blocked", "out_of_scope", 0.9),
    (0.1, ("noise", 0.6), "passed", None, None),
    (0.8, ("noise", 0.9), "blocked", "unsafe", 0.8),
    (0.08, ("valid_request", 0.92), "passed", None, 0.92),
])
def test_gate_rows(pu, scope, status, reason, conf):
    g, r = ev(resp(pu, scope))
    assert (g["status"], g["reason"]) == (status, reason)
    if conf is not None:
        assert g["confidence"] == pytest.approx(conf)
    assert (r is None) == (status == "blocked")


def test_gate_scope_boundary_strict():
    assert ev(resp(scope=("noise", 0.70)))[0]["status"] == "passed"
    assert ev(resp(scope=("noise", 0.71)))[0]["status"] == "blocked"


def test_gate_ambiguous_flag_and_clean_flags():
    assert ev(resp(0.1, ("noise", 0.6)))[0]["flags"] == ["ambiguous_scope"]
    assert ev(resp())[0]["flags"] == []


def test_gate_metadata():
    g, _ = ev(resp(0.08, rid="r9"))
    assert g["p_unsafe"] == pytest.approx(0.08) and g["scope"] == "valid_request"
    assert g["latency_ms"] == 3.0 and g["jev_model"] == "jev-latest" and g["request_id"] == "r9"
    assert g["scope_probabilities"]["valid_request"] == pytest.approx(0.92)


def test_gate_pass_confidence_weakest_link():
    assert ev(resp(0.4, ("valid_request", 0.9)))[0]["confidence"] == pytest.approx(0.6)


def test_gate_block_thresholds_configurable():
    assert ev(resp(0.5), block=0.4)[0]["status"] == "blocked"


@pytest.mark.parametrize("missing", ["unsafe", "scope", "complexity"])
def test_gate_missing_answer_errors(missing):
    g, r = ev(resp(drop=(missing,)))
    assert (g["status"], g["reason"], r) == ("error", "jev_error", None)


def test_gate_wrong_answer_type_errors():
    r = ClassifierResponse.model_validate({"model": "m", "answers": {
        "unsafe": {"type": "choice", "choice": "a", "probabilities": {"a": 1.0}, "confidence": 0.5},
        "scope": {"type": "noul", "noul": 0.5},
        "complexity": {"type": "noul", "noul": 0.5}}})
    assert ev(r)[0]["status"] == "error"


@pytest.mark.parametrize("ps,req,tier,src,jt", [
    (0.88, "auto", "lite", "jev", "lite"),
    (0.70, "auto", "lite", "jev", "lite"),
    (0.69, "auto", "flash", "jev", "flash"),
    (0.50, "auto", "flash", "jev", "flash"),
    (0.10, "auto", "flash", "jev", "flash"),
    (0.88, "flash", "flash", "override", "lite"),
    (0.10, "lite", "lite", "override", "flash"),
])
def test_route_rows(ps, req, tier, src, jt):
    _, r = ev(resp(p_simple=ps), req)
    assert (r["tier"], r["source"], r["jev_tier"]) == (tier, src, jt)
    assert r["model"] == TIERS[tier]
    assert r["p_simple"] == pytest.approx(ps) and r["complexity_confidence"] == pytest.approx(0.77)


def test_route_threshold_configurable():
    assert ev(resp(p_simple=0.8), lite=0.9)[1]["tier"] == "flash"
    assert ev(resp(p_simple=0.8), lite=0.8)[1]["tier"] == "lite"


def test_route_override_matching_jev_is_still_override():
    _, r = ev(resp(p_simple=0.9), "lite")
    assert (r["source"], r["jev_tier"]) == ("override", "lite")
