"""Offline routing eval: runs the Jev classifier + policy over a labeled dataset and reports metrics."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def parse_sweep(spec: str) -> list[float]:
    """Expand 'lo:hi:step' into an inclusive list of thresholds."""
    parts = spec.split(":")
    if len(parts) != 3:
        raise ValueError(f"threshold sweep must look like lo:hi:step, got {spec!r}")
    try:
        lo, hi, step = (float(p) for p in parts)
    except ValueError as exc:
        raise ValueError(f"threshold sweep must be numeric, got {spec!r}") from exc
    if step <= 0 or hi < lo:
        raise ValueError(f"threshold sweep needs step > 0 and hi >= lo, got {spec!r}")
    n = int(round((hi - lo) / step, 6)) + 1
    return [round(lo + i * step, 10) for i in range(n)]


GATES = {"pass", "unsafe", "noise", "out_of_scope"}
TIERS = {"simple", "complex"}


def _validate_item(it: dict) -> None:
    if not isinstance(it.get("id"), str) or not it["id"]:
        raise ValueError(f"item needs a non-empty string id: {it!r}")
    if not isinstance(it.get("text"), str) or not it["text"].strip():
        raise ValueError(f"item {it['id']} needs non-empty text")
    if it.get("expect_gate") not in GATES:
        raise ValueError(f"item {it['id']} has invalid expect_gate {it.get('expect_gate')!r}")
    if not isinstance(it.get("notes", ""), str):
        raise ValueError(f"item {it['id']} notes must be a string")
    ctx = it.get("context")
    if ctx is not None and not (isinstance(ctx, list) and all(isinstance(c, str) for c in ctx)):
        raise ValueError(f"item {it['id']} context must be a list of strings")
    tier = it.get("expect_tier")
    if it["expect_gate"] == "pass" and tier not in TIERS:
        raise ValueError(f"passing item {it['id']} needs expect_tier simple|complex")
    if it["expect_gate"] != "pass" and tier is not None:
        raise ValueError(f"item {it['id']} expects a block, so it must not have expect_tier")


def load_dataset(path) -> list[dict]:
    """Read and validate the labeled routing dataset (jsonl)."""
    items = [json.loads(ln) for ln in Path(path).read_text().splitlines() if ln.strip()]
    seen: set[str] = set()
    for it in items:
        _validate_item(it)
        if it["id"] in seen:
            raise ValueError(f"duplicate id {it['id']}")
        seen.add(it["id"])
    return items


def _percentile(sorted_vals: list[float], q: float) -> float:
    pos = (len(sorted_vals) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def latency_stats(latencies_ms: list[float]) -> dict[str, float | None]:
    """p50 / p95 / max of Jev latency in ms (linear interpolation)."""
    if not latencies_ms:
        return {"p50": None, "p95": None, "max": None}
    vals = sorted(latencies_ms)
    return {"p50": _percentile(vals, 0.5), "p95": _percentile(vals, 0.95), "max": vals[-1]}
