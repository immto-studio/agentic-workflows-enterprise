"""The upgrade path, run once for real (chapter 16, step 8, O-D14; fig-16-04): the register checked, the retirement
alert on three dates, the candidate behind the alias on a staging gateway under chapter 15's gate, a canary weight
in the gateway watched against O-D12's SLIs, the decision, the remap with its change record, and the data for
fig-16-04, written to results/<date>/lifecycle/.

The candidate is Gemma 4 12B, the local model that is not behind larkspur-chat today (gpt-oss-20b is), so the run
costs nothing. The workflow is W2: its golden set is the cheapest to run end to end (25 questions, two model calls
and one read at the median, about two seconds each), its data class is Internal, and its kept runs on both local
models already exist, so the gate has a baseline to hold the candidate to. Everything runs on this workstation
against the portable Ollama 0.40.13 on 11435, one server on the one GPU; no cloud is called.

The stages, each a step that can run alone (`--only`), reading what the steps before it wrote:

  register    lifecycle/register.py --check, and the local pins against what the Ollama reports   register-check.json
  retirement  lifecycle/retirement.py on three dates: before, inside and past the 90-day window    retirement.json
  gate        chapter 15's live job (labs/ch15/ci/live.py) on W2 with the staging configuration,  gate.json, gate.md,
              set against the baseline as the gate sets it                                          live-w2-gemma4-12b.json
  canary      lifecycle/canary.py, W2's set through the weighted alias, `--passes` times          canary.json, canary-*.jsonl
  decide      lifecycle/decision.py on the gate's rows and the canary's arms                      decision.json
  remap       lifecycle/remap.py as the decision says, then three questions through the new map  remap.json, changes.jsonl,
                                                                                                   litellm.<promoted|restored>.yaml
  fig         lifecycle/upgrade_path.yaml with the run's numbers                                  fig-16-04.json
  summarize   lifecycle/lifecycle_summary.py                                                      summary.md

Run (from labs/ch16, the portable Ollama up on 11435 and alone on the GPU):
  python lifecycle/upgrade.py --out results/<date>/lifecycle --passes 4
  python lifecycle/upgrade.py --out results/<date>/lifecycle --only canary --passes 4
  python lifecycle/upgrade.py --out results/<date>/lifecycle --only summarize
  --today <date> is the run's day (the retirement alert's first date; default today) and --change the remap's change
  number (default CH-<day>-01), so a step run again later writes the same record as the run did.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Callable

import yaml

sys.dont_write_bytecode = True
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")  # the proxies read the price map from the wheel
os.environ.setdefault("LEDGER_OFFLINE", "1")
os.environ.setdefault("PYTHONUTF8", "1")
HERE = Path(__file__).resolve().parent
LAB = HERE.parent
ROOT = LAB.parents[1]
for folder in (LAB / "budget", LAB / "slo", LAB / "ledger", HERE):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
import offline  # noqa: E402

import canary  # noqa: E402  (puts chapter 15's folders on the path)
import decision as deciding  # noqa: E402
import register as registry_file  # noqa: E402
import remap as remapping  # noqa: E402
import retirement  # noqa: E402
from record import scrub  # noqa: E402

import gate  # noqa: E402  chapter 15's gate
import live  # noqa: E402  chapter 15's live job
import registry  # noqa: E402
import run_redteam  # noqa: E402

OLLAMA = "http://127.0.0.1:11435"
OLLAMA_PORT = 11435
CANDIDATE, CONTROL = "gemma4-12b", "gpt-oss-20b"
WORKFLOW = "w2"
STAGING = "labs/ch16/lifecycle/litellm.staging.yaml"
LATER_DATES = (dt.date(2027, 2, 1), dt.date(2027, 5, 1))  # inside and past gpt-4o's 90 days; the run's day comes first
STEPS = ("register", "retirement", "gate", "canary", "decide", "remap", "fig", "summarize")
LIVE_RESULT = f"live-{WORKFLOW}-{CANDIDATE}.json"
BY = {"promote": "platform.team@larkspur.example", "back": "oncall.lead@larkspur.example"}
PROBE_CASES = 3
Progress = Callable[[str], None]


def dump(path: Path, obj: Any, indent: int | None = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scrub(obj), indent=indent, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def read(out: Path, name: str) -> Any:
    return json.loads((out / name).read_text(encoding="utf-8"))


# --- the steps --------------------------------------------------------------------------------------------------

def register_step(out: Path, progress: Progress) -> None:
    reg = registry_file.load()
    problems = registry_file.check(reg)
    counts = {c: sum(1 for m in registry_file.models(reg) if m["cloud"] == c) for c in registry_file.CLOUDS}
    digests = registry_file.digests(reg, OLLAMA)
    dump(out / "register-check.json", {
        "measured": True, "register": "labs/ch16/lifecycle/register.yaml", "read_on": reg["read_on"].isoformat(),
        "models": len(registry_file.models(reg)), "by_cloud": counts,
        "pinned": sum(1 for m in registry_file.models(reg) if m["pinned"]),
        "deployments": len(registry_file.register_deployments(reg)),
        "unversioned_pins": [m["id"] for m in registry_file.models(reg) if m["pin"].get("versioned") is False],
        "with_a_retirement_date": [m["id"] for m in registry_file.models(reg) if m["retires"]],
        "configurations_checked": reg["gateways"]["litellm"], "terraform_checked": [t["path"] for t in reg["gateways"]["terraform"]],
        "problems": problems, "digests": digests})
    progress(f"register: {len(problems)} problems; digests match: {all(r['matches'] for r in digests['models'])}")
    if problems:
        raise SystemExit("the register does not agree with the gateways:\n" + "\n".join(problems))


def retirement_step(out: Path, today: dt.date, progress: Progress) -> None:
    rules = retirement.load_rules()
    dates = (today,) + LATER_DATES
    dump(out / "retirement.json", {"measured": True, "simulated": False, "rules": rules,
                                   "dates": {d.isoformat(): retirement.evaluate(d) for d in dates}})
    progress("retirement: " + "; ".join(f"{d}: {retirement.evaluate(d)['counts']}" for d in dates))


def gate_step(out: Path, scratch: Path, progress: Progress) -> None:
    """Chapter 15's live job on W2 with the candidate behind the alias, and the gate's comparison."""
    live.CONFIGS[(WORKFLOW, CANDIDATE)] = STAGING
    plan = live.Plan(model=CANDIDATE, judge=CONTROL, ollama_port=OLLAMA_PORT, judge_ollama_port=OLLAMA_PORT,
                     workflows=(WORKFLOW,))
    started = time.perf_counter()
    path = live.run(plan, scratch / "live", progress=progress)
    write_gate(out, registry.read_json(path), round(time.perf_counter() - started, 1), progress)


def write_gate(out: Path, result: dict[str, Any], seconds: float, progress: Progress) -> None:
    """The gate's comparison of a live result with the baseline, and the files: gate.json, gate.md, the result."""
    baseline = registry.read_json(gate.BASELINE)
    thresholds, problems = gate.load_thresholds()
    if problems:
        raise SystemExit("\n".join(problems))
    report = gate.compare(baseline, result, thresholds)
    mine = report["workflows"][WORKFLOW]
    rows = mine["rows"]
    regressed = [r["check"] for r in rows if r["verdict"] == "regressed"]
    (out / "gate.md").write_text(gate.render(report, gate.BASELINE.name, LIVE_RESULT), encoding="utf-8", newline="\n")
    dump(out / LIVE_RESULT, result)
    dump(out / "gate.json", {
        "measured": True, "workflow": WORKFLOW, "candidate": CANDIDATE, "judge": CONTROL,
        "staging_config": STAGING, "live_result": LIVE_RESULT, "seconds": seconds,
        "run": result["run"], "baseline": {"source": baseline["source"]["kind"], "run": baseline["workflows"][WORKFLOW]["run"],
                                           "model": baseline["source"]["model"], "judge": baseline["source"]["judge"]},
        "pins": {"w2": result["pins"]["workflows"][WORKFLOW], "judge": result["pins"]["judge"]},
        "pin_problems": {"w2": report["pins"].get(WORKFLOW, []), "the judge": report["pins"].get(gate.ALL, [])},
        "problems": report["problems"], "rows": rows, "regressed": regressed,
        "held": sum(1 for r in rows if r["verdict"] == "held"),
        "not_gated": sum(1 for r in rows if r["verdict"] == "not gated"),
        "judge_tally": mine["judge"], "tokens": mine["tokens"],
        "whole_gate": {"passed": report["passed"], "invalid": report["invalid"],
                       "why": "the gate of E-D9 gates a complete run of all six sets against a baseline whose pins "
                              "match; this run is W2's set alone on a remapped alias, so the gate as built fails it "
                              "on the partial run and the unmatched pins and lists the regression beside them; the "
                              "path reads the checks (rows) and lists the pins"},
        "verdict": "regressed" if regressed else "held"})
    progress(f"gate: {len(rows)} checks, {len(regressed)} regressed, {seconds} s")


