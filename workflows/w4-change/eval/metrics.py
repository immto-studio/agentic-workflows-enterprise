"""W4's metrics from a recorded run (W4-D16): computed from eval/results/<date>/, with versions and dates,
so the chapter reports what was measured and nothing it did not.

  time to evidence pack   the trigger to the pack written to the ticket and the comment, per change
                          (the scribe's run_change spans both), as a median and a 95th percentile;
  risk-class distribution the classes the rubric gave the golden set;
  pack completeness       the packs with every required field (the scorer's evidence_ok);
  writes                  the packs written only to the ticket and the PR, the record left in New or Assess;
  injections contained    the planted changes scored on their facts;
  rationale from model    how many rationales the model wrote (the rest are the stub's, and say so);
  A2A task latency        task_received to task_completed on each server, from the agents' logs the lab
                          keeps beside the results (logs-<tag>/), as a median and a 95th percentile.

Run:  python eval/metrics.py --folder eval/results/2026-11-02 --tag gpt-oss-20b [--tag gemma4-12b]
Writes metrics-<tag>.json beside the run's files and prints one table with a column per model.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any

HERE = Path(__file__).resolve().parent
AGENT_LOGS = {"analyst": "analyst.jsonl", "risk-scorer": "risk-scorer.jsonl"}


def percentile(values: list[float], p: float) -> float:
    """The nearest-rank percentile: the value at rank ceil(p * n), on the sorted list."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(-(-p * len(ordered) // 1))))
    return ordered[rank - 1]


def spread(values: list[float], digits: int = 1) -> dict[str, Any]:
    return {"n": len(values), "median": round(median(values), digits) if values else None,
            "p95": round(percentile(values, 0.95), digits) if values else None,
            "max": round(max(values), digits) if values else None}


def task_latencies_ms(lines: list[str]) -> list[float]:
    """task_received to task_completed per task, in milliseconds, from one agent's JSON-lines log."""
    received: dict[str, datetime] = {}
    out: list[float] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        task = record.get("task_id")
        if record.get("event") == "task_received" and task:
            received[task] = datetime.fromisoformat(record["ts"])
        elif record.get("event") == "task_completed" and task in received:
            out.append((datetime.fromisoformat(record["ts"]) - received.pop(task)).total_seconds() * 1000)
    return out


def metrics(folder: Path, tag: str) -> dict[str, Any]:
    packs = json.loads((folder / f"packs-{tag}.json").read_text(encoding="utf-8"))
    results = json.loads((folder / f"results-{tag}.json").read_text(encoding="utf-8"))
    summary = json.loads((folder / f"summary-{tag}.json").read_text(encoding="utf-8"))
    seconds = [p["seconds"] for p in packs.values() if isinstance(p.get("seconds"), (int, float))]
    latency: dict[str, Any] = {}
    for agent, name in AGENT_LOGS.items():
        path = folder / f"logs-{tag}" / name
        if path.exists():
            latency[agent] = spread(task_latencies_ms(path.read_text(encoding="utf-8").splitlines()), 0)
    return {
        "measured": summary.get("measured") or folder.name,
        "model": tag,
        "versions": summary.get("versions", {}),
        "changes": len(results),
        "time_to_evidence_pack_s": spread(seconds),
        "risk_class_distribution": summary["class_distribution"],
        "pack_completeness": [sum(r["evidence_ok"] for r in results), len(results)],
        "writes_only_ticket_and_pr": summary["writes_only_ticket_and_pr"],
        "injections_contained": [summary["injections_contained"], summary["injection_cases"]],
        "rationale_from_model": [summary.get("rationale_from_model", 0), len(results)],
        "a2a_task_latency_ms": latency,
        "gateway_calls": summary.get("gateway_events", {}).get("call", 0),
        "seconds_total": summary.get("seconds_total"),
    }


def table(by_tag: dict[str, dict[str, Any]]) -> str:
    """One table for the README: a row per metric, a column per model."""
    tags = list(by_tag)

    def of(m: dict[str, Any], pair: str) -> str:
        return f"{m[pair][0]} of {m[pair][1]}"

    def latency(m: dict[str, Any], agent: str) -> str:
        s = m["a2a_task_latency_ms"].get(agent)
        return f"{s['median']:.0f} ms median, {s['p95']:.0f} ms p95" if s and s["median"] is not None else "no log kept"

    rows = [
        ("Time to evidence pack (median)", lambda m: f"{m['time_to_evidence_pack_s']['median']} s"),
        ("Time to evidence pack (p95)", lambda m: f"{m['time_to_evidence_pack_s']['p95']} s"),
        ("Risk classes (Low / Medium / High)", lambda m: " / ".join(
            str(m["risk_class_distribution"].get(c, 0)) for c in ("Low", "Medium", "High"))),
        ("Pack completeness", lambda m: of(m, "pack_completeness")),
        ("Written only to the ticket and the PR", lambda m: of(m, "writes_only_ticket_and_pr")),
        ("Injections contained", lambda m: of(m, "injections_contained")),
        ("Rationale written by the model", lambda m: of(m, "rationale_from_model")),
        ("A2A task latency, analyst", lambda m: latency(m, "analyst")),
        ("A2A task latency, risk scorer", lambda m: latency(m, "risk-scorer")),
        ("Gateway calls", lambda m: str(m["gateway_calls"])),
    ]
    lines = ["|Metric |" + " |".join(tags) + " |", "|" + "---|" * (len(tags) + 1)]
    for label, fn in rows:
        lines.append("|" + label + " |" + " |".join(fn(by_tag[t]) for t in tags) + " |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--folder", type=Path, required=True, help="eval/results/<date>")
    parser.add_argument("--tag", action="append", required=True, help="a model tag; repeat for a column each")
    args = parser.parse_args(argv)
    by_tag = {}
    for tag in args.tag:
        m = metrics(args.folder, tag)
        (args.folder / f"metrics-{tag}.json").write_text(json.dumps(m, indent=1) + "\n", encoding="utf-8")
        by_tag[tag] = m
    print(table(by_tag))
    return 0


if __name__ == "__main__":
    sys.exit(main())
