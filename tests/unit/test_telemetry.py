import asyncio
import hashlib
import json

import pytest

from app.config import Price
from app.telemetry import DecisionLog, Stats, TurnRecord, cost, counterfactual_flash_cost

PRICES = {
    "lite": Price(input_per_mtok=1.0, output_per_mtok=2.0),
    "flash": Price(input_per_mtok=10.0, output_per_mtok=20.0),
}
USAGE = {"input_tokens": 1000, "output_tokens": 500}


def test_cost_exact():
    assert cost(USAGE, "lite", PRICES) == pytest.approx(0.001 + 0.001)


def test_cost_none_when_price_or_usage_unset():
    assert cost(USAGE, "nope", PRICES) is None
    assert cost(None, "lite", PRICES) is None
    assert cost(USAGE, "lite", {}) is None


def test_counterfactual_uses_flash_price_and_same_tokens():
    assert counterfactual_flash_cost(USAGE, PRICES, "flash") == pytest.approx(0.01 + 0.01)


def rec(**kw):
    base = dict(
        thread_id="t", turn_index=0, message="hello", jev_decision={"status": "passed"},
        route={"tier": "lite", "source": "jev"}, model="lite", usage=USAGE,
        cost_usd=0.002, counterfactual_flash_cost_usd=0.02,
        latency_ms={"jev": 10.0, "ttft": 5.0, "total": 20.0},
    )
    base.update(kw)
    return TurnRecord(**base)


def test_record_hashes_message_unless_log_messages():
    d = rec().to_log_dict(log_messages=False)
    assert "message" not in d
    assert d["message_sha256"] == hashlib.sha256(b"hello").hexdigest()
    assert d["message_chars"] == 5
    assert rec().to_log_dict(log_messages=True)["message"] == "hello"


async def test_decision_log_creates_dir_and_writes_json_lines(tmp_path):
    path = tmp_path / "a" / "b" / "log.jsonl"
    log = DecisionLog(path)
    await log.append({"x": 1})
    await log.append({"x": 2})
    assert [json.loads(x) for x in path.read_text().splitlines()] == [{"x": 1}, {"x": 2}]


async def test_decision_log_50_concurrent_appends(tmp_path):
    log = DecisionLog(tmp_path / "l.jsonl")
    await asyncio.gather(*[log.append({"i": i, "pad": "z" * 5000}) for i in range(50)])
    lines = (tmp_path / "l.jsonl").read_text().splitlines()
    assert sorted(json.loads(x)["i"] for x in lines) == list(range(50))


def test_stats_exact_aggregates():
    s = Stats()
    s.add(rec(latency_ms={"jev": 10.0, "ttft": 4.0, "total": 9}))
    s.add(rec(latency_ms={"jev": 20.0, "ttft": 6.0, "total": 9}, route={"tier": "lite", "source": "override"}))
    s.add(rec(route={"tier": "flash", "source": "jev"}, latency_ms={"jev": 30.0, "ttft": 8.0, "total": 9},
              cost_usd=0.02))
    s.add(rec(jev_decision={"status": "blocked", "reason": "unsafe"}, route=None, usage=None, cost_usd=None,
              counterfactual_flash_cost_usd=None, model=None, latency_ms={"jev": 40.0, "ttft": 0, "total": 1}))
    out = s.summary()
    assert out["turns"] == 4
    assert out["blocked_pct"] == {"unsafe": 25.0}
    assert out["tier_pct"] == {"lite": pytest.approx(200 / 3), "flash": pytest.approx(100 / 3)}
    assert out["overridden_pct"] == pytest.approx(100 / 3)
    assert out["jev_latency_ms"]["p50"] == pytest.approx(25.0)
    assert out["jev_latency_ms"]["p95"] == pytest.approx(38.5)
    assert out["ttft_p50_ms"] == {"lite": 5.0, "flash": 8.0}
    assert out["total_cost_usd"] == pytest.approx(0.024)
    assert out["counterfactual_flash_cost_usd"] == pytest.approx(0.06)
    assert out["savings_pct"] == pytest.approx(60.0)


def test_stats_savings_null_without_prices():
    s = Stats()
    s.add(rec(cost_usd=None, counterfactual_flash_cost_usd=None))
    assert s.summary()["savings_pct"] is None
    assert Stats().summary()["turns"] == 0
