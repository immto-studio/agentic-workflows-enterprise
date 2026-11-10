"""Step 6's results: the SLIs on the kept runs, and the simulated month with its alerts, its policy, its probe, and
the data for fig-16-03, written to results/<date>/slo/.

Chapter 16, step 6 (companion #14, O-D12, O-D13). No model, no gateway process, no network: the kept runs are on
disk, and the month is built from them by a seeded generator. Two runs write the same bytes.

- kept.json: MEASURED. The three SLIs of each workflow on every kept run, per kept run and pooled.
- month.json, alerts.json, policy.json, policy-actions.jsonl, probe.json, probe-costlines.jsonl, fig-16-03.json:
  SIMULATED, and each says so in its first field ("simulated": true) or, for the JSON Lines, on every line.
- summary.md: every table the README's step 6 section prints, written from those files (`--summarize`).

Run (from labs/ch16):  python slo/run_slo.py --out results/<date>/slo
                       python slo/run_slo.py --summarize results/<date>/slo
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
LAB = HERE.parent
for folder in (LAB / "capacity", LAB / "budget", LAB / "ledger", HERE):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import budget_policy  # noqa: E402
import burn  # noqa: E402
import costlines  # noqa: E402
import offline  # noqa: E402
import price  # noqa: E402
import probe  # noqa: E402
import simulate  # noqa: E402
import slis  # noqa: E402
from summary import num, table  # noqa: E402  step 5's table helpers

DASHBOARD = HERE / "dashboard.yaml"
ALERTS = HERE / "alerts.yaml"
FILES = ("alerts.json", "fig-16-03.json", "kept.json", "month.json", "policy-actions.jsonl", "policy.json",
         "probe-costlines.jsonl", "probe.json", "summary.md")
HOUR = 3600.0
ORDER_ENDS = slis.ENDS


def dump(path: Path, obj: Any, indent: int | None = 1) -> None:
    path.write_text(json.dumps(obj, indent=indent, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8", newline="\n")


def pct(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(100 * value, digits)


# --- measured: the kept runs ------------------------------------------------------------------------------

def kept_results(slos: dict[str, Any], kept: dict[str, list[slis.RunEvent]]) -> dict[str, Any]:
    table_ = slis.measured_table(kept, slos)
    w2_budget = [e.run_id for e in slis.pooled(kept, "w2") if e.end == "budget_stop"]
    return {"measured": True, "simulated": False, "what": "the SLIs on the kept runs, every model, as kept",
            "targets": {w: {s: v.get("target") for s, v in slos["workflows"][w]["slis"].items()} for w in slis.WORKFLOWS},
            "thresholds_s": {w: slis.threshold(slos, w) for w in slis.WORKFLOWS},
            "rows": table_["rows"], "pooled": table_["pooled"],
            "w2_budget_stops": w2_budget,
            "incidents": [e.run_id for events in kept.values() for e in slis.incidents(events)]}


# --- simulated: the month ---------------------------------------------------------------------------------

def month_results(month: simulate.Month, slos: dict[str, Any], budgets: dict[str, dict[str, float]]) -> dict[str, Any]:
    config = month.config
    end = config["days"] * simulate.DAY
    rows = {}
    for workflow in slis.WORKFLOWS:
        # an event counts at the time it becomes known (slis.placed): the runs that ended in the month, and the
        # decisions made in it, as the budgets and the alert windows count them
        mine = month.real(workflow)
        runs = [e for e in mine if e.unit == "run" and slis.in_window(e, "success", 0.0, end)]
        decided = [e for e in mine if e.decision is not None and slis.in_window(e, "outcome", 0.0, end)]
        measured = slis.measured(mine, slos, workflow, 0.0, end)
        bad_by = Counter(e.injected or "baseline" for e in runs if e.end in slis.BAD)
        bad_by.update(e.injected or "baseline" for e in decided if e.decision in ("rejected", "reverted"))
        rows[workflow] = {
            "runs": len(runs), "ends": {k: v for k, v in sorted(Counter(e.end for e in runs).items(),
                                                                key=lambda kv: ORDER_ENDS.index(kv[0]))},
            "decisions": dict(sorted(Counter(e.decision for e in decided).items())),
            "slis": {s: None if r is None else {"good": r.good, "valid": r.valid, "value": round(r.value, 6)}
                     for s, r in measured.items()},
            "expected": {s: round(v, 3) for s, v in month.expected[workflow].items()},
            "budgets": {s: round(v, 3) for s, v in budgets[workflow].items()},
            "changed_by": dict(sorted(Counter(e.injected for e in runs if e.injected).items())),
            "bad_by": dict(sorted(bad_by.items()))}
    events = []
    for item in config["injected"]:
        begin, end = month.shapes["windows"][item["id"]]
        events.append({"id": item["id"], "what": item["what"], "start_s": begin, "end_s": end,
                       "start": simulate.clock(config, begin), "end": simulate.clock(config, end),
                       "runs_changed": {w: rows[w]["changed_by"].get(item["id"], 0) for w in slis.WORKFLOWS
                                        if rows[w]["changed_by"].get(item["id"])},
                       "bad_events": {w: rows[w]["bad_by"].get(item["id"], 0) for w in slis.WORKFLOWS
                                      if rows[w]["bad_by"].get(item["id"])},
                       "gateway_records": dict(sorted(Counter(
                           f"{r['workflow']}{' probe' if r['probe'] else ''} {r['kind']}" for r in month.records
                           if r["injected"] == item["id"]).items()))})
    probes = Counter((p.workflow, p.end) for p in month.probes if p.at >= 0)
    return {"simulated": True, "seed": config["seed"], "start": config["start"], "days": config["days"],
            "w5_nights": w5_nights(month),
            "lead_in_days": config["lead_in_days"], "built_from": {
                "volumes": config["volumes"]["source"], "runs": config["pools"]["rule"],
                "pools": config["pools"]["baseline"], "decisions": config["decisions"]["basis"]},
            "shapes": month.shapes, "workflows": rows, "injected": events,
            "probes": {w: dict(sorted((end, n) for (wf, end), n in probes.items() if wf == w))
                       for w in sorted({p.workflow for p in month.probes})},
            "incidents": [e.run_id for e in slis.incidents(month.events)]}


def w5_nights(month: simulate.Month) -> dict[str, Any]:
    """W5's scheduled nights in the month, before the regression and after: their output tokens and time, from the
    kept nights each was drawn from. No SLI reads either; the cost lines are where a regression like this shows."""
    tokens = {f"{r.kept_run} {r.case}": r.tokens() for r in costlines.collect(("w5",))}
    begin = month.shapes["windows"]["model-regression"][0]
    out = {}
    for name, inside in (("before", False), ("after", True)):
        nights = [e for e in month.real("w5") if e.unit == "run" and e.reason == "schedule" and (e.at or -1) >= 0
                  and (e.at >= begin) == inside]
        outputs = [tokens[e.source][1] for e in nights]
        out[name] = {"nights": len(nights), "output_tokens_mean": round(sum(outputs) / len(outputs)) if outputs else None,
                     "output_tokens_range": [min(outputs), max(outputs)] if outputs else None,
                     "seconds_mean": round(sum(e.seconds for e in nights) / len(nights), 1) if nights else None}
    return out


def peaks(month: simulate.Month, alerts: dict[str, Any], slos: dict[str, Any], design: str) -> list[dict[str, Any]]:
    """For each injected event, the highest burn rate each long window reached, for each SLI of each workflow whose
    runs or probe it touched, from the event's start to an hour past its end (a regression's to the month's end). A
    rule's short window is not read here: an alert needs both windows past the rate, so a peak over the long window
    that stays under the rate pages nowhere, whatever the short window does."""
    spec = alerts["designs"][design]
    streams = {(s.scope, s.sli): s for s in burn.streams(design, spec, month.events, month.probes, slos)}
    step = alerts["burn_rate"]["evaluate_every_minutes"] * 60.0
    end_of_month = month.config["days"] * 86400.0
    out = []
    for item in month.config["injected"]:
        begin, end = month.shapes["windows"][item["id"]]
        touched = sorted({e.workflow for e in month.events + month.probes if e.injected == item["id"]})
        for workflow in touched:
            for sli in slis.SLI_NAMES:
                stream = streams.get((workflow, sli))
                if stream is None:
                    continue
                times = [begin + i * step for i in range(int((min(end + HOUR, end_of_month) - begin) // step) + 1)]
                row = {"event": item["id"], "workflow": workflow, "sli": sli}
                for rule in alerts["burn_rate"]["rules"]:
                    row[rule["name"]] = round(max(stream.burn(t, rule["long_window_hours"]) for t in times), 3)
                out.append(row)
    return out


def alert_results(found: dict[str, list[burn.Alert]], month: simulate.Month, alerts: dict[str, Any]) -> dict[str, Any]:
    names = [i["id"] for i in month.config["injected"]]
    summary = {}
    for design, items in found.items():
        summary[design] = dict(sorted(Counter(f"{a.action} {a.cause}" for a in items).items()))
    by_event = burn.by_event(found, names)
    for row in by_event.values():
        for cell in row.values():
            if cell["first"] is not None:
                cell["first"]["start"] = simulate.clock(month.config, cell["first"]["start_s"])
    return {"simulated": True, "rules": alerts["burn_rate"]["rules"],
            "proposed": next(d for d, s in alerts["designs"].items() if s.get("proposed")),
            "by_event": by_event, "counts": summary,
            "episodes": {d: [a.as_json() | {"start": simulate.clock(month.config, a.start),
                                            "end": None if a.end is None else simulate.clock(month.config, a.end)}
                             for a in items] for d, items in found.items()}}


def probe_results(month: simulate.Month, cases: dict[str, probe.ProbeCase], table_: dict[str, Any],
                  ledger_month: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    lines: list[dict[str, Any]] = []
    rows = {}
    per_month = {r["workflow"]: r for r in ledger_month["rows"]}
    hours = month.config["days"] * 24
    for workflow, case in cases.items():
        mine = [p for p in month.probes if p.workflow == workflow and p.at >= 0]
        month_lines = probe.month_cost_lines(case, mine)
        lines += month_lines
        one = costlines.CostLine("probe", None, workflow, case.gateway_workflow, "probe", case.case, 1, "gpt-oss-20b",
                                 "gpt-oss-20b", case.alias, case.alias, case.data_class, case.input_tokens,
                                 case.output_tokens, None, False, probe.SOURCE)
        usd = price.line_cost(table_, one) or Decimal(0)
        served = sum(1 for line in month_lines if line["ok"])
        tokens = served * (case.input_tokens + case.output_tokens)
        own = per_month[workflow]["tokens_per_month"] * hours / ledger_month["month_hours"]
        rows[workflow] = {"case": case.case, "kept_run": case.kept_run, "alias": case.alias,
                          "data_class": case.data_class, "input_tokens": case.input_tokens,
                          "output_tokens": case.output_tokens, "first_call_seconds": case.seconds,
                          "probes": len(mine), "served": served, "failed": len(mine) - served,
                          "tokens_in_month": tokens, "workflow_tokens_in_month": round(own),
                          "over_workflow_tokens": round(tokens / own, 4),
                          "usd_per_probe": float(round(usd, 10)), "usd_in_month": float(round(usd * served, 6)),
                          "priced_at": price.deployment(table_, case.alias)["id"]}
    return {"simulated": True, "hours": hours, "cases": rows}, lines


def fig_workflow(month: simulate.Month, found: dict[str, list[burn.Alert]], policy: dict[str, Any],
                 slos: dict[str, Any], proposed: str) -> tuple[str, dict[str, dict[str, int]]]:
    """The workflow whose month shows the most: injected events that changed its runs, kinds of alert in the proposed
    design, kinds of policy action, and SLIs with a target; the first in W1..W5 order on a tie."""
    scores = {}
    end = month.config["days"] * simulate.DAY
    for workflow in slis.WORKFLOWS:
        events = {e.injected for e in month.real(workflow) if e.injected and slis.in_window(e, "success", 0.0, end)}
        kinds = {(a.sli, a.rule) for a in found[proposed] if a.scope == workflow}
        actions = {a["action"] for a in policy["actions"] if a["workflow"] == workflow}
        targets = sum(1 for s in slis.SLI_NAMES if slos["workflows"][workflow]["slis"][s].get("target") is not None)
        scores[workflow] = {"injected_events": len(events), "alert_kinds": len(kinds), "policy_actions": len(actions),
                            "slis": targets}
    best = max(slis.WORKFLOWS, key=lambda w: (sum(scores[w].values()), -slis.WORKFLOWS.index(w)))
    return best, scores


def fig_data(month: simulate.Month, workflow: str, scores: dict[str, Any], found: dict[str, list[burn.Alert]],
             policy: dict[str, Any], slos: dict[str, Any], budgets: dict[str, dict[str, float]], proposed: str,
             dashboard: dict[str, Any]) -> dict[str, Any]:
    config = month.config
    spec = slos["workflows"][workflow]["slis"]
    design = next(s for d, s in yaml.safe_load(ALERTS.read_text(encoding="utf-8"))["designs"].items() if d == proposed)
    with_probe = design["workflows"].get(workflow) == "probe"
    mine = month.real(workflow)
    probes = [p for p in month.probes if p.workflow == workflow]
    streams = {}
    for sli in slis.SLI_NAMES:
        if spec[sli].get("target") is None:
            continue
        threshold = slis.threshold(slos, workflow) if sli == "latency" else None
        own = burn.Stream.of(workflow, sli, float(spec[sli]["target"]), mine, threshold)
        alerting = burn.Stream.of(workflow, sli, float(spec[sli]["target"]),
                                  mine + (probes if with_probe and sli == "success" else []), threshold)
        streams[sli] = (own, alerting, threshold)
    series = []
    for hour in range(config["days"] * 24):
        end = (hour + 1) * HOUR
        point: dict[str, Any] = {"hour": hour, "at": simulate.clock(config, hour * HOUR)}
        for sli, (own, alerting, _) in streams.items():
            lo = own.window(end, (end - 0.0) / HOUR)  # the month to date
            valid, bad = lo[2], lo[3]
            budget = budgets[workflow][sli]
            point[sli] = {"valid_to_date": valid, "bad_to_date": bad,
                          "value_to_date": None if not valid else round(1 - bad / valid, 5),
                          "budget_left": round(1 - bad / budget, 4) if budget else None,
                          "burn_1h": round(alerting.burn(end, 1), 3), "burn_6h": round(alerting.burn(end, 6), 3),
                          "burn_3d": round(alerting.burn(end, 72), 3)}
        runs = [e for e in mine if e.unit == "run" and hour * HOUR <= (e.at or -1) < end]
        point["runs"] = len(runs)
        point["budget_stops"] = sum(1 for e in runs if e.end == "budget_stop")
        point["bad_runs"] = sum(1 for e in runs if e.end in slis.BAD)
        hour_records = [r for r in month.records if r["workflow"] == workflow and hour * HOUR <= r["at"] < end]
        point["provider_429s"] = sum(r.get("calls", 1) for r in hour_records if r["kind"] == "provider_429")
        point["fallback_calls"] = sum(r.get("calls", 1) for r in hour_records if r["kind"] == "fallback")
        point["failed_calls"] = sum(r.get("calls", 1) for r in hour_records if r["kind"] == "failed")
        hour_probes = [p for p in probes if hour * HOUR <= p.at - (p.seconds or 0) < end]
        point["probe"] = None if not probes else ("ok" if all(p.end in slis.GOOD for p in hour_probes) else "failed")
        series.append(point)
    return {"simulated": True, "figure": "fig-16-03", "workflow": workflow,
            "name": slos["workflows"][workflow]["name"], "chosen_because": scores,
            "design": proposed, "with_probe": with_probe, "start": config["start"], "hours": config["days"] * 24,
            "targets": {s: spec[s]["target"] for s in streams},
            "thresholds_s": {s: t for s, (_, _, t) in streams.items() if t is not None},
            "budgets_events": {s: round(budgets[workflow][s], 3) for s in streams},
            "lines": {"page_1h": 14.4, "page_6h": 6, "ticket_3d": 1},
            "injected": [{"id": i["id"], "start_hour": round(month.shapes["windows"][i["id"]][0] / HOUR, 3),
                          "end_hour": round(month.shapes["windows"][i["id"]][1] / HOUR, 3)}
                         for i in config["injected"]],
            "alerts": [a.as_json() for a in found[proposed] if a.scope == workflow],
            "policy": [a for a in policy["actions"] if a["workflow"] == workflow],
            "panels": [p["id"] for p in dashboard["workflow_row"]],
            "series": series}


def write(out: Path) -> None:
    offline.block_network()
    out.mkdir(parents=True, exist_ok=True)
    slos = slis.load()
    alerts = yaml.safe_load(ALERTS.read_text(encoding="utf-8"))
    policy_spec = budget_policy.load()
    dashboard = yaml.safe_load(DASHBOARD.read_text(encoding="utf-8"))
    kept = slis.kept_events()
    dump(out / "kept.json", kept_results(slos, kept))
    month = simulate.build(alerts=alerts, kept=kept)
    budgets = budget_policy.budgets(slos, month.expected)
    dump(out / "month.json", month_results(month, slos, budgets))
    found = burn.evaluate(month, alerts, slos, budgets)
    alert_json = alert_results(found, month, alerts)
    alert_json["peaks"] = peaks(month, alerts, slos, alert_json["proposed"])
    dump(out / "alerts.json", alert_json)
    policy = budget_policy.apply(month, slos, policy_spec)
    dump(out / "policy.json", policy)
    jsonl(out / "policy-actions.jsonl", policy["actions"])
    ledger_month = json.loads(simulate.LEDGER_MONTH.read_text(encoding="utf-8"))["month"]
    probe_json, lines = probe_results(month, probe.cases(alerts), price.load(), ledger_month)
    dump(out / "probe.json", probe_json)
    jsonl(out / "probe-costlines.jsonl", lines)
    proposed = alert_json["proposed"]
    workflow, scores = fig_workflow(month, found, policy, slos, proposed)
    dump(out / "fig-16-03.json", fig_data(month, workflow, scores, found, policy, slos, budgets, proposed, dashboard),
         indent=None)
    summarize(out)


# --- the summary ------------------------------------------------------------------------------------------

def load_json(folder: Path, name: str) -> Any:
    return json.loads((folder / name).read_text(encoding="utf-8"))


def ratio_cell(r: dict[str, Any] | None) -> str:
    if r is None:
        return "none"
    if not r["valid"]:
        return "no events"
    return f"{r['good']:,} / {r['valid']:,} ({num(100 * r['value'], 4)}%)"


def ends_cell(ends: dict[str, int]) -> str:
    return ", ".join(f"{k.replace('_', ' ')} {v:,}" for k, v in ends.items())


def target_cell(t: float | None) -> str:
    return "none" if t is None else f"{num(100 * t, 4)}%"


def summarize(folder: Path) -> Path:
    kept = load_json(folder, "kept.json")
    month = load_json(folder, "month.json")
    alerts = load_json(folder, "alerts.json")
    policy = load_json(folder, "policy.json")
    probes = load_json(folder, "probe.json")
    fig = load_json(folder, "fig-16-03.json")
    slos = slis.load()
    dashboard = yaml.safe_load(DASHBOARD.read_text(encoding="utf-8"))
    out = ["# Chapter 16, step 6: SLOs, the simulated month, the alerts and the policy", "",
           "Written by `slo/run_slo.py --summarize` from the files beside it. The first section is MEASURED on the "
           "kept runs; every section after it is SIMULATED.", ""]

    out += ["## The SLIs on the kept runs (measured)", ""]
    rows = []
    for w in slis.WORKFLOWS:
        p = kept["pooled"][w]
        t = kept["targets"][w]
        rows.append([w.upper(), ends_cell(p["ends"]), ratio_cell(p["slis"]["success"]), target_cell(t["success"]),
                     f"{num(kept['thresholds_s'][w])} s", ratio_cell(p["slis"]["latency"]), target_cell(t["latency"]),
                     ratio_cell(p["slis"]["outcome"]), target_cell(t["outcome"])])
    out += table(["Workflow", "Runs by end", "Success", "Target", "Latency threshold", "Latency", "Target", "Outcome",
                  "Target"], rows) + [""]
    rows = []
    for r in kept["rows"]:
        rows.append([r["workflow"].upper(), r["kept_run"], r["runs"], ends_cell(r["ends"]),
                     ratio_cell(r["slis"]["success"]), ratio_cell(r["slis"]["latency"]),
                     ratio_cell(r["slis"]["outcome"])])
    out += table(["Workflow", "Kept run", "Runs", "Runs by end", "Success", "Latency", "Outcome"], rows) + [""]

    out += ["## The SLOs and their budgets in the simulated month", ""]
    rows = []
    for w in slis.WORKFLOWS:
        spec = slos["workflows"][w]["slis"]
        for s in slis.SLI_NAMES:
            if spec[s].get("target") is None:
                rows.append([w.upper(), s, "none", "", "", ""])
                continue
            threshold = f"{num(spec['latency']['threshold_s'])} s" if s == "latency" else ""
            rows.append([w.upper(), s, target_cell(spec[s]["target"]), threshold,
                         month["workflows"][w]["expected"][s], month["workflows"][w]["budgets"][s]])
    out += table(["Workflow", "SLI", "Target", "Threshold", "Valid events expected in the month",
                  "Error budget (events)"], rows) + [""]

    out += ["## The simulated month", ""]
    rows = []
    for w in slis.WORKFLOWS:
        r = month["workflows"][w]
        rows.append([w.upper(), r["runs"], ends_cell(r["ends"]), ratio_cell(r["slis"]["success"]),
                     ratio_cell(r["slis"]["latency"]), ratio_cell(r["slis"]["outcome"]),
                     ", ".join(f"{k} {v}" for k, v in r["bad_by"].items())])
    out += table(["Workflow", "Runs", "Runs by end", "Success", "Latency", "Outcome", "Bad events by cause"],
                 rows) + [""]
    rows = []
    for e in month["injected"]:
        rows.append([e["id"], f"{e['start']} to {e['end']}", ", ".join(f"{w.upper()} {n}" for w, n in
                                                                     e["runs_changed"].items()),
                     ", ".join(f"{w.upper()} {n}" for w, n in e["bad_events"].items()),
                     ", ".join(f"{k} {v}" for k, v in e["gateway_records"].items())])
    out += table(["Injected event", "When (ET)", "Runs it changed", "Bad events it caused", "Gateway records"],
                 rows) + [""]
    rows = [[w.upper(), ", ".join(f"{k} {v:,}" for k, v in ends.items())] for w, ends in month["probes"].items()]
    out += table(["Probe", "Probes in the month by end"], rows) + [""]
    rows = [[name, n["nights"], n["output_tokens_mean"], f"{n['output_tokens_range'][0]:,} to {n['output_tokens_range'][1]:,}",
             n["seconds_mean"]] for name, n in month["w5_nights"].items()]
    out += table(["W5's scheduled nights", "Nights", "Output tokens a night, mean", "Range", "Seconds a night, mean"],
                 rows) + [""]

    out += ["## Which alert caught each injected event (simulated)", ""]
    designs = [d for d in alerts["by_event"][next(iter(alerts["by_event"]))]]
    rows = []
    for name, row in alerts["by_event"].items():
        cells = [name]
        for d in designs:
            first = row[d]["first"]
            cells.append(row[d]["action"] if first is None else
                         f"{row[d]['action']}: {first['scope'].upper() if not first['scope'].startswith('group') else first['scope']} "
                         f"{first['sli']} {first['rule']}, {first['start']}")
        rows.append(cells)
    out += table(["Injected event"] + [f"{d}{' (proposed)' if d == alerts['proposed'] else ''}" for d in designs],
                 rows) + [""]
    rows = [[p["event"], p["workflow"].upper(), p["sli"], p["fast-burn-1h"], p["fast-burn-6h"], p["slow-burn-3d"]]
            for p in alerts["peaks"]]
    out += table(["Injected event", "Workflow", "SLI", "Highest burn over 1 hour (page at 14.4)",
                  "Over 6 hours (page at 6)", "Over 3 days (ticket at 1)"], rows) + [""]
    rows = []
    for d, counts in alerts["counts"].items():
        rows.append([d, ", ".join(f"{k} {v}" for k, v in counts.items()) or "none"])
    out += table(["Design", "Alerts by action and cause"], rows) + [""]
    rows = []
    for d, items in alerts["episodes"].items():
        for scope in sorted({a["scope"] for a in items}):
            mine = [a for a in items if a["scope"] == scope]
            pages = Counter(a["cause"] for a in mine if a["action"] == "page")
            tickets = Counter(a["cause"] for a in mine if a["action"] == "ticket")
            rows.append([d, scope.upper() if not scope.startswith(("group", "platform")) else scope,
                         ", ".join(f"{k} {v}" for k, v in sorted(pages.items())) or "none",
                         ", ".join(f"{k} {v}" for k, v in sorted(tickets.items())) or "none"])
    out += table(["Design", "Scope", "Pages by cause", "Tickets by cause"], rows) + [""]

    out += ["## The error-budget policy over the simulated month", ""]
    rows = []
    for w, acc in policy["accounts"].items():
        for s, a in acc.items():
            rows.append([w.upper(), s, num(a["budget_events"]), a["bad"], f"{num(100 * a['consumed'], 4)}%",
                         a["spent_at_clock"] or "",
                         "" if a["causes_when_spent"] is None else ", ".join(f"{k} {v}" for k, v in
                                                                              a["causes_when_spent"].items())])
    out += table(["Workflow", "SLI", "Budget (events)", "Bad events in the month", "Budget used",
                  "Spent at", "Bad events when spent"], rows) + [""]
    rows = []
    for a in policy["actions"]:
        extra = ""
        if a["action"] == "rung down":
            extra = (f"{a['change_record']['change']}: rung {a['plan']['manifest_rung']} to {a['plan']['rung']}, "
                     f"dropped {', '.join(a['plan']['dropped'])}; document by {a['change_record']['document_by']}")
        rows.append([a["at"], a["workflow"].upper(), a["action"], a["sli"], a.get("decided_by", ""), extra])
    out += table(["When (ET)", "Workflow", "Action", "SLI", "Decided by", "Record"], rows) + [""]

    out += ["## The hourly probe and its cost over the simulated month", ""]
    rows = []
    for w, r in probes["cases"].items():
        rows.append([w.upper(), r["case"], f"{r['input_tokens']:,} / {r['output_tokens']:,}", r["probes"], r["served"],
                     f"{r['tokens_in_month']:,}", f"{r['workflow_tokens_in_month']:,}",
                     f"{num(100 * r['over_workflow_tokens'], 4)}%", num(r["usd_in_month"], 4)])
    out += table(["Workflow", "Case", "Tokens a probe (in / out)", "Probes", "Served", "Probe tokens in the month",
                  "The workflow's own tokens", "Probe over own", "USD in the month"], rows) + [""]

    out += ["## fig-16-03 (simulated)", ""]
    rows = [[w.upper(), s["injected_events"], s["alert_kinds"], s["policy_actions"], s["slis"],
             sum(s.values()), "yes" if w == fig["workflow"] else ""] for w, s in fig["chosen_because"].items()]
    out += table(["Workflow", "Injected events that changed its runs", "Kinds of alert", "Kinds of policy action",
                  "SLIs", "Sum", "Chosen"], rows) + [""]

    out += ["## The dashboard's panels", ""]
    rows = [["workflow", p["title"], p["status"], " ".join(p["source"].split())] for p in dashboard["workflow_row"]]
    rows += [["platform", p["title"], p["status"], " ".join(p["source"].split())] for p in dashboard["platform_row"]]
    out += table(["Row", "Panel", "Status", "Source"], rows) + [""]
    path = folder / "summary.md"
    path.write_text("\n".join(out), encoding="utf-8", newline="\n")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--out", type=Path)
    group.add_argument("--summarize", type=Path)
    args = parser.parse_args(argv)
    if args.out:
        write(args.out)
        print(f"wrote {', '.join(FILES)} to {args.out}")
    else:
        print(summarize(args.summarize))
    return 0


if __name__ == "__main__":
    sys.exit(main())
