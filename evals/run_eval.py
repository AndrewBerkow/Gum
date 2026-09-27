"""Offline routing eval: runs the Jev classifier + policy over a labeled dataset and reports metrics."""

import argparse
import asyncio
import datetime as dt
import json
import random
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402

from app.config import ConfigError, Settings, has_real_key  # noqa: E402
from app.jev import build_request, evaluate  # noqa: E402
from app.state import Tier  # noqa: E402


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


_EXPECTED_ROUTE = {"simple": "lite", "complex": "flash"}


def _ratio(num: int, den: int) -> float | None:
    return num / den if den else None


def _routable(results: list[dict]) -> list[dict]:
    """Gate-passing items that carry an expected tier."""
    return [r for r in results if r.get("gate") == "passed" and r.get("expect_tier") in TIERS]


def route_metrics(results: list[dict]) -> dict:
    """Accuracy, confusion matrix and misroute rates over gate-passing, tier-labeled items."""
    rows = _routable(results)
    confusion = {t: {"lite": 0, "flash": 0} for t in ("simple", "complex")}
    for r in rows:
        confusion[r["expect_tier"]][r["route_tier"]] += 1
    correct = sum(confusion[t][_EXPECTED_ROUTE[t]] for t in confusion)
    lite = confusion["simple"]["lite"] + confusion["complex"]["lite"]
    return {
        "n": len(rows),
        "confusion": confusion,
        "accuracy": _ratio(correct, len(rows)),
        "complex_to_lite_rate": _ratio(confusion["complex"]["lite"], sum(confusion["complex"].values())),
        "simple_to_flash_rate": _ratio(confusion["simple"]["flash"], sum(confusion["simple"].values())),
        "lite_share": _ratio(lite, len(rows)),
    }


def gate_metrics(results: list[dict]) -> dict:
    """Unsafe precision/recall, benign false-block rate and noise/out-of-scope catch rate."""
    unsafe = [r for r in results if r["expect_gate"] == "unsafe"]
    benign = [r for r in results if r["expect_gate"] == "pass"]
    off_topic = [r for r in results if r["expect_gate"] in ("noise", "out_of_scope")]
    flagged = [r for r in results if r.get("gate") == "blocked" and r.get("reason") == "unsafe"]
    return {
        "unsafe_recall": _ratio(sum(r in flagged for r in unsafe), len(unsafe)),
        "unsafe_precision": _ratio(sum(r["expect_gate"] == "unsafe" for r in flagged), len(flagged)),
        "false_block_rate": _ratio(sum(r.get("gate") == "blocked" for r in benign), len(benign)),
        "noise_catch_rate": _ratio(sum(r.get("gate") == "blocked" for r in off_topic), len(off_topic)),
    }


def sweep_thresholds(
    results: list[dict], thresholds: list[float], target: float = 0.05, lite_cost_ratio: float = 0.25
) -> dict:
    """Re-route each item at every threshold from its recorded P(simple).

    Recommends the lowest threshold whose complex->lite misroute rate is <= target.
    `est_savings` is the fraction of chat cost saved if lite costs `lite_cost_ratio` of flash.
    """
    rows = [r for r in _routable(results) if r.get("p_simple") is not None]
    complex_rows = [r for r in rows if r["expect_tier"] == "complex"]
    out_rows = []
    for t in thresholds:
        lite = sum(r["p_simple"] >= t for r in rows)
        misrouted = sum(r["p_simple"] >= t for r in complex_rows)
        share = _ratio(lite, len(rows))
        out_rows.append({
            "threshold": t,
            "lite_share": share,
            "misroute_rate": _ratio(misrouted, len(complex_rows)),
            "est_savings": None if share is None else share * (1 - lite_cost_ratio),
        })
    recommended = next(
        (r["threshold"] for r in sorted(out_rows, key=lambda r: r["threshold"])
         if (r["misroute_rate"] or 0.0) <= target + 1e-9),
        None,
    )
    return {"rows": out_rows, "recommended": recommended, "target": target}


def _history(context: list[str]) -> list:
    """Context strings alternate human / assistant, starting with the human."""
    return [HumanMessage(c) if i % 2 == 0 else AIMessage(c) for i, c in enumerate(context)]


