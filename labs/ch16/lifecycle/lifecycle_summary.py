"""Step 8's summary: every table the README's step 8 section prints, written from the committed files.

Chapter 16, step 8. `lifecycle/upgrade.py` writes register-check.json, retirement.json, gate.json, gate.md, the live
result, canary.json with its two JSON Lines files, decision.json, remap.json, changes.jsonl, the written
configuration, and fig-16-04.json to results/<date>/lifecycle/; this writes summary.md beside them from those files
and from lifecycle/register.yaml, the same bytes each time.

Run (from labs/ch16):  python lifecycle/upgrade.py --out results/<date>/lifecycle --only summarize
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
LAB = HERE.parent
for folder in (LAB / "capacity", HERE):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
import register as registry_file  # noqa: E402
from summary import num, table  # noqa: E402  step 5's table helpers

FILES = ("canary-calls.jsonl", "canary-runs.jsonl", "canary.json", "changes.jsonl", "decision.json", "fig-16-04.json",
         "gate.json", "gate.md", "live-w2-gemma4-12b.json", "register-check.json", "remap.json", "retirement.json",
         "summary.md")


def load(folder: Path, name: str) -> Any:
    return json.loads((folder / name).read_text(encoding="utf-8"))


def ratio(r: dict[str, Any] | None) -> str:
    if r is None:
        return "none"
    if not r["valid"]:
        return "no events"
    return f"{r['good']} / {r['valid']} ({num(100 * r['value'], 4)}%)"


def date_or_none(m: dict[str, Any]) -> str:
    if m.get("retires"):
        return m["retires"].isoformat()
    if m.get("retires_no_earlier_than"):
        return f"no earlier than {m['retires_no_earlier_than'].isoformat()}"
    return "none published"


def pin_cell(m: dict[str, Any]) -> str:
    pin = m["pin"]
    value = str(pin["value"])
    shown = value[:12] if pin["kind"] == "ollama digest" else value
    return f"{pin['kind']}: {shown}" + ("" if pin.get("versioned") else " (no version in it)")


def write(folder: Path) -> Path:
    reg = registry_file.load()
    check = load(folder, "register-check.json")
    ret = load(folder, "retirement.json")
    gate = load(folder, "gate.json")
    canary = load(folder, "canary.json")
    decision = load(folder, "decision.json")
    remap = load(folder, "remap.json") if (folder / "remap.json").exists() else None
    fig = load(folder, "fig-16-04.json")
    out = ["# Chapter 16, step 8: the model register and the upgrade path", "",
           "Written by `lifecycle/upgrade.py --only summarize` from the files beside it. Everything here is MEASURED "
           "on this workstation; nothing is simulated.", ""]

    out += ["## The register", ""]
    rows = []
    for m in registry_file.models(reg):
        aliases = sorted({a for d in m["deployments"] for a in d["aliases"]})
        where = aliases or [d.get("note", "").split(";")[0] or d["id"] for d in m["deployments"]]
        rows.append([m["name"], m["cloud"], "yes" if m["pinned"] else "no", m["stage"], date_or_none(m),
                     pin_cell(m), ", ".join(where) if m["deployments"] else "none"])
    out += table(["Model", "Cloud", "Larkspur runs on it", "Stage", "Retires", "Pin", "Behind"], rows) + [""]
    rows = [[c, n] for c, n in check["by_cloud"].items()]
    rows.append(["all", check["models"]])
    out += table(["Cloud", "Models"], rows) + [""]
    rows = []
    for d in check["digests"]["models"]:
        rows.append([d["tag"], d["pinned_digest"][:12], d["reported_digest"][:12] if d["reported_digest"] else "not served",
                     "yes" if d["matches"] else "no", f"{d['size_bytes'] / 1e9:.2f} GB" if d["size_bytes"] else ""])
    out += table(["Tag", "Pinned digest", f"Reported by Ollama {check['digests']['ollama']}", "Matches", "Size"], rows) + [""]
    out += [f"Configurations checked: {len(check['configurations_checked'])} LiteLLM files and "
            f"{len(check['terraform_checked'])} Terraform files; problems: {len(check['problems'])}; "
            f"deployments: {check['deployments']}; pins without a version: {', '.join(check['unversioned_pins'])}.", ""]

    out += ["## The retirement alert on three dates", ""]
    rows = []
    for day, result in ret["dates"].items():
        counts = result["counts"]
        rows.append([day, counts["retired"], counts["alert"], counts["review"], counts["clear"], counts["unscheduled"],
                     result["pages"], result["tickets"], result["review_rows"]])
    out += table(["Date", "Retired", "Within 90 days", "Within 180", "Further off", "No date published", "Pages",
                  "Tickets", "Review rows"], rows) + [""]
    rows = []
    for day, result in ret["dates"].items():
        for a in result["alerts"]:
            rows.append([day, a["action"], a["rule"], a["name"], a["cloud"], "yes" if a["pinned"] else "no",
                         a["retires"] or "", "" if a["days_left"] is None else a["days_left"]])
    out += table(["Date", "Action", "Rule", "Model", "Cloud", "Larkspur runs on it", "Retires", "Days left"], rows) + [""]

    out += ["## The gate: the candidate behind the alias on staging", ""]
    run = gate["run"]
    out += table(["Workflow", "Candidate", "Judge", "Cases", "Complete run", "Seconds", "Checks", "Held", "Regressed",
                  "Not gated", "Pin problems", "Verdict for the path"],
                 [[gate["workflow"].upper(), gate["candidate"], gate["judge"], gate["pins"]["w2"]["set"]["cases"],
                   "yes" if run["complete"] else f"no: {run['why_partial']}", gate["seconds"], len(gate["rows"]), gate["held"],
                   ", ".join(gate["regressed"]) or "none", gate["not_gated"],
                   sum(len(v) for v in gate["pin_problems"].values()), gate["verdict"]]]) + [""]
    rows = []
    for r in gate["rows"]:
        rows.append([r["check"], "not gated" if r["threshold"] is None else r["threshold"],
                     f"{r['baseline']['passed']} of {r['baseline']['passed'] + r['baseline']['failed']}",
                     f"{r['run']['passed']} of {r['run']['passed'] + r['run']['failed']}",
                     ", ".join(r["lost"]) or "-", ", ".join(r["gained"]) or "-", r["verdict"]])
    out += table(["Check", "Threshold", "Baseline", "Candidate", "Lost", "Gained", "Verdict"], rows) + [""]
    rows = [[scope, p] for scope, found in gate["pin_problems"].items() for p in found]
    out += table(["Pins", "What differs from the baseline"], rows) + [""]
    tally = gate["judge_tally"]["run"]
    out += table(["Judge", "Outputs read", "Withheld as sampled texts", "Right", "Wrong", "No verdict"],
                 [[gate["judge"], tally["judged"], tally["withheld"], tally["right"], tally["wrong"], tally["no_verdict"]]]) + [""]
    tokens = gate["tokens"]["run"]
    out += table(["Tokens", "Calls", "Prompt", "Completion"],
                 [["the candidate, W2's set", tokens["workflow"]["calls"], tokens["workflow"]["prompt"], tokens["workflow"]["completion"]],
                  ["the judge", tokens["judge"]["calls"], tokens["judge"]["prompt"], tokens["judge"]["completion"]]]) + [""]

    out += ["## The canary", ""]
    arms = canary["arms"]
    rows = [[d, a["arm"], a["model"], num(a["weight"]), f"{num(100 * a['share'], 4)}%", str(a["think"]), a["num_ctx"]]
            for d, a in arms.items()]
    out += table(["Deployment", "Arm", "Model", "Weight", "Share asked", "Thinking", "num_ctx"], rows) + [""]
    out += table(["Passes", "Cases a pass", "Runs", "Calls", "Failed calls", "Calls a run (median)", "Seconds",
                  "Ollama", "Swaps: loads of each model", "Both models resident at once"],
                 [[canary["passes"], canary["cases_a_pass"], canary["runs"]["total"], canary["calls"]["total"],
                   canary["calls"]["failed"], num(canary["runs"]["calls_median"]), canary["seconds"], canary["server"]["ollama"],
                   ", ".join(f"{k} {v}" for k, v in canary["server"]["swaps"]["loads"].items()),
                   "yes" if canary["server"]["swaps"]["both_at_once"] else "no"]]) + [""]
    rows = []
    for arm in ("control", "candidate"):
        a = canary["by_arm"][arm]
        rows.append([arm, a["calls"], f"{num(100 * a['share_of_calls'], 4)}%", a["failed_calls"],
                     num(a["latency_ms_median"]), num(a["latency_ms_p95"]), a["calls_after_a_swap"],
                     num(a["latency_ms_median_after_a_swap"]), num(a["latency_ms_median_steady"]),
                     num(a["load_s_median"]), num(a["load_s_max"]), num(a["load_s_total"])])
    out += table(["Arm", "Calls", "Share served", "Failed", "Latency ms, median", "p95", "Calls after a swap",
                  "Median after a swap", "Median with no swap", "Load s, median", "Load s, max", "Load s, total"], rows) + [""]
    rows = [[g, v["runs"], ", ".join(f"{k.replace('_', ' ')} {n}" for k, n in v["ends"].items()) or "",
             ratio(v["success"]), ratio(v["latency"]), ratio(v["latency_without_loads"]),
             num(v["seconds_median"]), num(v["seconds_without_loads_median"]), v["runs_with_a_load"]]
            for g, v in canary["by_group"].items()]
    out += table(["Runs served by", "Runs", "Ends", "Success", f"Latency under {num(canary['threshold_s'])} s",
                  "Latency, loads taken out", "Seconds, median", "Without loads, median", "Runs with a load"], rows) + [""]
    rows = []
    for arm in ("control", "candidate"):
        t = canary["by_arm"][arm]["runs_touched"]
        rows.append([arm, t["runs"], ", ".join(f"{k.replace('_', ' ')} {n}" for k, n in t["ends"].items()),
                     ratio(t["success"]), ratio(t["latency"]), ratio(t["latency_without_loads"]),
                     num(t["seconds_median"]), num(t["seconds_without_loads_median"]), num(t["loads_s_total"])])
    out += table(["Arm, over the runs it served", "Runs", "Ends", "Success", "Latency", "Latency, loads taken out",
                  "Seconds, median", "Without loads, median", "Load s in its runs"], rows) + [""]

    out += ["## The decision", ""]
    rows = []
    for sli, c in decision["slis"].items():
        rows.append([sli, c["read"], ratio(c["control"]), ratio(c["candidate"]),
                     "yes" if c["candidate_not_below_control"] else "no"])
    out += table(["SLI", "Read from", "Control", "Candidate", "Candidate not below control"], rows) + [""]
    out += table(["Decision", "Gate", "Minimum runs", "As measured, loads included", "Because"],
                 [[decision["decision"], f"{decision['gate']['held']} held, {len(decision['gate']['regressed'])} regressed, "
                   f"{decision['gate']['not_gated']} not gated", decision["rule"]["min_runs"],
                   decision["as_measured"]["decision"], "; ".join(decision["because"])]]) + [""]

    out += ["## The remap", ""]
    if remap and remap.get("remapped"):
        rec, probe = remap["record"], remap["probe"]
        out += table(["Change", "Kind", "Lever", "Alias", "From", "To", "By", "Authority", "Document by", "Review",
                      "Takes effect"],
                     [[rec["change"], rec["kind"], rec["lever"], rec["alias"],
                       ", ".join(f"{d['id']}" + (f" (weight {num(d['weight'])})" if "weight" in d else "") for d in rec["from"]),
                       ", ".join(d["id"] for d in rec["to"]), rec["by"], rec["authority"], rec["document_by"], rec["review"],
                       rec["takes_effect"]]]) + [""]
        out += table(["After the remap", "Cases", "Calls", "Served by", "Every call on the expected deployment", "Ends",
                      "Seconds"],
                     [[remap["config"], ", ".join(probe["cases"]), probe["calls"], ", ".join(probe["deployments"]),
                       "yes" if probe["every_call_on_it"] else "no", ", ".join(probe["ends"]),
                       ", ".join(num(s) for s in probe["seconds"])]]) + [""]
    else:
        out += table(["Decision", "Remapped", "Why"], [[decision["decision"], "no", (remap or {}).get("why", "")]]) + [""]

    out += ["## fig-16-04", ""]
    rows = []
    for s in fig["stages"]:
        numbers = s.get("numbers") or {}
        shown = []
        for k, v in numbers.items():
            if isinstance(v, (dict, list)):
                continue
            shown.append(f"{k} {v}")
        rows.append([s["id"], s["name"], s["gate"], "; ".join(shown)])
    out += table(["Stage", "Name", "What gates it", "The run's numbers"], rows) + [""]
    path = folder / "summary.md"
    path.write_text("\n".join(out), encoding="utf-8", newline="\n")
    return path


if __name__ == "__main__":
    print(write(Path(sys.argv[1])))
