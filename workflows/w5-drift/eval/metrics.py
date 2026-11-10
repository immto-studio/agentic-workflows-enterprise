"""W5's metrics from a recorded run (W5-D14): computed from the ledger, the night records, and the gateway
log under eval/results/<date>/, with versions and dates, so the chapter reports what was measured.

  findings per night        by kind, from each night's record;
  pull requests             opened and updated per night, and the suppressed;
  bodies                    who wrote them (the model or the stub), and the forbidden words refused;
  duration                  each night's, from the trigger to the ledger saved;
  the agent's own cost      the gateway's calls and prompt and completion tokens per night, counted from
                            the gateway log the lab keeps (logs-<tag>/gateway.jsonl) by the night's trace
                            id, with the latency per call; the night record's own count (read while the
                            gateway was still writing) is kept beside it as `cost_as_recorded`;
  savings                   proposed and realized as shares of the accounts' spend and of each other, and
                            as counts, from ledger.summary(month): never a currency (W5-D10).

Run:  python eval/metrics.py --folder eval/results/2026-11-03 --tag gpt-oss-20b [--tag gemma4-12b] [--print]
Writes metrics-<tag>.json beside the run's files; with --print, renders one table with a column per model.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import median
from typing import Any

HERE = Path(__file__).resolve().parent
W5 = HERE.parent
for folder in (W5 / "writer", W5 / "detect", W5 / "servers"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from ledger import Ledger  # noqa: E402

__all__ = ["TYPOGRAPHIC", "percentile", "spread", "gateway_lines", "night_metrics", "prose_metrics", "metrics", "table"]

TYPOGRAPHIC = "‐‑‒–—−  "  # score.TYPOGRAPHIC, without importing the scorer here


def percentile(values: list[float], p: float) -> float:
    """The nearest-rank percentile: the value at rank ceil(p * n), on the sorted list (W4's)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(-(-p * len(ordered) // 1))))
    return ordered[rank - 1]


def spread(values: list[float], digits: int = 1) -> dict[str, Any]:
    return {"n": len(values), "median": round(median(values), digits) if values else None,
            "p95": round(percentile(values, 0.95), digits) if values else None,
            "max": round(max(values), digits) if values else None}


def gateway_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def night_metrics(record: dict[str, Any], lines: list[dict[str, Any]], result: dict[str, Any] | None = None) -> dict[str, Any]:
    """One night's row from its record and the gateway lines of its trace id."""
    trace = record.get("trace_id")
    mine = [line for line in lines if line.get("trace_id") == trace]
    calls = [line for line in mine if line.get("event") == "call"]
    counts = record.get("counts") or {}
    return {
        "id": record.get("golden_id"), "night": record.get("night"), "trigger": (record.get("trigger") or {}).get("kind"),
        "workspaces": record.get("workspaces_read") or [], "trace_id": trace,
        "findings": counts.get("findings", 0), "by_kind": counts.get("by_kind") or {},
        "pull_requests": counts.get("pull_requests") or {},
        "body_sources": record.get("body_sources") or {}, "refused_words": record.get("refused_words") or {},
        "duration_s": record.get("duration_s"), "seconds": record.get("seconds"),
        "cost_as_recorded": record.get("cost") or {},
        "gateway": {"calls": len(calls),
                    "prompt_tokens": sum(int(c.get("prompt_tokens") or 0) for c in calls),
                    "completion_tokens": sum(int(c.get("completion_tokens") or 0) for c in calls),
                    "refused": sum(1 for line in mine if line.get("event") == "refused"),
                    "failed": sum(1 for line in mine if line.get("event") == "failed"),
                    "latency_ms": spread([float(c["latency_ms"]) for c in calls if c.get("latency_ms") is not None], 0),
                    "served": sorted({str(c.get("served_alias")) for c in calls})},
        "pass": None if result is None else result.get("pass"),
    }


def prose_metrics(packs_path: Path) -> dict[str, Any]:
    """How the model wrote, from the pull requests as opened: the words of the prose above the facts per
    body, and the typographic characters (the non-breaking hyphen U+2011 apart) in its titles and prose."""
    out: dict[str, Any] = {"model_bodies": 0, "words": spread([]), "u2011": 0, "bodies_with_u2011": 0, "other_typographic": 0}
    if not packs_path.exists():
        return out
    words: list[float] = []
    for night in json.loads(packs_path.read_text(encoding="utf-8")).values():
        for pack in night.values():
            if pack.get("body_source") != "model":
                continue
            prose_part = (pack.get("body") or "").split("## Facts")[0]
            text = (pack.get("title") or "") + "\n" + prose_part
            words.append(float(len(prose_part.split())))
            nb = text.count("‑")
            out["u2011"] += nb
            out["bodies_with_u2011"] += bool(nb)
            out["other_typographic"] += sum(text.count(c) for c in TYPOGRAPHIC if c != "‑")
    out["model_bodies"] = len(words)
    out["words"] = spread(words, 0)
    return out


def metrics(folder: Path, tag: str) -> dict[str, Any]:
    results = json.loads((folder / f"results-{tag}.json").read_text(encoding="utf-8"))
    summary = json.loads((folder / f"summary-{tag}.json").read_text(encoding="utf-8"))
    nights_dir = folder / f"nights-{tag}"
    lines = gateway_lines(folder / f"logs-{tag}" / "gateway.jsonl")
    nights = []
    for result in results:
        path = nights_dir / f"{result['id']}.json"
        if path.exists():
            nights.append(night_metrics(json.loads(path.read_text(encoding="utf-8")), lines, result))
    calls = [line for line in lines if line.get("event") == "call"]
    refused: list[str] = []
    for night in nights:
        for words in night["refused_words"].values():
            refused += [w for w in words if w not in refused]
    totals = {
        "findings": sum(n["findings"] for n in nights),
        "opened": sum(n["pull_requests"].get("opened", 0) for n in nights),
        "updated": sum(n["pull_requests"].get("updated", 0) for n in nights),
        "suppressed": sum(n["pull_requests"].get("suppressed", 0) for n in nights),
        "skipped": sum(n["pull_requests"].get("skipped", 0) for n in nights),
        "bodies_from_model": sum(n["body_sources"].get("model", 0) for n in nights),
        "bodies_written": sum(sum(n["body_sources"].values()) for n in nights),
        "refused_words": sum(len(w) for n in nights for w in n["refused_words"].values()),
        "refused_word_list": refused,
        "seconds": round(sum(n["duration_s"] or 0.0 for n in nights), 1),
        "gateway_calls": sum(n["gateway"]["calls"] for n in nights),
        "prompt_tokens": sum(n["gateway"]["prompt_tokens"] for n in nights),
        "completion_tokens": sum(n["gateway"]["completion_tokens"] for n in nights),
        "gateway_calls_in_log": len(calls),
        "latency_ms": spread([float(c["latency_ms"]) for c in calls if c.get("latency_ms") is not None], 0),
    }
    totals["prose"] = prose_metrics(folder / f"packs-{tag}.json")
    ledger_path = nights_dir / "ledger.json"
    savings: dict[str, Any] | None = None
    if ledger_path.exists() and nights:
        month = (nights[0]["night"] or "")[:7]
        led = Ledger(ledger_path)
        month_summary = led.summary(month)
        savings = {"month": month, **month_summary["savings"], "pull_requests_by_state": {s: month_summary["pull_requests"][s] for s in ("open", "merged", "closed")},
                   "findings_seen": month_summary["findings"]["seen"], "findings_suppressed": month_summary["findings"]["suppressed"],
                   "with_estimate": month_summary["findings"]["with_estimate"], "accounts_read": month_summary["agent"]["accounts_read"]}
    return {
        "measured": summary.get("measured") or folder.name,
        "model": tag,
        "versions": summary.get("versions", {}),
        "nights": nights,
        "totals": totals,
        "savings": savings,
        "nights_passed": [summary.get("passed"), summary.get("nights")],
    }


def table(by_tag: dict[str, dict[str, Any]]) -> str:
    """One table for the README: a row per metric, a column per model; per-night values in the nights' order."""
    tags = list(by_tag)

    def per_night(m: dict[str, Any], fn: Any) -> str:
        return " / ".join(str(fn(n)) for n in m["nights"])

    def share(value: float | None) -> str:
        return "none" if value is None else f"{value * 100:.2f} %"

    def latency(m: dict[str, Any]) -> str:
        s = m["totals"]["latency_ms"]
        return f"{s['median'] / 1000:.1f} s median, {s['p95'] / 1000:.1f} s p95" if s["median"] is not None else "no gateway call"

    rows = [
        ("Findings per night", lambda m: per_night(m, lambda n: n["findings"])),
        ("Pull requests opened per night", lambda m: per_night(m, lambda n: n["pull_requests"].get("opened", 0))),
        ("Pull requests updated per night", lambda m: per_night(m, lambda n: n["pull_requests"].get("updated", 0))),
        ("Suppressed per night", lambda m: per_night(m, lambda n: n["pull_requests"].get("suppressed", 0))),
        ("Bodies written by the model", lambda m: f"{m['totals']['bodies_from_model']} of {m['totals']['bodies_written']}"),
        ("Refused words", lambda m: str(m["totals"]["refused_words"]) + (f" ({', '.join(m['totals']['refused_word_list'])})"
                                                                         if m["totals"]["refused_word_list"] else "")),
        ("Night duration", lambda m: per_night(m, lambda n: f"{n['duration_s']:.1f} s")),
        ("Gateway calls per night", lambda m: per_night(m, lambda n: n["gateway"]["calls"])),
        ("Prompt tokens per night", lambda m: per_night(m, lambda n: n["gateway"]["prompt_tokens"])),
        ("Completion tokens per night", lambda m: per_night(m, lambda n: n["gateway"]["completion_tokens"])),
        ("Model latency per body", latency),
        ("Prose words per model body (median)", lambda m: "no model body" if m["totals"]["prose"]["words"]["median"] is None
         else f"{m['totals']['prose']['words']['median']:.0f}"),
        ("Non-breaking hyphens (U+2011) in model prose", lambda m: f"{m['totals']['prose']['u2011']} in "
         f"{m['totals']['prose']['bodies_with_u2011']} of {m['totals']['prose']['model_bodies']} bodies"),
        ("Savings proposed, share of spend", lambda m: share((m["savings"] or {}).get("proposed_share_of_spend"))),
        ("Savings realized, share of proposed", lambda m: share((m["savings"] or {}).get("realized_share_of_proposed"))),
        ("Findings realized", lambda m: str((m["savings"] or {}).get("realized_findings", 0))),
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
    parser.add_argument("--print", action="store_true", help="render the markdown table")
    args = parser.parse_args(argv)
    by_tag = {}
    for tag in args.tag:
        m = metrics(args.folder, tag)
        (args.folder / f"metrics-{tag}.json").write_text(json.dumps(m, indent=1) + "\n", encoding="utf-8")
        by_tag[tag] = m
    if args.print:
        print(table(by_tag))
    return 0


if __name__ == "__main__":
    sys.exit(main())