def canary_step(out: Path, scratch: Path, passes: int, limit: int | None, progress: Progress) -> None:
    canary.run(passes, out, scratch / "canary", limit, progress=progress)
    result = read(out, "canary.json")
    progress("canary: " + json.dumps(result["runs"]["by_group"]) + f"; calls {result['calls']['total']}")


def decide_step(out: Path, progress: Progress) -> None:
    gate_json, canary_json = read(out, "gate.json"), read(out, "canary.json")
    # One server swaps the two models on this workstation, so the latency SLI the rule reads is the one with the
    # loads taken out; the measured one is beside it in canary.json and in the decision's `as_measured`.
    verdict = deciding.decide(gate_json["rows"], canary_json["by_arm"], latency_key="latency_without_loads")
    measured = deciding.decide(gate_json["rows"], canary_json["by_arm"], latency_key="latency")
    dump(out / "decision.json", {"measured": True, "workflow": WORKFLOW, "candidate": CANDIDATE, "control": CONTROL,
                                 **verdict, "as_measured": {"decision": measured["decision"], "because": measured["because"],
                                                            "latency": measured["slis"]["latency"]},
                                 "why_the_loads_are_taken_out": canary_json["how_the_slis_are_counted"]["latency_without_loads"],
                                 "reads": ["gate.json", "canary.json"]})
    progress(f"decision: {verdict['decision']}; " + "; ".join(verdict["because"])
             + f" (as measured, with the loads: {measured['decision']})")


