"""Telemetry: per-turn records, cost, the JSONL decision log and in-memory stats."""

import asyncio
import hashlib
import json
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import Price


@dataclass
class TurnRecord:
    thread_id: str
    turn_index: int
    message: str
    jev_decision: dict[str, Any] | None = None
    route: dict[str, Any] | None = None
    model: str | None = None
    usage: dict[str, int] | None = None
    cost_usd: float | None = None
    counterfactual_flash_cost_usd: float | None = None
    latency_ms: dict[str, float] = field(default_factory=lambda: {"jev": 0.0, "ttft": 0.0, "total": 0.0})
    error: str | None = None
    ts: float = field(default_factory=time.time)

    def to_log_dict(self, log_messages: bool) -> dict[str, Any]:
        d: dict[str, Any] = {
            "ts": self.ts,
            "thread_id": self.thread_id,
            "turn_index": self.turn_index,
        }
        if log_messages:
            d["message"] = self.message
        else:
            d["message_sha256"] = hashlib.sha256(self.message.encode()).hexdigest()
            d["message_chars"] = len(self.message)
        d.update(
            jev_decision=self.jev_decision,
            route=self.route,
            model=self.model,
            usage=self.usage,
            cost_usd=self.cost_usd,
            counterfactual_flash_cost_usd=self.counterfactual_flash_cost_usd,
            latency_ms=self.latency_ms,
            error=self.error,
        )
        return d


def cost(usage: dict[str, int] | None, model: str | None, prices: dict[str, Price | dict]) -> float | None:
    """USD for one turn, or None when usage or the model's price is unknown."""
    if not usage or model is None or model not in prices:
        return None
    p = prices[model]
    p = p if isinstance(p, Price) else Price(**p)
    return (
        usage.get("input_tokens", 0) * p.input_per_mtok + usage.get("output_tokens", 0) * p.output_per_mtok
    ) / 1e6


def counterfactual_flash_cost(
    usage: dict[str, int] | None, prices: dict[str, Price | dict], flash_model: str
) -> float | None:
    """What the same token counts would have cost on the flash model."""
    return cost(usage, flash_model, prices)


class DecisionLog:
    """Append-only JSONL sink; appends are serialized so concurrent lines never interleave."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = asyncio.Lock()

    async def append(self, entry: dict[str, Any]) -> None:
        line = json.dumps(entry) + "\n"
        async with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line)


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    xs = sorted(values)
    pos = (len(xs) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def _pct(n: int, total: int) -> float:
    return n / total * 100 if total else 0.0


class Stats:
    def __init__(self) -> None:
        self.records: list[TurnRecord] = []

    def add(self, record: TurnRecord) -> None:
        self.records.append(record)

    def summary(self) -> dict[str, Any]:
        recs = self.records
        n = len(recs)
        blocked = Counter(
            (r.jev_decision or {}).get("reason") or "unknown"
            for r in recs
            if (r.jev_decision or {}).get("status") != "passed"
        )
        routed = [r for r in recs if r.route]
        tiers = Counter(r.route["tier"] for r in routed)  # type: ignore[index]
        overridden = sum(1 for r in routed if r.route["source"] == "override")  # type: ignore[index]
        ttft: dict[str, list[float]] = defaultdict(list)
        for r in routed:
            ttft[r.route["tier"]].append(r.latency_ms["ttft"])  # type: ignore[index]
        jev = [r.latency_ms["jev"] for r in recs]
        priced = [r for r in recs if r.cost_usd is not None and r.counterfactual_flash_cost_usd is not None]
        total = sum(r.cost_usd for r in priced) if priced else None  # type: ignore[misc]
        cf = sum(r.counterfactual_flash_cost_usd for r in priced) if priced else None  # type: ignore[misc]
        return {
            "turns": n,
            "blocked_pct": {k: _pct(v, n) for k, v in blocked.items()},
            "tier_pct": {t: _pct(c, len(routed)) for t, c in tiers.items()},
            "overridden_pct": _pct(overridden, len(routed)),
            "jev_latency_ms": {"p50": _percentile(jev, 0.5), "p95": _percentile(jev, 0.95)},
            "ttft_p50_ms": {t: _percentile(v, 0.5) for t, v in ttft.items()},
            "total_cost_usd": total,
            "counterfactual_flash_cost_usd": cf,
            "savings_pct": (cf - total) / cf * 100 if cf else None,  # type: ignore[operator]
        }
