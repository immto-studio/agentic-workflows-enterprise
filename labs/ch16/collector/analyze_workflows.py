"""Step 3b's results: what each workflow sent the Collector, what a run's trace id holds, fig-16-01, and W5's
night under the two sampler settings.

Chapter 16, step 3b (companion #14, O-D3, O-D5, O-D18). run_workflows.py leaves each run's raw records in a
git-ignored folder. As step 3's analyze.py does, this works in two steps, so the summary can always be checked
against what is committed:

- `extract` copies what the results keep. Each workflow's own results and its gateway's cost lines go to the
  workflow's eval/traced/<date>/, as its lab writes them, with this machine's paths taken out: outside
  eval/results/, because chapter 15's registry takes every run there as one of the runs its replay, judge and
  tests were built on. Into results/<date>/workflows/<run>/ go the Collector's span file, a digest of every span
  the tap saw (ids, parent, name, service, times, when it arrived, and the attributes the policies read), when
  each kept span reached the sink with the share and policy it carries, the Collector's tail-sampling counters, the run's meta, and for W2 and W5 the stores join.py reads.
- `summarize` computes every table from those files alone and writes summary.md, workflows.json and
  fig-16-01-trace.json. Two runs of it write the same bytes.

Run (from labs/ch16):
    python collector/analyze_workflows.py collector/_lab/<stamp>-<run> ... --out results/2026-11-03/workflows
    python collector/analyze_workflows.py --summarize results/2026-11-03/workflows
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import analyze  # noqa: E402  step 3's: scrub, read_jsonl, write_jsonl, write_json
import fake_otlp  # noqa: E402
import join  # noqa: E402
import policies  # noqa: E402

COMPANION = policies.COMPANION
DATE = "2026-11-03"
TRACED = "traced"
WORKFLOW_DIRS = {"w2": "w2-ops-assistant", "w3": "w3-incident", "w4": "w4-change", "w5": "w5-drift"}
NAMES = {"w2": "W2", "w3": "W3", "w4": "W4", "w5": "W5"}
RUNS = ("w2", "w3", "w4-gpt-oss-20b", "w4-gemma4-12b", "w5-step3", "w5-root")
FIGURE = "fig-16-01-trace.json"
CONFIG_SHARE = 10.0  # config.yaml's share of the rest
# What a digest keeps of a span's attributes: what the policies read, the trace id the processes write as an
# attribute, and what names the operation.
DIGEST_ATTRIBUTES = ("larkspur.trace_id", "larkspur.workflow", "larkspur.cost_usd", "larkspur.refused",
                     "larkspur.fallback", "error.type", "gen_ai.operation.name", "gen_ai.tool.name",
                     "gen_ai.request.model", "gen_ai.response.model", "gen_ai.usage.input_tokens",
                     "gen_ai.usage.output_tokens")
FIGURE_ATTRIBUTES = ("gen_ai.operation.name", "gen_ai.agent.name", "gen_ai.request.model", "gen_ai.response.model",
                     "gen_ai.tool.name", "gen_ai.usage.input_tokens", "gen_ai.usage.output_tokens", "larkspur.cost_usd",
                     "larkspur.deployment", "larkspur.region", "larkspur.workflow", "larkspur.data_class",
                     "larkspur.fallback", "larkspur.identity", "larkspur.refused", "mcp.method.name", "error.type")


def write_json(path: Path, data: Any) -> None:
    analyze.write_json(path, data)


def traced_folder(workflow: str, day: str = DATE) -> Path:
    """Where a workflow's step 3b run is kept: beside its results/, never in it (chapter 15's registry)."""
    return COMPANION / "workflows" / WORKFLOW_DIRS[workflow] / "eval" / TRACED / day


def run_name(meta: Mapping[str, Any]) -> str:
    workflow = meta["workflow"]
    if workflow == "w4":
        return f"w4-{meta['model']}"
    if workflow == "w5":
        return f"w5-{meta['wait']}"
    return workflow


def scrub(text: str) -> str:
    """A kept file's text without this machine's paths: the companion's root as <companion> in each form a file
    holds it, then step 3's scrub for any other absolute path."""
    root = str(COMPANION)
    for form in (json.dumps(root)[1:-1], root, root.replace("\\", "/")):
        text = text.replace(form, "<companion>")
    return analyze.scrub(text)