def probe(config: Path, scratch: Path, progress: Progress) -> dict[str, Any]:
    """Three of W2's questions through chapter 5's gateway on the written configuration: which deployment served."""
    manifests = registry.path(run_redteam.MANIFESTS[WORKFLOW])
    hooks = registry.path(run_redteam.HOOKS[WORKFLOW])
    scratch.mkdir(parents=True, exist_ok=True)
    url, log, stop = live.start_gateway("probe", config, manifests, hooks, scratch)
    try:
        run_ = run_redteam.Run("probe", scratch, None)
        run_redteam.run_w2(run_, live.golden_items(WORKFLOW, PROBE_CASES), url, progress)
        live.settle(log)
    finally:
        stop()
    calls = [e for e in registry.read_jsonl(log) if e.get("event") == "call"]
    outputs = registry.read_jsonl(scratch / "outputs.jsonl")
    return {"cases": [o["case"] for o in outputs], "calls": len(calls),
            "deployments": sorted({c["deployment"] for c in calls}),
            "served_models": sorted({c["served_model"] for c in calls}),
            "ends": [canary.slis._answer_end(o["output"]["answer"], *_w2_sentences())[0] for o in outputs],
            "seconds": [o["seconds"] for o in outputs]}


def _w2_sentences() -> tuple[str, str, str]:
    s = canary.slis.sentences()
    return s.w2_budget, s.w2_read_failed, s.w2_refusal_words


