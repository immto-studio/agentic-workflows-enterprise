"""The local run's results: what reached each store, the content drop, the sampling, the delay, the headers.

Chapter 16, step 3 (companion #14, O-D3, O-D4, O-D18). run_local.py leaves its raw records in a git-ignored
folder. This module works in two steps, so the summary can always be checked against what is committed:

- `extract` copies what the results keep, per phase: the four stores join.py reads (the harness log, the tool
  server's log and the gateway's cost lines, each cut to the phase's runs, with the lock file's path made
  relative to the repository, and the Collector's span file as it wrote it); what the two fakes recorded
  (arrival times, headers and spans, with no raw body except one CloudWatch request kept whole for the SigV4
  test, signed with the dummy key); what the tap saw, as counts and the facts the policies read, never an
  attribute's value; the runner's record of each run; and the Collector's tail-sampling counters. A failed
  run's spans carry the exception's stack trace, and `scrub` replaces this machine's folders in it with
  `<companion>`, `<site-packages>`, `<python>` or `<path>`, keeping the file names.
- `summarize` computes every table from those files alone and writes summary.md and collector.json. Two runs of
  it write the same bytes. The trace for fig-16-01 that stood in here until step 3b is gone: step 3b's
  collector/analyze_workflows.py writes fig-16-01 from W2's real run.

Run (from labs/ch16):
    python collector/analyze.py collector/_lab/<stamp> --out results/2026-11-03/collector
    python collector/analyze.py --summarize results/2026-11-03/collector
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
import statistics
import sys
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import fake_otlp  # noqa: E402
import otelcol  # noqa: E402
import policies  # noqa: E402

PHASES = ("every-run", "sampled")
STORES = ("harness", "server", "gateway")
SPECIALS = ("refused", "slow", "over-budget", "fallback", "failed")
CALL_EVENTS = ("call", "failed")  # the gateway's lines for a call it sent, each with a span


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    Path(path).write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8", newline="\n")


def write_json(path: Path, data: Any) -> None:
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


# --- extract ------------------------------------------------------------------------------------------------

def _relative(line: dict[str, Any]) -> dict[str, Any]:
    """A harness line with the lock file's path relative to the repository, so no path of this machine stays."""
    lock = line.get("lock")
    if isinstance(lock, str):
        try:
            line = {**line, "lock": Path(lock).resolve().relative_to(policies.COMPANION).as_posix()}
        except ValueError:
            line = {**line, "lock": Path(lock).name}
    return line


# The paths of this machine that an exception's stack trace puts on a span, as they sit in JSON text (each
# backslash doubled), and what replaces them: the repository, the installed packages, the standard library,
# and, last, any other folder.
_PATHS = [
    (re.compile(r"[A-Za-z]:(?:\\\\[^\\\"]+)*?\\\\Lib\\\\site-packages(?=\\\\)"), "<site-packages>"),
    (re.compile(r"[A-Za-z]:(?:\\\\[^\\\"]+)*?\\\\Lib(?=\\\\)"), "<python>"),
    (re.compile(r"[A-Za-z]:(?:\\\\[^\\\"]+)+(?=\\\\)"), "<path>"),
]


def scrub(text: str) -> str:
    """JSON text with no absolute path of this machine left in it (stack traces keep their file names)."""
    text = text.replace(json.dumps(str(policies.COMPANION))[1:-1], "<companion>")
    for pattern, marker in _PATHS:
        text = pattern.sub(marker, text)
    return text


