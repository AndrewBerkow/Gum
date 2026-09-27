"""Offline routing eval: runs the Jev classifier + policy over a labeled dataset and reports metrics."""

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
