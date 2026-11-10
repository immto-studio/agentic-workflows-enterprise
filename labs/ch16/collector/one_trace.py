"""A follow-up to step 3b: one W3 incident and one W4 change through the Collector, after each was made one trace.

Chapter 16 (companion #14), with W3's issue #10 and W4's #11. Step 3b found W3's spans scattered, each read and
each session's set-up a trace of its own and each model call a root, and W4's in two trees, the rationale call a
root beside the scribe's span. W3's eval/lab.py now opens one `invoke_agent w3-incident` span an incident and
hands it to every read, write and model call, and W4's risk scorer hands its span's traceparent to the rationale
seam. run_workflows.py runs one case of each again with --only, a smoke run analyze_workflows.py doesn't keep, so
this keeps those two runs next to step 3b's results, in the same two steps:

- `extract` copies a raw run's Collector side as analyze_workflows.extract does (the span file, a digest of every
  span the tap saw, when each kept span left, the sampler's counters, the meta) and the case: its trace id, its
  verdict, and the gateway's lines for it, all with this machine's paths taken out. Nothing goes to the
  workflows' eval/traced/, whose files step 3b's test holds as they are.
- `summarize` computes from those files alone what the case's trace id holds (analyze_workflows.coverage: the spans,
  the roots, the spans elsewhere that name the case, the traces that name no case), which processes sent spans,
  and step 3b's row for the same case beside it, and writes one-trace.json and summary.md. Two runs write the same
  bytes.

Run (from labs/ch16, one model on the GPU, Ollama 0.22.1 serving gpt-oss-20b):
    python collector/run_workflows.py w3 --only w3-01
    python collector/run_workflows.py w4 --model gpt-oss-20b --only w4-01
    python collector/one_trace.py <the two raw folders, collector/_lab/<stamp>-*-smoke> --out results/2026-11-03/one-trace
    python collector/one_trace.py --summarize results/2026-11-03/one-trace
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import analyze  # noqa: E402  step 3's: read_jsonl, write_jsonl
import analyze_workflows as aw  # noqa: E402  step 3b's: digests, departures, scrub, coverage, run_name

LAB = HERE.parent
STEP_3B = LAB / "results" / aw.DATE / "workflows"
FILES = ("spans.jsonl", "tap.jsonl", "sink.jsonl", "tail-sampling.prom", "meta.json", "case.json", "gateway.jsonl")


def _case(raw: Path, meta: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The one case the run made, as the workflow's own results keep it, and the gateway's lines for its trace id."""
    model, results = meta["model"], raw / "results"
    if meta["workflow"] == "w3":
        runs = json.loads((results / f"runs-{model}.json").read_text(encoding="utf-8"))
        traces = json.loads((results / f"trace-ids-{model}.json").read_text(encoding="utf-8"))
        [record] = runs["records"]
        case = {"workflow": "w3", "case": record["id"], "trace_id": traces[record["id"]],
                "passed": record["id"] not in runs["summary"]["failed"], "state": record["state"],
                "proposal": record["proposal"], "executed": record["executed"], "model_calls": len(record["labels"]),
                "tool_calls": len(record["reads"]), "seconds": record.get("seconds")}
        lines = analyze.read_jsonl(raw / "logs" / "gateway.jsonl")
    elif meta["workflow"] == "w4":
        packs = json.loads((results / f"packs-{model}.json").read_text(encoding="utf-8"))
        verdicts = {r["id"]: r["pass"] for r in json.loads((results / f"results-{model}.json").read_text(encoding="utf-8"))}
        [(name, pack)] = packs.items()
        case = {"workflow": "w4", "case": name, "trace_id": pack["trace_id"], "passed": verdicts.get(name),
                "risk_class": (pack.get("risk") or {}).get("risk_class"),
                "rationale_source": (pack.get("risk") or {}).get("rationale_source"), "seconds": pack.get("seconds")}
        lines = analyze.read_jsonl(results / f"logs-{model}" / "gateway.jsonl")
    else:
        raise SystemExit(f"{raw.name}: one_trace keeps W3's and W4's runs; step 3b's results hold W5's night")
    return case, [line for line in lines if line.get("trace_id") == case["trace_id"]]