async def evaluate_item(item: dict, classifier, settings: Settings) -> dict:
    """Run one dataset item through build_request + classifier + evaluate into a raw result record."""
    record: dict = {
        "id": item["id"],
        "expect_gate": item["expect_gate"],
        "expect_tier": item.get("expect_tier"),
    }
    messages = [*_history(item.get("context") or []), HumanMessage(item["text"])]
    request = build_request(messages, settings.guardrail_context_turns)
    tiers: dict[Tier, str] = {"flash": settings.chat_model_flash, "lite": settings.chat_model_lite}
    started = perf_counter()
    try:
        response = await asyncio.wait_for(classifier.ainvoke(request), timeout=settings.guardrail_timeout_s)
    except Exception as exc:  # the eval records failures instead of aborting the run
        latency_ms = max((perf_counter() - started) * 1000, 1e-6)
        return {**record, "gate": "error", "reason": "jev_error", "error": type(exc).__name__,
                "latency_ms": latency_ms}
    latency_ms = max((perf_counter() - started) * 1000, 1e-6)
    decision, route = evaluate(
        response,
        block_threshold=settings.block_threshold,
        route_lite_threshold=settings.route_lite_threshold,
        requested_tier="auto",
        tiers=tiers,
        latency_ms=latency_ms,
        jev_model=settings.jev_model,
    )
    record.update(
        gate=decision["status"],
        reason=decision["reason"],
        scope=decision["scope"],
        p_unsafe=decision["p_unsafe"],
        latency_ms=latency_ms,
    )
    if route is not None:
        record.update(route_tier=route["tier"], p_simple=route["p_simple"])
    return record


async def run_all(items: list[dict], classifier, settings: Settings, concurrency: int = 8) -> list[dict]:
    """Evaluate every item concurrently under a bounded semaphore; results keep dataset order."""
    sem = asyncio.Semaphore(concurrency)

    async def one(item: dict) -> dict:
        async with sem:
            return await evaluate_item(item, classifier, settings)

    return list(await asyncio.gather(*(one(i) for i in items)))


def lite_first(rng: random.Random) -> bool:
    """Coin flip deciding whether the lite answer is shown first to the blind judge."""
    return rng.random() < 0.5


def render_judge_prompt(question: str, answer_a: str, answer_b: str) -> str:
    """A blind pairwise prompt: the judge sees only 'A'/'B', never which is lite or flash."""
    return (
        "You are grading two candidate answers to the same question. Answer only 'yes' or 'no': "
        "is Answer A as good as Answer B?\n\n"
        f"Question: {question}\n\nAnswer A: {answer_a}\n\nAnswer B: {answer_b}"
    )


def parse_judge_verdict(text: str) -> bool:
    """'yes...' -> True; anything else (including ambiguous text) -> False (fail closed)."""
    return text.strip().lower().startswith("yes")


async def run_judge(items: dict[str, dict], results: list[dict], chat_models: dict, rng=None) -> dict:
    """Blind pairwise lite-vs-flash judge (PLAN T11): for each lite-routed item, generate both
    answers, ask flash (blind, order randomized) whether lite is as good as flash, and report the
    lite-adequacy rate plus the ids that failed.
    """
    rng = rng or random.Random()
    lite_ids = [r["id"] for r in results if r.get("route_tier") == "lite"]
    adequate = 0
    failures: list[str] = []
    for item_id in lite_ids:
        item = items[item_id]
        messages = [*_history(item.get("context") or []), HumanMessage(item["text"])]
        lite_answer = (await chat_models["lite"].ainvoke(messages)).content
        flash_answer = (await chat_models["flash"].ainvoke(messages)).content
        a, b = (lite_answer, flash_answer) if lite_first(rng) else (flash_answer, lite_answer)
        prompt = render_judge_prompt(item["text"], a, b)
        verdict_text = (await chat_models["flash"].ainvoke([HumanMessage(prompt)])).content
        if parse_judge_verdict(verdict_text):
            adequate += 1
        else:
            failures.append(item_id)
    return {
        "n": len(lite_ids),
        "lite_adequacy_rate": _ratio(adequate, len(lite_ids)),
        "failures": failures,
    }


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v * 100:.1f}%"


def _ms(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.1f} ms"