def tap_summary(records: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per trace, what reached the Collector: span count, first arrival, services, content keys, policy facts."""
    spans: dict[str, list[Mapping[str, Any]]] = {}
    first: dict[str, float] = {}
    for record in records:
        for span in record["spans"]:
            spans.setdefault(span["trace_id"], []).append(span)
            first[span["trace_id"]] = min(first.get(span["trace_id"], record["received_at"]), record["received_at"])
    out = {}
    for trace_id, found in spans.items():
        keys = Counter(k for s in found for k in s["attributes"] if policies.is_content(k))
        keys += Counter(k for s in found for e in s["events"] for k in e["attributes"] if policies.is_content(k))
        out[trace_id] = {"spans": len(found), "first_received": first[trace_id],
                         "services": dict(sorted(Counter(s["resource"].get("service.name") for s in found).items())),
                         "content": dict(sorted(keys.items())), "features": policies.features(found)}
    return dict(sorted(out.items()))


def extract(raw: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "cloudwatch-request.json").unlink(missing_ok=True)
    logs = {name: read_jsonl(raw / f"{name}.jsonl") for name in STORES}
    logs["harness"] = [_relative(line) for line in logs["harness"]]
    for phase in PHASES:
        src, dst = raw / phase, out / phase
        dst.mkdir(exist_ok=True)
        runs = read_jsonl(src / "runs.jsonl")
        ids = {run["trace_id"] for run in runs}
        write_jsonl(dst / "runs.jsonl", runs)
        for name in STORES:
            write_jsonl(dst / f"{name}.jsonl", [line for line in logs[name] if line.get("trace_id") in ids])
        (dst / "spans.jsonl").write_text(scrub((src / "spans.jsonl").read_text(encoding="utf-8")), encoding="utf-8",
                                         newline="\n")
        tapped = tap_summary(fake_otlp.iter_records(src / "tap.jsonl"))
        write_json(dst / "tap.json", {"run_traces": {t: v for t, v in tapped.items() if t in ids},
                                      "other_traces": sorted(t for t in tapped if t not in ids)})
        langfuse = "".join(json.dumps(r) + "\n" for r in fake_otlp.iter_records(src / "langfuse.jsonl"))
        (dst / "langfuse.jsonl").write_text(scrub(langfuse), encoding="utf-8", newline="\n")
        cloudwatch, kept_whole = [], phase != PHASES[0]
        for record in fake_otlp.iter_records(src / "cloudwatch.jsonl"):
            record["sigv4_verified"] = fake_otlp.verify_sigv4(record, otelcol.DUMMY_SECRET_ACCESS_KEY)
            body = fake_otlp.decode_body(base64.b64decode(record["body_b64"]), record["headers"].get("Content-Encoding"))
            if not kept_whole and b":\\" not in body:  # one signed request whose body holds no path of this machine
                write_json(out / "cloudwatch-request.json", {k: v for k, v in record.items() if k != "spans"})
                kept_whole = True
            cloudwatch.append(json.dumps({k: v for k, v in record.items() if k != "body_b64"}) + "\n")
        (dst / "cloudwatch.jsonl").write_text(scrub("".join(cloudwatch)), encoding="utf-8", newline="\n")
        lines = (src / "metrics.txt").read_text(encoding="utf-8").splitlines()
        (dst / "tail-sampling.prom").write_text("".join(f"{line}\n" for line in lines
                                                        if line.startswith("otelcol_processor_tail_sampling")),
                                                encoding="utf-8", newline="\n")
        shutil.copyfile(src / "meta.json", dst / "meta.json")


# --- summarize ----------------------------------------------------------------------------------------------

def _by_trace(spans: Iterable[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    return fake_otlp.by_trace(spans)


def _first_arrival(records: Iterable[Mapping[str, Any]]) -> dict[str, float]:
    first: dict[str, float] = {}
    for record in records:
        for span in record["spans"]:
            t = span["trace_id"]
            first[t] = min(first.get(t, record["received_at"]), record["received_at"])
    return first


def _content_after(spans: Iterable[Mapping[str, Any]]) -> Counter:
    found: Counter = Counter()
    for s in spans:
        found.update(k for k in s["attributes"] if policies.is_content(k))
        found.update(k for e in s["events"] for k in e["attributes"] if policies.is_content(k))
    return found


def _metric(lines: Iterable[str], policy: str) -> int:
    """The Collector's own count of traces a policy voted to sample (count_traces_sampled, sampled="true")."""
    total = 0
    for line in lines:
        if line.startswith("otelcol_processor_tail_sampling_count_traces_sampled{") and f'policy="{policy}"' in line \
                and 'sampled="true"' in line:
            total += int(float(line.rsplit(" ", 1)[1]))
    return total


def _spread(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    return {"min": round(min(values), 2), "median": round(statistics.median(values), 2), "max": round(max(values), 2),
            "n": len(values)}


def _basic(header: str | None) -> str | None:
    if not header or not header.startswith("Basic "):
        return None
    return base64.b64decode(header[6:]).decode("utf-8")


def phase_data(folder: Path) -> dict[str, Any]:
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    runs = read_jsonl(folder / "runs.jsonl")
    tap = json.loads((folder / "tap.json").read_text(encoding="utf-8"))
    tapped = tap["run_traces"]
    logs = {name: read_jsonl(folder / f"{name}.jsonl") for name in STORES}
    file_spans = fake_otlp.spans_from_file(folder / "spans.jsonl")
    lf_records, cw_records = read_jsonl(folder / "langfuse.jsonl"), read_jsonl(folder / "cloudwatch.jsonl")
    lf_spans = [s for r in lf_records for s in r["spans"]]
    cw_spans = [s for r in cw_records for s in r["spans"]]
    stores = {"file": _by_trace(file_spans), "cloudwatch": _by_trace(cw_spans), "langfuse": _by_trace(lf_spans)}
    metrics = (folder / "tail-sampling.prom").read_text(encoding="utf-8").splitlines()

    cfg = policies.settings(percent=float(meta["share_percent"]))
    per_run = policies.budgets()
    rows = []
    for run in runs:
        t = run["trace_id"]
        facts = tapped.get(t, {}).get("features", {"spans": 0})
        expected = policies.decide(t, facts, per_run=per_run, threshold_ms=cfg["threshold_ms"], salt=cfg["salt"],
                                   percent=cfg["percent"])
        kept_spans = stores["langfuse"].get(t, [])
        recorded = sorted({s["scope_attributes"].get("tailsampling.policy") for s in kept_spans} - {None})
        shares = sorted({policies.share_from_tracestate(s["trace_state"]) for s in kept_spans} - {None})
        ids = {name: sorted(s["span_id"] for s in by.get(t, [])) for name, by in stores.items()}
        gateway_spans = [s for s in stores["file"].get(t, []) if s["resource"].get("service.name") == "gateway"]
        lines = {name: [line for line in logs[name] if line.get("trace_id") == t] for name in STORES}
        rows.append({
            "kind": run["kind"], "case": run["case"], "trace_id": t, "passed": run["passed"],
            "seconds": round(run["ended"] - run["started"], 3), "tool_calls": len(run["tool_calls"]),
            "cost_usd": run["cost_usd"], "spans_sent": facts["spans"], "expected": expected,
            "kept": {name: bool(by.get(t)) for name, by in stores.items()},
            "same_spans": len({tuple(v) for v in ids.values()}) == 1 and len(ids["file"]) == facts["spans"],
            "recorded_policy": recorded, "recorded_share": shares,
            "harness_lines": len(lines["harness"]), "server_lines": len(lines["server"]),
            "cost_lines": sum(1 for line in lines["gateway"] if line.get("event") in CALL_EVENTS),
            "gateway_spans": len(gateway_spans),
        })

    kept_ids = [r["trace_id"] for r in rows if r["expected"]["kept"]]
    tap_first = {t: v["first_received"] for t, v in tapped.items()}
    arrivals = {"langfuse": _first_arrival(lf_records), "cloudwatch": _first_arrival(cw_records)}
    last_end = {t: max(s["end_ns"] for s in spans) / 1e9 for t, spans in stores["langfuse"].items()}
    delay = {
        "collector_to_langfuse": _spread([arrivals["langfuse"][t] - tap_first[t] for t in kept_ids if t in arrivals["langfuse"]]),
        "collector_to_cloudwatch": _spread([arrivals["cloudwatch"][t] - tap_first[t] for t in kept_ids
                                            if t in arrivals["cloudwatch"]]),
        "last_span_to_langfuse": _spread([arrivals["langfuse"][t] - last_end[t] for t in kept_ids if t in arrivals["langfuse"]]),
    }
    content_before: Counter = Counter()
    sent_by_service: Counter = Counter()
    for t in (r["trace_id"] for r in rows):
        content_before.update(tapped.get(t, {}).get("content", {}))
        sent_by_service.update(tapped.get(t, {}).get("services", {}))
    services = {name: {"sent": sent_by_service[name],
                       "file": sum(1 for s in file_spans if s["resource"].get("service.name") == name),
                       "cloudwatch": sum(1 for s in cw_spans if s["resource"].get("service.name") == name),
                       "langfuse": sum(1 for s in lf_spans if s["resource"].get("service.name") == name)}
                for name in sorted(sent_by_service)}
    content = {"before": dict(content_before), "file": dict(_content_after(file_spans)),
               "cloudwatch": dict(_content_after(cw_spans)), "langfuse": dict(_content_after(lf_spans))}
    by_policy = []
    for name in cfg["order"]:
        matched = sum(1 for r in rows if (name in r["expected"]["matched"]) or (name == policies.SHARE and r["expected"]["share_keeps"]))
        by_policy.append({"policy": name, "matched": matched, "collector_count": _metric(metrics, name),
                          "recorded": sum(1 for r in rows if r["recorded_policy"] == [name]),
                          "shares": sorted({s for r in rows if r["recorded_policy"] == [name] for s in r["recorded_share"]})})
    rest = [r for r in rows if not r["expected"]["matched"]]
    hashing = {"runs": len(rest), "share_keeps": sum(1 for r in rest if r["expected"]["share_keeps"]),
               "collector_kept": sum(1 for r in rest if r["kept"]["langfuse"]),
               "same": all(r["expected"]["share_keeps"] == r["kept"]["langfuse"] for r in rest)}
    cost_spans = [s for s in lf_spans if isinstance(s["attributes"].get("larkspur.cost_usd"), (int, float))]
    langfuse_cost = {"spans": len(cost_spans),
                     "equal": sum(1 for s in cost_spans if s["attributes"].get("gen_ai.usage.cost") == s["attributes"]["larkspur.cost_usd"]),
                     "elsewhere": sum(1 for s in file_spans + cw_spans if "gen_ai.usage.cost" in s["attributes"])}
    lf_auth = {_basic(r["headers"].get("Authorization")) for r in lf_records}
    cw_auth = [fake_otlp.parse_sigv4(r["headers"].get("Authorization", "")) for r in cw_records]
    headers = {
        "langfuse": {"requests": len(lf_records), "paths": sorted({r["path"] for r in lf_records}),
                     "basic": sorted(a for a in lf_auth if a is not None), "all_basic": None not in lf_auth,
                     "ingestion_version": sorted({r["headers"].get("X-Langfuse-Ingestion-Version") for r in lf_records} - {None}),
                     "all_ingestion_version": all(r["headers"].get("X-Langfuse-Ingestion-Version") == "4" for r in lf_records),
                     "errors": sum(1 for r in lf_records if r["error"])},
        "cloudwatch": {"requests": len(cw_records), "paths": sorted({r["path"] for r in cw_records}),
                       "algorithms": sorted({a["algorithm"] for a in cw_auth}),
                       "key_ids": sorted({a["access_key_id"] for a in cw_auth}),
                       "scopes": sorted({f"{a['region']}/{a['service']}/{a['terminal']}" for a in cw_auth}),
                       "signed_headers": sorted({";".join(a["signed_headers"]) for a in cw_auth}),
                       "verified": sum(1 for r in cw_records if r.get("sigv4_verified")),
                       "amz_date": all("X-Amz-Date" in r["headers"] for r in cw_records),
                       "errors": sum(1 for r in cw_records if r["error"])},
    }
    return {"meta": meta, "rows": rows, "delay": delay, "content": content, "by_policy": by_policy, "hashing": hashing,
            "langfuse_cost": langfuse_cost, "headers": headers, "services": services,
            "other_traces": tap["other_traces"], "collector_exit": meta.get("collector_exit")}


def _pct(value: float) -> str:
    return f"{value:g}%"


def _spread_text(s: Mapping[str, float] | None) -> str:
    return "none" if not s else f"{s['min']:.2f} / {s['median']:.2f} / {s['max']:.2f}"


def _yes(value: bool) -> str:
    return "yes" if value else "no"


def render(data: Mapping[str, Any]) -> str:
    phases = data["phases"]
    out = ["# Chapter 16, step 3: the local run through the Collector", "",
           "Every table below is computed by `collector/analyze.py --summarize` from the files in this folder. "
           "The run is `collector/run_local.py`: chapter 5's skeleton with the rule model, every process sending "
           "OTLP to the pinned Collector running `collector/config.yaml`, and two fakes standing in for Langfuse "
           "and CloudWatch.", ""]
    out += ["## What reached each store", "",
            "|Phase |Share of the rest |Runs |Traces at the Collector |Kept, as the policies say |Kept in the span file "
            "|At CloudWatch's fake |At Langfuse's fake |The same runs everywhere |Spans sent |Spans of the kept runs "
            "|Kept runs with the same spans in all three |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, p in phases.items():
        rows = p["rows"]
        kept = [r for r in rows if r["expected"]["kept"]]
        same = all(r["kept"]["file"] == r["kept"]["cloudwatch"] == r["kept"]["langfuse"] == r["expected"]["kept"]
                   for r in rows)
        out.append(f"|{name} |{_pct(p['meta']['share_percent'])} |{len(rows)} |{sum(1 for r in rows if r['spans_sent'])} "
                   f"|{len(kept)} |{sum(r['kept']['file'] for r in rows)} |{sum(r['kept']['cloudwatch'] for r in rows)} "
                   f"|{sum(r['kept']['langfuse'] for r in rows)} |{_yes(same)} |{sum(r['spans_sent'] for r in rows)} "
                   f"|{sum(r['spans_sent'] for r in kept)} |{sum(r['same_spans'] for r in kept)} of {len(kept)} |")
    out += ["", "|Phase |Process |Spans it sent |In the span file |At CloudWatch's fake |At Langfuse's fake |",
            "|---|---|---|---|---|---|"]
    for name, p in phases.items():
        for service, n in p["services"].items():
            out.append(f"|{name} |{service} |{n['sent']} |{n['file']} |{n['cloudwatch']} |{n['langfuse']} |")
    out += ["", "## The same trace ids in every store", "",
            "|Phase |Runs |With harness log lines |With a tool call |Of those, in the tool server's log "
            "|With gateway cost lines |Kept runs with one gateway span per cost line |",
            "|---|---|---|---|---|---|---|"]
    for name, p in phases.items():
        rows = p["rows"]
        kept = [r for r in rows if r["expected"]["kept"]]
        tooled = [r for r in rows if r["tool_calls"]]
        out.append(f"|{name} |{len(rows)} |{sum(1 for r in rows if r['harness_lines'])} |{len(tooled)} "
                   f"|{sum(1 for r in tooled if r['server_lines'])} |{sum(1 for r in rows if r['cost_lines'])} "
                   f"|{sum(1 for r in kept if r['gateway_spans'] == r['cost_lines'])} of {len(kept)} |")
    out += ["", "## Content the manifests don't allow", "",
            "|Phase |Attribute |On spans that reached the Collector |In the span file |At CloudWatch's fake |At Langfuse's fake |",
            "|---|---|---|---|---|---|"]
    for name, p in phases.items():
        c = p["content"]
        for attr in sorted(set(c["before"]) | set(c["file"]) | set(c["cloudwatch"]) | set(c["langfuse"])):
            out.append(f"|{name} |`{attr}` |{c['before'].get(attr, 0)} |{c['file'].get(attr, 0)} "
                       f"|{c['cloudwatch'].get(attr, 0)} |{c['langfuse'].get(attr, 0)} |")
    out += ["", "## Tail sampling", "",
            "Each policy, the runs whose spans it matches (computed here from what reached the Collector), the "
            "traces the Collector itself counts as sampled by it, and the kept traces that record it.", "",
            "|Phase |Policy |Runs it matches |The Collector's count |Recorded on kept traces |Share recorded |",
            "|---|---|---|---|---|---|"]
    for name, p in phases.items():
        for b in p["by_policy"]:
            shares = ", ".join(f"{s:g}" for s in b["shares"]) or "none"
            out.append(f"|{name} |{b['policy']} |{b['matched']} |{b['collector_count']} |{b['recorded']} |{shares} |")
    out += ["", "|Phase |Run |Policies it matches |Recorded policy |Share recorded |Kept everywhere |",
            "|---|---|---|---|---|---|"]
    for name, p in phases.items():
        for r in p["rows"]:
            if r["kind"] in SPECIALS:
                out.append(f"|{name} |{r['case']} |{', '.join(r['expected']['matched']) or 'none'} "
                           f"|{', '.join(r['recorded_policy']) or 'none'} |{', '.join(f'{s:g}' for s in r['recorded_share']) or 'none'} "
                           f"|{_yes(all(r['kept'].values()))} |")
    out += ["", "|Phase |Runs no keep-all policy matches |Kept by the share, by FNV-1a here |Kept by the Collector |The same runs |",
            "|---|---|---|---|---|"]
    for name, p in phases.items():
        h = p["hashing"]
        out.append(f"|{name} |{h['runs']} |{h['share_keeps']} |{h['collector_kept']} |{_yes(h['same'])} |")
    out += ["", "## The delay", "",
            "Seconds, minimum / median / maximum over the kept traces: from the tap's first receipt of a trace "
            "(the Collector's receipt, before any processor) to its first arrival at each fake, and from the end "
            "of the trace's last span to its arrival at Langfuse's fake.", "",
            "|Phase |Kept traces |decision_wait |Receipt to Langfuse's fake |Receipt to CloudWatch's fake |Last span's end to Langfuse's fake |",
            "|---|---|---|---|---|---|"]
    for name, p in phases.items():
        d = p["delay"]
        out.append(f"|{name} |{d['collector_to_langfuse']['n'] if d['collector_to_langfuse'] else 0} "
                   f"|{p['meta']['decision_wait_s']:g} s |{_spread_text(d['collector_to_langfuse'])} "
                   f"|{_spread_text(d['collector_to_cloudwatch'])} |{_spread_text(d['last_span_to_langfuse'])} |")
    out += ["", "## Headers", "",
            "|Phase |Fake |Requests |Path |Authorization |Other headers |Refused by the fake |",
            "|---|---|---|---|---|---|---|"]
    for name, p in phases.items():
        lf, cw = p["headers"]["langfuse"], p["headers"]["cloudwatch"]
        basic = "Basic, " + (f"decoding to `{lf['basic'][0]}` on every request" if lf["all_basic"] and len(lf["basic"]) == 1
                             else f"{len(lf['basic'])} values")
        out.append(f"|{name} |Langfuse |{lf['requests']} |`{', '.join(lf['paths'])}` |{basic} "
                   f"|`x-langfuse-ingestion-version: {', '.join(lf['ingestion_version'])}` on "
                   f"{'every request' if lf['all_ingestion_version'] else 'some requests'} |{lf['errors']} |")
        sigv4 = (f"`{', '.join(cw['algorithms'])}`, key `{', '.join(cw['key_ids'])}`, scope `{', '.join(cw['scopes'])}`, "
                 f"signature recomputed from the dummy secret on {cw['verified']} of {cw['requests']}")
        out.append(f"|{name} |CloudWatch |{cw['requests']} |`{', '.join(cw['paths'])}` |{sigv4} "
                   f"|`X-Amz-Date` on {'every request' if cw['amz_date'] else 'some requests'}; signed: "
                   f"`{', '.join(cw['signed_headers'])}` |{cw['errors']} |")
    out += ["", "## Langfuse's cost", "",
            "|Phase |Gateway spans with `larkspur.cost_usd` at Langfuse's fake |With `gen_ai.usage.cost` equal to it "
            "|Spans with `gen_ai.usage.cost` in the span file or at CloudWatch's fake |",
            "|---|---|---|---|"]
    for name, p in phases.items():
        c = p["langfuse_cost"]
        out.append(f"|{name} |{c['spans']} |{c['equal']} |{c['elsewhere']} |")
    return "\n".join(out) + "\n"


def summarize(out: Path) -> dict[str, Any]:
    data = {"phases": {name: phase_data(out / name) for name in PHASES}}
    write_json(out / "collector.json", data)
    (out / "summary.md").write_text(render(data), encoding="utf-8", newline="\n")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("raw", nargs="?", type=Path, help="a run's raw folder, collector/_lab/<stamp>")
    parser.add_argument("--out", type=Path, help="the results folder, results/<date>/collector")
    parser.add_argument("--summarize", type=Path, help="write the summary again from a results folder")
    args = parser.parse_args(argv)
    if args.summarize:
        summarize(args.summarize)
        print(f"summary written in {args.summarize}")
        return 0
    if not (args.raw and args.out):
        parser.error("give a raw folder and --out, or --summarize")
    extract(args.raw, args.out)
    summarize(args.out)
    print(f"results written in {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