def extract(raw: Path, out: Path) -> str:
    """One raw run of one case into results/<date>/one-trace/<run>/."""
    meta = json.loads((raw / "meta.json").read_text(encoding="utf-8"))
    name = aw.run_name(meta)
    dst = out / name
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "spans.jsonl").write_text(aw.scrub((raw / "spans.jsonl").read_text(encoding="utf-8")), encoding="utf-8",
                                     newline="\n")
    analyze.write_jsonl(dst / "tap.jsonl", aw.digests(raw / "tap.jsonl"))
    analyze.write_jsonl(dst / "sink.jsonl", aw.departures(raw / "sink.jsonl"))
    prom = [line for line in (raw / "metrics.txt").read_text(encoding="utf-8").splitlines()
            if line.startswith("otelcol_processor_tail_sampling")]
    (dst / "tail-sampling.prom").write_text("".join(f"{line}\n" for line in prom), encoding="utf-8", newline="\n")
    (dst / "meta.json").write_text(aw.scrub(json.dumps(meta, indent=2, sort_keys=True) + "\n"), encoding="utf-8", newline="\n")
    case, lines = _case(raw, meta)
    (dst / "case.json").write_text(aw.scrub(json.dumps(case, indent=2, sort_keys=True) + "\n"), encoding="utf-8", newline="\n")
    (dst / "gateway.jsonl").write_text(aw.scrub("".join(json.dumps(line) + "\n" for line in lines)), encoding="utf-8",
                                       newline="\n")
    return name


# --- the summary ----------------------------------------------------------------------------------------------------

def one_tree(tap: list[dict[str, Any]], trace_id: str) -> bool:
    """Whether every span under the trace id reaches one root through parents under the same trace id."""
    spans = {d["span_id"]: d for d in tap if d["trace_id"] == trace_id}
    roots = {s for s, d in spans.items() if d["parent_span_id"] not in spans}
    if len(roots) != 1:
        return False
    for span in spans.values():
        seen: set[str] = set()
        while span["parent_span_id"] in spans and span["span_id"] not in seen:
            seen.add(span["span_id"])
            span = spans[span["parent_span_id"]]
        if span["span_id"] not in roots:
            return False
    return True


def step_3b(run: str, case: str) -> dict[str, Any] | None:
    """Step 3b's row for the same case, from its committed workflows.json, and what its whole run left naming no
    case at all (W3's sessions' set-up), for the comparison."""
    path = STEP_3B / "workflows.json"
    if not path.exists():
        return None
    cover = json.loads(path.read_text(encoding="utf-8"))["coverage"].get(run)
    row = next((r for r in (cover or {}).get("rows", []) if r["case"] == case), None)
    if row is None:
        return None
    return {"row": row, "cases": len(cover["rows"]), "unnamed_traces": cover["unnamed_traces"],
            "unnamed_spans": cover["unnamed_spans"]}


def summarize(out: Path) -> dict[str, Any]:
    data: dict[str, Any] = {"runs": {}}
    for folder in sorted(p for p in out.iterdir() if p.is_dir()):
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        case = json.loads((folder / "case.json").read_text(encoding="utf-8"))
        tap = analyze.read_jsonl(folder / "tap.jsonl")
        sink = analyze.read_jsonl(folder / "sink.jsonl")
        calls = [line for line in analyze.read_jsonl(folder / "gateway.jsonl") if line.get("event") == "call"]
        cover = aw.coverage({"tap": tap, "cases": [case]})
        [row] = cover["rows"]
        data["runs"][folder.name] = {
            "workflow": meta["workflow"], "model": meta["model"], "case": case, "gateway_calls": len(calls),
            "spans_sent": len(tap), "spans_left_the_sampler": len(sink),
            "processes": dict(sorted(Counter(d["service"] for d in tap).items())),
            "traces_at_the_collector": cover["traces_at_the_collector"], "row": row,
            "one_tree": one_tree(tap, case["trace_id"]) and not row["other_traces"] and not cover["unnamed_traces"],
            "unnamed_traces": cover["unnamed_traces"], "unnamed_spans": cover["unnamed_spans"],
            "collector_exit": meta.get("collector_exit"), "all_kept_spans_at_the_sink": meta.get("all_kept_spans_at_the_sink"),
            "share_percent": meta.get("share_percent"), "step_3b": step_3b(folder.name, case["case"]),
        }
    analyze.write_json(out / "one-trace.json", data)
    (out / "summary.md").write_text(render(data), encoding="utf-8", newline="\n")
    return data