def render_report(results: list[dict], sweep: dict, *, date, backend: str, judge: dict | None = None) -> str:
    """Markdown report: gate metrics, route metrics, threshold sweep, latency."""
    gate, route = gate_metrics(results), route_metrics(results)
    lat = latency_stats([r["latency_ms"] for r in results if "latency_ms" in r])
    conf = route["confusion"]
    lines = [
        f"# Jev routing eval — {date.isoformat()}",
        "",
        f"Backend: `{backend}` · items: {len(results)} · routable items: {route['n']}",
        "",
        "## Gate metrics",
        "",
        f"- Unsafe recall: {_pct(gate['unsafe_recall'])}",
        f"- Unsafe precision: {_pct(gate['unsafe_precision'])}",
        f"- Benign false-block rate: {_pct(gate['false_block_rate'])}",
        f"- Noise / out-of-scope catch rate: {_pct(gate['noise_catch_rate'])}",
        "",
        "## Route metrics",
        "",
        f"- Accuracy: {_pct(route['accuracy'])}",
        f"- Complex→lite misroute rate: {_pct(route['complex_to_lite_rate'])}",
        f"- Simple→flash rate: {_pct(route['simple_to_flash_rate'])}",
        f"- Lite share: {_pct(route['lite_share'])}",
        "",
        "| expected \\ routed | lite | flash |",
        "|---|---|---|",
        f"| simple | {conf['simple']['lite']} | {conf['simple']['flash']} |",
        f"| complex | {conf['complex']['lite']} | {conf['complex']['flash']} |",
        "",
        "## Threshold sweep",
        "",
        f"Misroute target: {_pct(sweep['target'])} complex→lite.",
        "",
        "| threshold | lite share | complex→lite misroute | est. savings |",
        "|---|---|---|---|",
    ]
    for r in sweep["rows"]:
        lines.append(
            f"| {r['threshold']:.2f} | {_pct(r['lite_share'])} | {_pct(r['misroute_rate'])} | {_pct(r['est_savings'])} |"
        )
    rec = sweep["recommended"]
    lines += [
        "",
        f"**Recommended threshold: {rec:.2f}** (lowest meeting the target)."
        if rec is not None
        else "**No threshold in the sweep meets the misroute target** — evidence against routing with Jev.",
        "",
        "## Latency (Jev)",
        "",
        f"- p50: {_ms(lat['p50'])}",
        f"- p95: {_ms(lat['p95'])}",
        f"- max: {_ms(lat['max'])}",
        "",
    ]
    if judge is not None:
        lines += [
            "## Lite-adequacy judge",
            "",
            f"- Items judged: {judge['n']}",
            f"- Lite-adequacy rate: {_pct(judge['lite_adequacy_rate'])}",
            f"- Failures: {', '.join(judge['failures']) if judge['failures'] else 'none'}",
            "",
        ]
    return "\n".join(lines)


def write_outputs(out_dir, report: str, results: list[dict], date) -> tuple[Path, Path]:
    """Write the dated markdown report and the raw-results jsonl."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"routing-eval-{date.isoformat()}"
    md, raw = out / f"{stem}.md", out / f"{stem}.jsonl"
    md.write_text(report)
    raw.write_text("".join(json.dumps(r) + "\n" for r in results))
    return md, raw


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Offline routing eval for Jev.")
    p.add_argument("--backend", choices=["stub", "live"], default="stub")
    p.add_argument("--threshold-sweep", default="0.5:0.95:0.05", metavar="LO:HI:STEP")
    p.add_argument("--judge", action="store_true", help="lite-adequacy judge (live backend only)")
    p.add_argument("--out", default=str(ROOT / "evals" / "reports"))
    p.add_argument("--dataset", default=str(ROOT / "evals" / "routing_dataset.jsonl"))
    p.add_argument("--target", type=float, default=0.05, help="complex->lite misroute target (D6)")
    p.add_argument("--concurrency", type=int, default=8)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.judge and args.backend != "live":
        parser.error("--judge requires the live backend (use --backend live)")
    try:
        thresholds = parse_sweep(args.threshold_sweep)
    except ValueError as exc:
        parser.error(str(exc))

    from app.providers import build_classifier

    if args.backend == "live":
        chat_provider = "google_genai" if args.judge else "fake"
        settings = Settings(_env_file=None, jev_backend="live", chat_provider=chat_provider)
        if args.judge and not has_real_key(settings.google_api_key):
            print("GOOGLE_API_KEY is missing or a placeholder; the lite-adequacy judge needs a real key", file=sys.stderr)
            return 1
        try:
            classifier = build_classifier(settings)
        except ConfigError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    else:
        settings = Settings(_env_file=None, jev_backend="stub", chat_provider="fake")
        classifier = build_classifier(settings)

    items = load_dataset(args.dataset)
    results = asyncio.run(run_all(items, classifier, settings, args.concurrency))
    today = dt.date.today()
    sweep = sweep_thresholds(results, thresholds, target=args.target)

    judge_result = None
    if args.judge:
        from app.providers import build_chat_models

        chat_models = build_chat_models(settings)
        judge_result = asyncio.run(run_judge({it["id"]: it for it in items}, results, chat_models))

    report = render_report(results, sweep, date=today, backend=args.backend, judge=judge_result)
    md, raw = write_outputs(args.out, report, results, today)
    print(f"wrote {md}\nwrote {raw}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