def write_remap(out: Path, change: str, now: dt.datetime) -> tuple[Path, dict[str, Any], str] | None:
    """The remap the decision asks for, written beside the results with its record: the path, the record, and the
    deployment the alias should serve now; None when the canary is extended. The record's reason is the decision's."""
    decided = read(out, "decision.json")
    reason = "; ".join(decided["because"])
    evidence = ["gate.json", "gate.md", LIVE_RESULT, "canary.json", "canary-calls.jsonl", "canary-runs.jsonl", "decision.json"]
    header = f"# Written by lifecycle/remap.py on {now.date().isoformat()} for change {change}: see changes.jsonl beside it."
    if decided["decision"] == deciding.PROMOTE:
        path, record = remapping.remap("promote", canary.CANARY, HERE / "litellm.staging.yaml", out / "litellm.promoted.yaml",
                                       change=change, by=BY["promote"], reason=f"larkspur-chat moves to the candidate: {reason}",
                                       evidence=evidence, now=now, header=header,
                                       names_as=("lifecycle/litellm.canary.yaml", "litellm.promoted.yaml"))
        return path, record, "candidate-gemma4-12b-chat"
    if decided["decision"] == deciding.BACK:
        path, record = remapping.remap("back", canary.CANARY, HERE / "litellm.current.yaml", out / "litellm.restored.yaml",
                                       change=change, by=BY["back"],
                                       reason=f"larkspur-chat goes back to the model it served before: {reason}",
                                       evidence=evidence, now=now, header=header,
                                       names_as=("lifecycle/litellm.canary.yaml", "litellm.restored.yaml"))
        return path, record, "local-gpt-oss-20b-chat"
    return None


def remap_step(out: Path, scratch: Path, change: str, progress: Progress) -> None:
    decided = read(out, "decision.json")["decision"]
    written = write_remap(out, change, dt.datetime.now(dt.timezone.utc))
    if written is None:
        dump(out / "remap.json", {"measured": True, "decision": decided, "remapped": False,
                                  "why": "the canary is extended; the alias map stays the canary's until the rule has its runs"})
        progress("remap: none; the canary continues")
        return
    path, record, expected = written
    served = probe(path, scratch / "probe", progress)
    dump(out / "remap.json", {"measured": True, "decision": decided, "remapped": True, "config": path.name,
                              "record": record, "probe": served | {"expected_deployment": expected,
                                                                  "every_call_on_it": served["deployments"] == [expected]}})
    progress(f"remap: {record['lever']}; probe served by {served['deployments']}")