def _roots(names: dict[str, int]) -> str:
    return "; ".join(f"{k} ({v})" for k, v in sorted(names.items())) or "none"


def render(data: dict[str, Any]) -> str:
    out = ["# Chapter 16, a follow-up to step 3b: one W3 incident and one W4 change as one trace each", "",
           "Each case ran again through its workflow's own harness, servers and gateway on gpt-oss-20b, every process "
           "sending OTLP to the pinned Collector (`collector/run_workflows.py --only`), after W3's eval/lab.py began "
           "opening one `invoke_agent w3-incident` span an incident and W4's risk scorer began handing its span's "
           "traceparent to the rationale seam. Every table below is computed by `collector/one_trace.py --summarize` "
           "from the files in this folder; step 3b's columns come from `../workflows/workflows.json`.", "",
           "## What the case's trace id holds", "",
           "|Run |Case |Passed |Model calls |Spans sent |Under the case's trace id |Roots |The root |Spans elsewhere naming "
           "the case |Traces naming no case |One tree |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, run in data["runs"].items():
        row, case = run["row"], run["case"]
        out.append(f"|{aw.NAMES[run['workflow']]}, {run['model']} |{case['case']} |{'yes' if case['passed'] else 'no'} "
                   f"|{run['gateway_calls']} |{run['spans_sent']} |{row['spans']} |{row['roots']} |{_roots(row['root_names'])} "
                   f"|{row['spans_in_other_traces']} |{run['unnamed_traces']} |{'yes' if run['one_tree'] else 'no'} |")
    out += ["", "## The same case in step 3b", "",
            "|Run |Case |Under the case's trace id |Roots |The roots |Traces elsewhere naming the case |Their spans "
            "|The whole run's traces naming no case (cases) |",
            "|---|---|---|---|---|---|---|---|"]
    for name, run in data["runs"].items():
        before = run["step_3b"]
        if before:
            row = before["row"]
            out.append(f"|{aw.NAMES[run['workflow']]}, {run['model']} |{row['case']} |{row['spans']} |{row['roots']} "
                       f"|{_roots(row['root_names'])} |{row['other_traces']} |{row['spans_in_other_traces']} "
                       f"|{before['unnamed_traces']} of {before['unnamed_spans']} spans ({before['cases']}) |")
    out += ["", "## Which processes sent spans", "", "|Run |service.name |Spans sent |", "|---|---|---|"]
    for name, run in data["runs"].items():
        for service, n in run["processes"].items():
            out.append(f"|{aw.NAMES[run['workflow']]}, {run['model']} |{service} |{n} |")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("raw", nargs="*", type=Path, help="raw run folders, collector/_lab/<stamp>-<run>-smoke")
    parser.add_argument("--out", type=Path, help="the results folder, results/2026-11-03/one-trace")
    parser.add_argument("--summarize", type=Path, help="write the summary again from a results folder")
    args = parser.parse_args(argv)
    if args.summarize:
        summarize(args.summarize)
        print(f"summary written in {args.summarize}")
        return 0
    if not (args.raw and args.out):
        parser.error("give raw run folders and --out, or --summarize")
    for raw in args.raw:
        print(f"{raw.name} -> {extract(raw, args.out)}")
    summarize(args.out)
    print(f"results written in {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