def copy_scrubbed(source: Path, dest: Path, *, relative_locks: bool = False) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if relative_locks:  # a harness's lines name its lock files: repository-relative, as step 3 keeps them
        lines = [analyze._relative(json.loads(line)) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
        text = "".join(json.dumps(line) + "\n" for line in lines)
    else:
        text = source.read_text(encoding="utf-8")
    dest.write_text(scrub(text), encoding="utf-8", newline="\n")


# --- extract ----------------------------------------------------------------------------------------------------

def digest(span: Mapping[str, Any], received_at: float | None = None) -> dict[str, Any]:
    """One span as the summary reads it: ids, parent, name, service, times, status, when it arrived, the share
    and policy a kept span records, and the attributes the policies read. Content keys are named, never valued."""
    attrs = span["attributes"]
    content = {k for k in attrs if policies.is_content(k)} | {k for e in span["events"] for k in e["attributes"]
                                                              if policies.is_content(k)}
    out: dict[str, Any] = {
        "trace_id": span["trace_id"], "span_id": span["span_id"], "parent_span_id": span["parent_span_id"],
        "name": span["name"], "service": span["resource"].get("service.name"), "kind": span["kind"],
        "status": span["status"], "start_ns": span["start_ns"], "end_ns": span["end_ns"],
        "attributes": {k: attrs[k] for k in DIGEST_ATTRIBUTES if k in attrs}, "content": sorted(content)}
    if received_at is not None:
        out["received_at"] = round(received_at, 3)
    if span.get("trace_state"):
        out["trace_state"] = span["trace_state"]
    if policy := (span.get("scope_attributes") or {}).get("tailsampling.policy"):
        out["policy"] = policy
    return out


def digests(path: Path) -> list[dict[str, Any]]:
    return [digest(span, record["received_at"]) for record in fake_otlp.iter_records(path) for span in record["spans"]]


SINK_FIELDS = ("trace_id", "span_id", "received_at", "trace_state", "policy")


def departures(path: Path) -> list[dict[str, Any]]:
    """What the sink adds to the tap's digest of the same span: when it left, and the share and policy it carries."""
    return [{k: d[k] for k in SINK_FIELDS if k in d} for d in digests(path)]


def extract(raw: Path, out: Path) -> str:
    """One raw run into the results: the Collector's side here, the workflow's own results to eval/traced/."""
    meta = json.loads((raw / "meta.json").read_text(encoding="utf-8"))
    if meta.get("only"):
        raise SystemExit(f"{raw.name} ran only {meta['only']}: a smoke run isn't kept")
    name, model = run_name(meta), meta["model"]
    dst = out / name
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "spans.jsonl").write_text(scrub((raw / "spans.jsonl").read_text(encoding="utf-8")), encoding="utf-8",
                                     newline="\n")
    analyze.write_jsonl(dst / "tap.jsonl", digests(raw / "tap.jsonl"))
    analyze.write_jsonl(dst / "sink.jsonl", departures(raw / "sink.jsonl"))
    prom = [line for line in (raw / "metrics.txt").read_text(encoding="utf-8").splitlines()
            if line.startswith("otelcol_processor_tail_sampling")]
    (dst / "tail-sampling.prom").write_text("".join(f"{line}\n" for line in prom), encoding="utf-8", newline="\n")
    (dst / "meta.json").write_text(scrub(json.dumps(meta, indent=2, sort_keys=True) + "\n"), encoding="utf-8", newline="\n")
    logs, results = raw / "logs", raw / "results"
    workflow = meta["workflow"]
    if workflow == "w2":
        traced = traced_folder("w2")
        copy_scrubbed(results / f"answers-{model}.json", traced / f"answers-{model}.json")
        for name_ in ("gateway", "harness", "kubernetes-server", "metrics-server", "logs-server"):
            copy_scrubbed(logs / f"{name_}.jsonl", traced / f"logs-{model}" / f"{name_}.jsonl", relative_locks=name_ == "harness")
        # The four stores join.py reads, side by side: the servers' three logs as one, in time order.
        copy_scrubbed(logs / "harness.jsonl", dst / "harness.jsonl", relative_locks=True)
        copy_scrubbed(logs / "gateway.jsonl", dst / "gateway.jsonl")
        servers = sorted((line for s in ("kubernetes", "metrics", "logs")
                          for line in analyze.read_jsonl(logs / f"{s}-server.jsonl")), key=lambda line: line.get("ts", ""))
        (dst / "server.jsonl").write_text(scrub("".join(json.dumps(line) + "\n" for line in servers)), encoding="utf-8",
                                          newline="\n")
    elif workflow == "w3":
        traced = traced_folder("w3")
        for file in (f"runs-{model}.json", f"trace-ids-{model}.json"):
            copy_scrubbed(results / file, traced / file)
        for source in sorted(logs.glob("*.jsonl")):
            copy_scrubbed(source, traced / f"logs-{model}" / source.name)
    elif workflow == "w4":
        traced = traced_folder("w4")
        for source in sorted(results.rglob("*")):
            if source.is_file():
                copy_scrubbed(source, traced / source.relative_to(results))
    else:
        night = json.loads((results / "night.json").read_text(encoding="utf-8"))
        copy_scrubbed(results / "night.json", dst / "night.json")
        log = Path(night["record"]["log_file"]).name
        copy_scrubbed(raw / "night" / log, dst / "night.jsonl", relative_locks=True)
        for source in sorted(logs.glob("*.jsonl")):
            copy_scrubbed(source, dst / source.name)
    return name