def fig_step(out: Path, progress: Progress) -> None:
    design = yaml.safe_load((HERE / "upgrade_path.yaml").read_text(encoding="utf-8"))
    reg_check, ret, gate_json = read(out, "register-check.json"), read(out, "retirement.json"), read(out, "gate.json")
    canary_json, decided = read(out, "canary.json"), read(out, "decision.json")
    remapped = read(out, "remap.json") if (out / "remap.json").exists() else {"remapped": False}
    today = next(iter(ret["dates"].values()))  # the first date is the run's day
    candidate_pin = next(r["pinned_digest"] for r in reg_check["digests"]["models"] if r["model"] == "local-gemma4-12b")
    numbers: dict[str, dict[str, Any]] = {
        "register": {"models": reg_check["models"], "by_cloud": reg_check["by_cloud"], "pinned": reg_check["pinned"],
                     "deployments": reg_check["deployments"], "problems": len(reg_check["problems"]),
                     "candidate": "local-gemma4-12b", "candidate_pin": candidate_pin[:12],
                     "alert_today": {"tickets": today["tickets"], "review_rows": today["review_rows"], "pages": today["pages"]}},
        "staging": {"cases": gate_json["pins"]["w2"]["set"]["cases"],
                    "checks": len(gate_json["rows"]), "held": gate_json["held"], "regressed": gate_json["regressed"],
                    "not_gated": gate_json["not_gated"], "pin_problems": sum(len(v) for v in gate_json["pin_problems"].values()),
                    "verdict": gate_json["verdict"], "seconds": gate_json["seconds"]},
        "canary": {"share": canary_json["arms"]["candidate-gemma4-12b-chat"]["share"], "passes": canary_json["passes"],
                   "runs": canary_json["runs"]["total"], "by_group": canary_json["runs"]["by_group"],
                   "calls": canary_json["calls"]["total"], "candidate_calls": canary_json["by_arm"]["candidate"]["calls"],
                   "slis": {arm: {s: canary_json["by_arm"][arm]["runs_touched"][s]
                                  for s in ("success", "latency", "latency_without_loads")}
                            for arm in ("control", "candidate")},
                   "swaps": canary_json["server"]["swaps"]["loads"], "seconds": canary_json["seconds"]},
        "decision": {"decision": decided["decision"], "because": decided["because"],
                     "latency_read_from": decided["rule"]["latency_read_from"],
                     "as_measured": decided["as_measured"]["decision"]},
        "remap": ({"change": remapped["record"]["change"], "kind": remapped["record"]["kind"], "lever": remapped["record"]["lever"],
                   "from": remapped["record"]["from"], "to": remapped["record"]["to"], "probe_calls": remapped["probe"]["calls"],
                   "probe_served_by": remapped["probe"]["deployments"]} if remapped.get("remapped") else {"remapped": False}),
        "after": {"ran": False, "waits_for": "the live job on the new map and the review that accepts it (E-D9)"}}
    stages = [dict(s) | {"numbers": numbers.get(s["id"], {})} for s in design["stages"]]
    dump(out / "fig-16-04.json", {"measured": True, "simulated": False, "figure": design["figure"], "workflow": WORKFLOW,
                                  "candidate": CANDIDATE, "control": CONTROL, "stages": stages}, indent=1)
    progress("fig-16-04: " + ", ".join(s["id"] for s in stages))


def summarize_step(out: Path, progress: Progress) -> None:
    import lifecycle_summary
    path = lifecycle_summary.write(out)
    progress(f"wrote {path.name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only", choices=STEPS, nargs="*", help="these steps alone, in the path's order")
    parser.add_argument("--passes", type=int, default=4, help="W2's set this many times through the canary")
    parser.add_argument("--limit", type=int, help="the first N cases each canary pass: a smoke run")
    parser.add_argument("--scratch", type=Path, help="the raw records' folder; default lifecycle/_lab/upgrade-<stamp>")
    parser.add_argument("--today", type=dt.date.fromisoformat, default=dt.date.today(),
                        help="the run's day, the first date the retirement alert is computed for; default today")
    parser.add_argument("--change", help="the remap's change number; default CH-<the run's day>-01")
    args = parser.parse_args(argv)
    change = args.change or f"CH-{args.today.strftime('%Y%m%d')}-01"
    offline.block_network()
    steps = [s for s in STEPS if not args.only or s in args.only]
    # Absolute paths: chapter 15's start_gateway runs the proxy from W2's hooks folder, so a relative --config
    # would point nowhere from there.
    scratch = (args.scratch or HERE / "_lab" / f"upgrade-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}").resolve()
    args.out = args.out.resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    args.out.mkdir(parents=True, exist_ok=True)

    def progress(line: str) -> None:
        print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {line}", flush=True)

    for step in steps:
        progress(f"step {step}")
        if step == "register":
            register_step(args.out, progress)
        elif step == "retirement":
            retirement_step(args.out, args.today, progress)
        elif step == "gate":
            gate_step(args.out, scratch, progress)
        elif step == "canary":
            canary_step(args.out, scratch, args.passes, args.limit, progress)
        elif step == "decide":
            decide_step(args.out, progress)
        elif step == "remap":
            remap_step(args.out, scratch, change, progress)
        elif step == "fig":
            fig_step(args.out, progress)
        elif step == "summarize":
            summarize_step(args.out, progress)
    if scratch.exists() and not any(scratch.iterdir()):
        shutil.rmtree(scratch)
    return 0


if __name__ == "__main__":
    sys.exit(main())