# --- reading a run back -------------------------------------------------------------------------------------------

def by_trace(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    out: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        out.setdefault(row["trace_id"], []).append(row)
    return out


def as_span(d: Mapping[str, Any]) -> dict[str, Any]:
    """A digest in the flat shape policies.features reads."""
    return {"status": d["status"], "attributes": d["attributes"], "resource": {}, "start_ns": d["start_ns"],
            "end_ns": d["end_ns"]}


def gateway_lines(name: str, folder: Path, model: str) -> list[dict[str, Any]]:
    workflow = name.split("-")[0]
    if workflow == "w5":
        return analyze.read_jsonl(folder / "gateway.jsonl")
    return analyze.read_jsonl(traced_folder(workflow) / f"logs-{model}" / "gateway.jsonl")


def cases(name: str, folder: Path, model: str) -> list[dict[str, Any]]:
    """Each case of the run in its golden order: its trace id, its verdict, its model calls and tool calls, as the
    workflow's own records keep them."""
    workflow = name.split("-")[0]
    traced = traced_folder(workflow) if workflow != "w5" else None
    if workflow == "w2":
        answers = json.loads((traced / f"answers-{model}.json").read_text(encoding="utf-8"))
        trace_of = {}
        for line in analyze.read_jsonl(traced / f"logs-{model}" / "harness.jsonl"):
            trace_of.setdefault(line["case"], line["trace_id"])
        return [{"case": r["id"], "trace_id": trace_of[r["id"]], "passed": r["passed"], "model_calls": len(r["model_calls"]),
                 "tool_calls": len(r["read_events"]), "seconds": r["seconds"]} for r in answers["results"]]
    if workflow == "w3":
        runs = json.loads((traced / f"runs-{model}.json").read_text(encoding="utf-8"))
        traces = json.loads((traced / f"trace-ids-{model}.json").read_text(encoding="utf-8"))
        failed = set(runs["summary"]["failed"])
        return [{"case": r["id"], "trace_id": traces[r["id"]], "passed": r["id"] not in failed, "model_calls": len(r["labels"]),
                 "tool_calls": len(r["reads"]), "seconds": r.get("seconds")} for r in runs["records"]]
    if workflow == "w4":
        packs = json.loads((traced / f"packs-{model}.json").read_text(encoding="utf-8"))
        verdicts = {r["id"]: r["pass"] for r in json.loads((traced / f"results-{model}.json").read_text(encoding="utf-8"))}
        return [{"case": case, "trace_id": pack["trace_id"], "passed": verdicts.get(case), "model_calls": 1, "tool_calls": None,
                 "seconds": pack.get("seconds")} for case, pack in sorted(packs.items())]
    night = json.loads((folder / "night.json").read_text(encoding="utf-8"))
    events = analyze.read_jsonl(folder / "night.jsonl")
    return [{"case": night["golden_id"], "trace_id": night["record"]["trace_id"], "passed": night["result"]["pass"],
             "model_calls": night["record"]["cost"]["gateway_calls"],
             "tool_calls": sum(1 for e in events if e.get("event") == "tool_call"), "seconds": night["record"]["duration_s"]}]


def load(folder: Path) -> dict[str, Any]:
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    name = run_name(meta)
    return {"name": name, "meta": meta, "tap": analyze.read_jsonl(folder / "tap.jsonl"),
            "sink": analyze.read_jsonl(folder / "sink.jsonl"), "file": fake_otlp.spans_from_file(folder / "spans.jsonl"),
            "prom": (folder / "tail-sampling.prom").read_text(encoding="utf-8").splitlines(),
            "cases": cases(name, folder, meta["model"]), "lines": gateway_lines(name, folder, meta["model"])}


def _spread(values: list[float], digits: int = 2) -> dict[str, float] | None:
    if not values:
        return None
    return {"min": round(min(values), digits), "median": round(statistics.median(values), digits),
            "max": round(max(values), digits), "n": len(values)}


# --- the tables ---------------------------------------------------------------------------------------------------

def run_row(run: dict[str, Any]) -> dict[str, Any]:
    meta, lines = run["meta"], run["lines"]
    calls = [line for line in lines if line.get("event") == "call"]
    ollama = next(p for p in meta["processes"] if p["service"] is None)
    return {"run": run["name"], "workflow": meta["workflow"], "model": meta["model"], "ollama": ollama["process"],
            "think": meta.get("think", "model default"), "cases": len(run["cases"]),
            "passed": sum(1 for c in run["cases"] if c["passed"]), "calls": len(calls),
            "failed_calls": sum(1 for line in lines if line.get("event") == "failed"),
            "input_tokens": sum(line["prompt_tokens"] or 0 for line in calls),
            "output_tokens": sum(line["completion_tokens"] or 0 for line in calls),
            "model_seconds": round(sum(line.get("latency_ms") or 0 for line in calls) / 1000, 1),
            "run_seconds": round(sum(c["seconds"] or 0 for c in run["cases"]), 1), "share_percent": meta["share_percent"], "decision_wait_s": meta["decision_wait_s"],
            "decision_wait_after_root_received": meta.get("decision_wait_after_root_received"),
            "lines_per_case_match": all(sum(1 for line in calls if line["trace_id"] == c["trace_id"]) == c["model_calls"]
                                        for c in run["cases"])}


def processes(run: dict[str, Any]) -> list[dict[str, Any]]:
    sent = Counter(d["service"] for d in run["tap"])
    kept = Counter(s["resource"].get("service.name") for s in run["file"])
    rows = [{"process": p["process"], "service": p["service"], "sent": sent.get(p["service"], 0) if p["service"] else 0,
             "kept": kept.get(p["service"], 0) if p["service"] else 0} for p in run["meta"]["processes"]]
    named = {p["service"] for p in run["meta"]["processes"]}
    rows += [{"process": "not started by the run", "service": s, "sent": n, "kept": kept.get(s, 0)}
             for s, n in sorted(sent.items()) if s not in named]
    return rows


def coverage(run: dict[str, Any]) -> dict[str, Any]:
    """For each case, what its trace id holds at the Collector, and what of the case went elsewhere: spans whose
    `larkspur.trace_id` attribute names the case under another trace id, and the traces they belong to."""
    tap = run["tap"]
    traces = by_trace(tap)
    named: set[str] = set()
    rows = []
    for case in run["cases"]:
        own = traces.get(case["trace_id"], [])
        ids = {d["span_id"] for d in own}
        roots = [d for d in own if d["parent_span_id"] not in ids]
        other = sorted({d["trace_id"] for d in tap if d["trace_id"] != case["trace_id"]
                        and d["attributes"].get("larkspur.trace_id") == case["trace_id"]})
        named |= {case["trace_id"], *other}
        rows.append({"case": case["case"], "trace_id": case["trace_id"], "spans": len(own), "roots": len(roots),
                     "root_names": dict(sorted(Counter(f"{d['service']}: {d['name']}" for d in roots).items())),
                     "other_traces": len(other), "spans_in_other_traces": sum(len(traces[t]) for t in other)})
    unnamed = {t: v for t, v in traces.items() if t not in named}
    return {"rows": rows, "traces_at_the_collector": len(traces), "spans_at_the_collector": len(tap),
            "unnamed_traces": len(unnamed), "unnamed_spans": sum(len(v) for v in unnamed.values()),
            "unnamed_by_name": dict(sorted(Counter(f"{d['service']}: {d['name'].split(' ')[0]} "
                                                   f"{d['name'].split(' ')[1] if ' ' in d['name'] else ''}".strip()
                                                   for v in unnamed.values() for d in v
                                                   if d["parent_span_id"] not in {x["span_id"] for x in v}).items()))}


def at_ten_percent(run: dict[str, Any], cover: dict[str, Any]) -> dict[str, Any]:
    """What config.yaml's 10 percent would keep of a run made at 100 percent, trace by trace (policies.py, which
    step 3 showed decides as the Collector does)."""
    cfg = policies.settings(percent=CONFIG_SHARE)
    budgets = policies.budgets()
    traces = by_trace(run["tap"])
    kept = {t: policies.decide(t, policies.features([as_span(d) for d in v]), per_run=budgets, threshold_ms=cfg["threshold_ms"],
                               salt=cfg["salt"], percent=cfg["percent"]) for t, v in traces.items()}
    tap = run["tap"]
    rows = []
    for row in cover["rows"]:
        other = sorted({d["trace_id"] for d in tap if d["trace_id"] != row["trace_id"]
                        and d["attributes"].get("larkspur.trace_id") == row["trace_id"]})
        mine = [row["trace_id"], *other] if row["spans"] else other
        rows.append({"case": row["case"], "own_kept": bool(kept.get(row["trace_id"], {}).get("kept")),
                     "policy": kept.get(row["trace_id"], {}).get("policy"),
                     "traces": len(mine), "traces_kept": sum(1 for t in mine if kept[t]["kept"])})
    with_spans = [r for r in rows if r["traces"]]
    return {"traces": len(traces), "kept": sum(1 for d in kept.values() if d["kept"]),
            "by_policy": dict(sorted(Counter(d["policy"] for d in kept.values() if d["kept"]).items())),
            "spans_kept": sum(len(traces[t]) for t, d in kept.items() if d["kept"]), "spans": len(tap),
            "cases": len(rows), "cases_with_spans": len(with_spans),
            "cases_whole": sum(1 for r in with_spans if r["traces_kept"] == r["traces"]),
            "cases_partly": sum(1 for r in with_spans if 0 < r["traces_kept"] < r["traces"]),
            "cases_none": sum(1 for r in with_spans if r["traces_kept"] == 0), "rows": rows}


def sampler(run: dict[str, Any]) -> dict[str, Any]:
    """W5: the night's trace through the sampler as it ran: what arrived and when, when the first span left, which
    spans the decision could have seen, what was kept, by which policy, and how long each span was held."""
    trace = run["cases"][0]["trace_id"]
    tap = [d for d in run["tap"] if d["trace_id"] == trace]
    sink = {d["span_id"]: d for d in run["sink"] if d["trace_id"] == trace}
    kept = [s for s in run["file"] if s["trace_id"] == trace]
    ids = {d["span_id"] for d in tap}
    [root] = [d for d in tap if d["parent_span_id"] not in ids]
    first_out = min(d["received_at"] for d in sink.values()) if sink else None
    judged = [d for d in tap if first_out is not None and d["received_at"] < first_out]
    cfg = policies.settings(percent=run["meta"]["share_percent"])
    budgets = policies.budgets()

    def decided(spans: list[Mapping[str, Any]]) -> dict[str, Any]:
        return policies.decide(trace, policies.features([as_span(d) for d in spans]), per_run=budgets,
                               threshold_ms=cfg["threshold_ms"], salt=cfg["salt"], percent=cfg["percent"])

    held = [sink[d["span_id"]]["received_at"] - d["received_at"] for d in tap if d["span_id"] in sink]
    late = [line for line in run["prom"] if line.startswith("otelcol_processor_tail_sampling_sampling_late_span_age_count")]
    return {
        "trace_id": trace, "decision_wait_s": run["meta"]["decision_wait_s"],
        "decision_wait_after_root_received": run["meta"].get("decision_wait_after_root_received"),
        "share_percent": run["meta"]["share_percent"], "night_seconds": round((root["end_ns"] - root["start_ns"]) / 1e9, 1),
        "spans_sent": len(tap), "spans_kept": len(kept), "spans_at_the_sink": len(sink),
        "policy": sorted({d.get("policy") for d in sink.values()} - {None}),
        "share": sorted({policies.share_from_tracestate(d.get("trace_state")) for d in sink.values()} - {None}),
        "first_arrival_to_first_departure_s": None if first_out is None else round(first_out - min(d["received_at"] for d in tap), 1),
        "root_arrival_after_first_s": round(root["received_at"] - min(d["received_at"] for d in tap), 1),
        "root_arrival_to_departure_s": round(sink[root["span_id"]]["received_at"] - root["received_at"], 1)
        if root["span_id"] in sink else None,
        "first_departure_after_root_arrival_s": None if first_out is None else round(first_out - root["received_at"], 1),
        "spans_before_the_first_departure": len(judged), "root_among_them": root in judged,
        "decision_on_those": decided(judged) if judged else None, "decision_on_all": decided(tap),
        "held_s": _spread(held, 1), "late_span_count_metric": [line.rsplit(" ", 1)[1] for line in late],
    }


def figure(out: Path, run: dict[str, Any]) -> dict[str, Any]:
    """fig-16-01: the first W2 case, in golden order, with two model calls and one read that passed, from its real
    trace: the span tree with timings, and every store its trace id joins (join.py's output)."""
    case = next(c for c in run["cases"] if c["model_calls"] == 2 and c["tool_calls"] == 1 and c["passed"])
    trace = case["trace_id"]
    folder = out / "w2"
    spans = sorted((s for s in run["file"] if s["trace_id"] == trace), key=lambda s: (s["start_ns"], s["end_ns"]))
    start = min(s["start_ns"] for s in spans)
    flat = [{"span_id": s["span_id"], "parent_span_id": s["parent_span_id"], "name": s["name"],
             "service": s["resource"].get("service.name"), "kind": s["kind"], "status": s["status"],
             "start_ms": round((s["start_ns"] - start) / 1e6, 3), "duration_ms": round((s["end_ns"] - s["start_ns"]) / 1e6, 3),
             "attributes": {k: s["attributes"][k] for k in FIGURE_ATTRIBUTES if k in s["attributes"]}} for s in spans]
    ids = {s["span_id"] for s in flat}

    def children(parent: str | None) -> list[dict[str, Any]]:
        return [{**s, "children": children(s["span_id"])} for s in flat
                if (s["parent_span_id"] if s["parent_span_id"] in ids else None) == parent]

    stores = join.local_stores(folder)
    joined = join.join(trace, stores)
    answers = json.loads((traced_folder("w2") / f"answers-{run['meta']['model']}.json").read_text(encoding="utf-8"))
    result = next(r for r in answers["results"] if r["id"] == case["case"])
    question = next(q["question"] for q in _golden_w2() if q["id"] == case["case"])
    calls = [r for r in joined["gateway cost lines"] if r.get("event") == "call"]
    ten = policies.settings(percent=CONFIG_SHARE)
    at_ten = policies.decide(trace, policies.features(spans), per_run=policies.budgets(), threshold_ms=ten["threshold_ms"],
                             salt=ten["salt"], percent=ten["percent"])
    return {
        "figure": "fig-16-01",
        "source": "W2's golden set on gpt-oss-20b through chapter 5's gateway and chapter 16's pinned Collector, "
                  "step 3b: the first case in the set's order with two model calls and one read that passed, "
                  "chapter 3's median run (ch03:58). It replaces step 3's stand-in, a run of chapter 5's skeleton "
                  "with its rule model.",
        "trace_id": trace, "workflow": "w2-ops-assistant", "case": case["case"], "question": question,
        "answer": result["answer"], "model": run["meta"]["model"], "model_calls": case["model_calls"],
        "tool_calls": case["tool_calls"], "duration_ms": round((max(s["end_ns"] for s in spans) - start) / 1e6, 3),
        "kept_by": sorted({s["scope_attributes"].get("tailsampling.policy") for s in spans} - {None}),
        "share_recorded": sorted({policies.share_from_tracestate(s["trace_state"]) for s in spans} - {None}),
        "at_config_share": {"percent": CONFIG_SHARE, "kept": at_ten["kept"], "policy": at_ten["policy"]},
        "spans": flat, "tree": children(None),
        "stores": [
            {"store": "harness log", "key": "trace_id on every line", "records": len(joined["harness log"]),
             "events": [line["event"] for line in joined["harness log"]]},
            {"store": "tool servers' logs", "key": "trace_id from the call's _meta", "records": len(joined["tool server log"]),
             "identity": sorted({line.get("identity") for line in joined["tool server log"]})},
            {"store": "gateway cost lines", "key": "trace_id from the request's metadata",
             "records": len(joined["gateway cost lines"]),
             "input_tokens": sum(line.get("prompt_tokens") or 0 for line in calls),
             "output_tokens": sum(line.get("completion_tokens") or 0 for line in calls),
             "latency_ms": [line.get("latency_ms") for line in calls]},
            {"store": "span file (the Collector)", "key": "the trace id itself", "records": len(joined["spans"])},
            {"store": "CloudWatch (step 7)", "key": "the trace id itself", "records": None},
            {"store": "Langfuse (step 7)", "key": "the trace id itself", "records": None},
            {"store": "model invocation log (step 7)", "key": "requestMetadata.trace_id", "records": None},
            {"store": "CloudTrail (step 7)", "key": "the role session name, <object id>.<first 16 hex>", "records": None},
        ],
        "join": join.render(trace, joined).splitlines(),
    }


def _golden_w2() -> list[dict[str, Any]]:
    import yaml
    return yaml.safe_load((COMPANION / "workflows" / "w2-ops-assistant" / "eval" / "golden-questions.yaml").read_text(encoding="utf-8"))


def summarize(out: Path) -> dict[str, Any]:
    runs = {name: load(out / name) for name in RUNS if (out / name).is_dir()}
    data: dict[str, Any] = {"runs": {}, "processes": {}, "coverage": {}, "at_ten_percent": {}, "sampler": {}}
    for name, run in runs.items():
        data["runs"][name] = run_row(run)
        data["processes"][name] = processes(run)
        data["coverage"][name] = coverage(run)
        if run["meta"]["share_percent"] == 100.0:
            data["at_ten_percent"][name] = at_ten_percent(run, data["coverage"][name])
        else:
            data["sampler"][name] = sampler(run)
    write_json(out / "workflows.json", data)
    fig = figure(out, runs["w2"])
    write_json(out / FIGURE, fig)
    (out / "summary.md").write_text(render(data, fig), encoding="utf-8", newline="\n")
    return data


# --- the summary ------------------------------------------------------------------------------------------------

def _label(name: str, row: Mapping[str, Any]) -> str:
    if row["workflow"] == "w5":
        return f"W5, {'decision_wait 30 s' if name == 'w5-step3' else 'root trigger'}"
    return f"{NAMES[row['workflow']]}, {row['model']}"


def _count(n: Any) -> str:
    return f"{n:,}" if isinstance(n, int) else str(n)


def _spread_text(s: Mapping[str, float] | None) -> str:
    return "none" if not s else f"{s['min']:g} / {s['median']:g} / {s['max']:g}"


def render(data: Mapping[str, Any], fig: Mapping[str, Any]) -> str:
    runs = data["runs"]
    out = ["# Chapter 16, step 3b: the workflows on the local models through the Collector", "",
           "Every table below is computed by `collector/analyze_workflows.py --summarize` from the files in this folder "
           "and the runs' results in each workflow's `eval/traced/2026-11-03/`. The runs are "
           "`collector/run_workflows.py`: each workflow's own harness, servers and gateway on a local model, every "
           "process sending OTLP to the pinned Collector running `collector/config.yaml` with CloudWatch and Langfuse "
           "off.", ""]
    out += ["## The runs", "",
            "|Run |Ollama |Cases |Passed |Model calls |Input tokens |Output tokens |Model time (s) |Run (s) "
            "|Share of the rest |decision_wait |Root trigger |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, r in runs.items():
        out.append(f"|{_label(name, r)} |{r['ollama']} |{r['cases']} |{r['passed']} |{r['calls']} |{_count(r['input_tokens'])} "
                   f"|{_count(r['output_tokens'])} |{r['model_seconds']:g} |{r['run_seconds']:g} |{r['share_percent']:g}% "
                   f"|{r['decision_wait_s']:g} s |{r['decision_wait_after_root_received'] or 'off'} |")
    total = {k: sum(r[k] for r in runs.values()) for k in ("calls", "input_tokens", "output_tokens", "model_seconds", "run_seconds")}
    out.append(f"|all | | | |{total['calls']} |{_count(total['input_tokens'])} |{_count(total['output_tokens'])} "
               f"|{total['model_seconds']:.1f} |{total['run_seconds']:.1f} | | | |")
    out += ["", "Model time is the gateway's latency summed over its calls, the time the GPU spent on them. A run's time "
            "is its cases' own, as each workflow's record keeps them, summed.", ""]
    out += ["## Which processes sent spans", "",
            "|Run |Process |service.name |Spans sent |Kept in the span file |", "|---|---|---|---|---|"]
    for name, rows in data["processes"].items():
        for p in rows:
            out.append(f"|{_label(name, runs[name])} |{p['process']} |{p['service'] or 'none'} |{p['sent']} |{p['kept']} |")
    out += ["", "## What a run's trace id holds", "",
            "For each case, the spans whose trace id is the case's, the roots among them (spans whose parent isn't in "
            "the trace), and the case's spans that went elsewhere: spans under another trace id whose "
            "`larkspur.trace_id` attribute names the case, with the traces they belong to. The last two columns count "
            "the traces at the Collector that name no case at all.", "",
            "|Run |Cases |With spans under their trace id |Roots per trace (min / median / max) |Cases that are one tree "
            "|Cases with spans elsewhere |Traces elsewhere |Spans elsewhere |Traces naming no case |Their spans |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    for name, c in data["coverage"].items():
        rows = c["rows"]
        with_spans = [r for r in rows if r["spans"]]
        roots = _spread([r["roots"] for r in with_spans], 0)
        out.append(f"|{_label(name, runs[name])} |{len(rows)} |{len(with_spans)} |{_spread_text(roots)} "
                   f"|{sum(1 for r in with_spans if r['roots'] == 1 and not r['other_traces'])} "
                   f"|{sum(1 for r in rows if r['other_traces'])} |{sum(r['other_traces'] for r in rows)} "
                   f"|{sum(r['spans_in_other_traces'] for r in rows)} |{c['unnamed_traces']} |{c['unnamed_spans']} |")
    out += ["", "|Run |The roots of the cases' traces |", "|---|---|"]
    for name, c in data["coverage"].items():
        roots: Counter = Counter()
        for r in c["rows"]:
            roots.update(r["root_names"])
        out.append(f"|{_label(name, runs[name])} |" + "; ".join(f"{k} ({v})" for k, v in sorted(roots.items())) + " |")
    out += ["", "## At config.yaml's 10 percent", "",
            "W2, W3 and W4 ran with the share of the rest at 100 percent, so every trace was kept. What 10 percent "
            "would keep, computed trace by trace with `collector/policies.py`:", "",
            "|Run |Traces |Kept at 10% |By policy |Spans kept |Cases with spans |Kept whole |Kept in part |Kept not at all |",
            "|---|---|---|---|---|---|---|---|---|"]
    for name, t in data["at_ten_percent"].items():
        out.append(f"|{_label(name, runs[name])} |{t['traces']} |{t['kept']} |"
                   + ", ".join(f"{k} {v}" for k, v in t["by_policy"].items()) + f" |{t['spans_kept']} of {t['spans']} "
                   f"|{t['cases_with_spans']} |{t['cases_whole']} |{t['cases_partly']} |{t['cases_none']} |")
    out += ["", "## W5's night under the two settings", "",
            "One night each, the same fixture night on gpt-oss-20b, at config.yaml's 10 percent. Times are seconds at "
            "the Collector: when a span reached the tap, before any processor, and when it reached the sink, beside "
            "the span file, after the sampler.", "",
            "|Setting |Night (s) |Spans sent |Kept |Policy recorded |Share recorded |First span in to first out "
            "|Root in, after the first span |Root in to root out |Spans in before the first left |Their decision "
            "|The whole trace's decision |Held per span (min / median / max) |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, s in data["sampler"].items():
        setting = (f"decision_wait {s['decision_wait_s']:g} s" if not s["decision_wait_after_root_received"]
                   else f"decision_wait {s['decision_wait_s']:g} s, root trigger {s['decision_wait_after_root_received']}")
        theirs = s["decision_on_those"]
        out.append(f"|{setting} |{s['night_seconds']:g} |{s['spans_sent']} |{s['spans_kept']} |{', '.join(s['policy']) or 'none'} "
                   f"|{', '.join(f'{x:g}' for x in s['share']) or 'none'} |{s['first_arrival_to_first_departure_s']} "
                   f"|{s['root_arrival_after_first_s']} |{s['root_arrival_to_departure_s']} "
                   f"|{s['spans_before_the_first_departure']}{' (root among them)' if s['root_among_them'] else ''} "
                   f"|{'kept by ' + theirs['policy'] if theirs and theirs['kept'] else 'dropped' if theirs else 'none'} "
                   f"|{'kept by ' + s['decision_on_all']['policy'] if s['decision_on_all']['kept'] else 'dropped'} "
                   f"|{_spread_text(s['held_s'])} |")
    out += ["", "## fig-16-01", "",
            f"W2's {fig['case']}, \"{fig['question']}\", on {fig['model']}: {fig['model_calls']} model calls and "
            f"{fig['tool_calls']} read, {fig['duration_ms'] / 1000:.2f} s, trace `{fig['trace_id']}`. `join.py "
            f"{fig['trace_id']} --stores results/2026-11-03/workflows/w2` prints:", "", "```", *fig["join"], "```"]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("raw", nargs="*", type=Path, help="raw run folders, collector/_lab/<stamp>-<run>")
    parser.add_argument("--out", type=Path, help="the results folder, results/<date>/workflows")
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
