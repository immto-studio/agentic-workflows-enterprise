"""The gate (chapter 15, step 7, E-D9): the last committed live run against the accepted baseline, check by check.

The pull-request job runs it last, and each of these fails it:

  thresholds  baseline/thresholds.yaml gives every check of every set a threshold and a reason that exists
              (measure.check_names), and names no check that doesn't
  baseline    the baseline is not what its source gives (ci/baseline.py --check)
  the run     the last file in live/ (by name, which starts with the run's UTC time) is a partial run, or was
              made on sets, a prompt, or rubrics the repository no longer holds: a stale run
  pins        a pin of the run differs from the baseline's, or the baseline holds none (E-D12): a set's version,
              a workflow's alias map, a model's digest or the Ollama serving it, the judge's model, digest,
              server, or alias map, the prompt's or a rubric's hash. The baseline is then invalid until a run is
              accepted (ci/live.py --accept)
  checks      per workflow and check, more cases than the threshold allows that passed in the baseline and fail
              in the run, or that the run no longer decides or doesn't hold

A case that passes now and failed in the baseline offsets nothing, so a new failure can't hide behind an old one
that went away. The judge's verdicts are reported beside the checks and gated for no workflow; thresholds.yaml
gives the reason, from the calibration of step 5. With no live run committed, the gate checks the thresholds and
the baseline, prints the baseline, and says so.

Run (from labs/ch15):  python ci/gate.py
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
LAB = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import measure  # noqa: E402  (puts the lab's folders on sys.path)
import registry  # noqa: E402

BASELINE = LAB / "baseline" / "baseline.json"
THRESHOLDS = LAB / "baseline" / "thresholds.yaml"
LIVE = LAB / "live"
ALL = "the judge"  # the scope of the pins every workflow shares: the judge's model and its prompt


# --- the thresholds ---------------------------------------------------------------------------------------------

def load_thresholds(path: Path = THRESHOLDS) -> tuple[dict[str, dict[str, dict[str, Any]]], list[str]]:
    """The thresholds by workflow and check, each with its reason's text, and what is wrong with the file: a
    check without an entry, an entry for a check that doesn't exist, a value that is not a count or null, a
    reason that isn't written."""
    data = registry.read_yaml(path) or {}
    reasons = data.get("reasons") or {}
    out: dict[str, dict[str, dict[str, Any]]] = {}
    problems = []
    for workflow in measure.WORKFLOWS:
        given = (data.get("workflows") or {}).get(workflow) or {}
        names = measure.check_names(workflow)
        problems += [f"{workflow}: no threshold for {n}" for n in names if n not in given]
        problems += [f"{workflow}: {n} is not a check of this set" for n in given if n not in names]
        out[workflow] = {}
        for name in names:
            entry = given.get(name) or {}
            value, reason = entry.get("threshold"), entry.get("reason")
            if name in given and not (value is None or (isinstance(value, int) and not isinstance(value, bool) and value >= 0)):
                problems.append(f"{workflow}: {name}'s threshold is {value!r}, not a count of cases or null")
            if name in given and not str(reasons.get(reason) or "").strip():
                problems.append(f"{workflow}: {name} names the reason {reason!r}, which the file doesn't write")
            out[workflow][name] = {"threshold": value, "reason": reason, "why": " ".join(str(reasons.get(reason) or "").split()),
                                   "note": entry.get("note")}
    return out, problems


# --- the run ------------------------------------------------------------------------------------------------------

def latest_live(folder: Path = LIVE) -> Path | None:
    """The last live result committed: live/<UTC time>-<model>.json, the latest by name."""
    found = sorted(folder.glob("*.json")) if folder.is_dir() else []
    return found[-1] if found else None


def stale(run: dict[str, Any], now: dict[str, Any] | None = None) -> list[str]:
    """What the run was made on that the repository no longer holds: a set's version, the prompt, a rubric."""
    now = now or measure.current_pins()
    pins, out = run["pins"], []
    if pins.get("prompt") != now["prompt"]:
        out.append(f"the judge's prompt is {measure.short(now['prompt'])} now; the run read "
                   f"{measure.short(pins.get('prompt'))}")
    for workflow, pin in pins["workflows"].items():
        if pin["set"]["version"] != now["sets"][workflow]["version"]:
            out.append(f"{workflow}: the set is version {measure.short(now['sets'][workflow]['version'])} now; the run "
                       f"ran {measure.short(pin['set']['version'])}")
        if workflow in measure.JUDGED and pin.get("rubric") != now["rubrics"][workflow]:
            out.append(f"{workflow}: the rubric is {measure.short(now['rubrics'][workflow])} now; the run's judge read "
                       f"{measure.short(pin.get('rubric'))}")
    return out


# --- the pins -----------------------------------------------------------------------------------------------------

def _changed_aliases(before: dict[str, str], after: dict[str, str]) -> str:
    parts = [f"{alias} {before.get(alias, 'absent')} -> {after.get(alias, 'absent')}"
             for alias in sorted(set(before) | set(after)) if before.get(alias) != after.get(alias)]
    return "; ".join(parts)


def pin_problems(baseline: dict[str, Any], run: dict[str, Any]) -> dict[str, list[str]]:
    """Each pin of the run that differs from the baseline's, or that the baseline doesn't hold, by the workflow
    it invalidates (ALL for the judge and its prompt)."""
    out: dict[str, list[str]] = defaultdict(list)
    if baseline.get("prompt") != run.get("prompt"):
        out[ALL].append(f"the judge's prompt changed: {measure.short(baseline.get('prompt'))} -> "
                        f"{measure.short(run.get('prompt'))}")
    before, after = baseline.get("judge") or {}, run.get("judge") or {}
    for key in ("model", "served", "aliases", "server", "digest"):
        if before.get(key) is None:
            out[ALL].append(f"the baseline holds no {key} for the judge")
        elif before.get(key) != after.get(key):
            if key == "aliases":
                out[ALL].append(f"the judge's alias map changed: {_changed_aliases(before[key], after.get(key) or {})}")
            elif key == "digest":
                out[ALL].append(f"the judge's digest changed: {measure.short(before[key])} -> {measure.short(after.get(key))}")
            else:
                out[ALL].append(f"the judge's {key} changed: {before[key]} -> {after.get(key)}")
    for workflow in measure.WORKFLOWS:
        b, r = baseline["workflows"].get(workflow), run["workflows"].get(workflow)
        if b is None and r is None:
            continue
        if b is None or r is None:
            out[workflow].append(f"the {'baseline' if b is None else 'run'} holds no pins for this set")
            continue
        if b["set"]["version"] != r["set"]["version"]:
            out[workflow].append(f"the set changed: version {measure.short(b['set']['version'])} -> "
                                 f"{measure.short(r['set']['version'])}")
        if b.get("rubric") != r.get("rubric"):
            out[workflow].append(f"the rubric changed: {measure.short(b.get('rubric'))} -> {measure.short(r.get('rubric'))}")
        if b.get("aliases") is None:
            out[workflow].append("the baseline holds no alias map")
        elif b["aliases"] != r.get("aliases"):
            out[workflow].append(f"the alias map changed: {_changed_aliases(b['aliases'], r.get('aliases') or {})}")
        for served in sorted(set(r.get("models") or {})):
            held, now = (b.get("models") or {}).get(served), r["models"][served]
            if held is None or held.get("digest") is None:
                out[workflow].append(f"{served}: the baseline holds no digest for it")
            elif held["digest"] != now.get("digest"):
                out[workflow].append(f"{served}: the digest changed: {measure.short(held['digest'])} -> "
                                     f"{measure.short(now.get('digest'))}")
            elif held.get("server") != now.get("server"):
                out[workflow].append(f"{served}: Ollama {now.get('server')} serves it, where the baseline's was "
                                     f"{held.get('server')}")
    return dict(out)


# --- the checks ---------------------------------------------------------------------------------------------------

def compare_workflow(workflow: str, baseline: dict[str, Any], run: dict[str, Any],
                     thresholds: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per check: the counts in the baseline and in the run, the cases that passed in the baseline and
    don't now (lost), those that pass now and didn't (gained), the threshold, and the verdict."""
    rows = []
    for name in measure.case_checks(workflow):
        threshold = thresholds[name]["threshold"]
        lost = [c for c, v in baseline["cases"].items() if v.get(name) is True and (run["cases"].get(c) or {}).get(name) is not True]
        gained = [c for c, v in run["cases"].items() if v.get(name) is True and (baseline["cases"].get(c) or {}).get(name) is not True]
        verdict = "not gated" if threshold is None else "regressed" if len(lost) > threshold else "held"
        rows.append({"check": name, "threshold": threshold, "reason": thresholds[name]["reason"],
                     "baseline": baseline["tally"][name], "run": run["tally"][name], "lost": lost, "gained": gained,
                     "verdict": verdict})
    return rows


def compare(baseline: dict[str, Any], run: dict[str, Any], thresholds: dict[str, dict[str, dict[str, Any]]],
            now: dict[str, Any] | None = None) -> dict[str, Any]:
    """The run against the baseline: what makes the comparison unsound (a partial or stale run, invalid pins),
    and per workflow every check's row and the judge's verdicts beside them."""
    problems = []
    if not run["run"].get("complete"):
        problems.append(f"the run is partial ({run['run'].get('why_partial') or 'not every set in full'}); only a "
                        "complete run is gated")
    problems += [f"stale: {p}" for p in stale(run, now)]
    pins = pin_problems(baseline["pins"], run["pins"])
    workflows = {}
    for workflow in measure.WORKFLOWS:
        b, r = baseline["workflows"].get(workflow), run["workflows"].get(workflow)
        if b is None or r is None:
            continue
        rows = compare_workflow(workflow, b, r, thresholds[workflow])
        workflows[workflow] = {"rows": rows, "judge": {"baseline": b.get("judge"), "run": r.get("judge")},
                               "tokens": {"baseline": b.get("tokens"), "run": r.get("tokens")}}
    regressions = [(w, row["check"]) for w, entry in workflows.items() for row in entry["rows"] if row["verdict"] == "regressed"]
    invalid = sorted((scope for scope, found in pins.items() if found), key=lambda s: (s != ALL, s))
    return {"problems": problems, "pins": pins, "invalid": invalid, "workflows": workflows,
            "regressions": regressions, "passed": not problems and not invalid and not regressions}


# --- the report ---------------------------------------------------------------------------------------------------

def _of(t: dict[str, int]) -> str:
    decided = t["passed"] + t["failed"]
    return f"{t['passed']} of {decided}" if decided else "none decided"


def _judge(t: dict[str, Any] | None) -> str:
    if not t:
        return "no judge"
    shown = t["judged"] - t["withheld"]
    if t.get("right") is None:
        return f"{t['judged']} read, {t['withheld']} of them sampled texts; no verdict carried"
    return f"{t['right']} right of {shown} shown, {t['withheld']} withheld"


def render(report: dict[str, Any], baseline_name: str, run_name: str) -> str:
    lines = [f"# The gate: {run_name} against {baseline_name}", ""]
    for problem in report["problems"]:
        lines.append(f"- {problem}")
    for scope in sorted(report["pins"], key=lambda s: (s != ALL, s)):
        for problem in report["pins"][scope]:
            lines.append(f"- pins, {scope}: {problem}")
    if report["invalid"]:
        lines += ["", "The baseline is invalid for " + ", ".join(report["invalid"]) + " until a run is accepted "
                  "(python ci/live.py --accept live/<run>.json, after review). The checks below are for that review."]
    lines += ["", "|Workflow |Check |Threshold |Baseline |Run |Lost |Gained |Verdict |", "|---|---|---|---|---|---|---|---|"]
    for workflow, entry in report["workflows"].items():
        for row in entry["rows"]:
            threshold = "not gated" if row["threshold"] is None else row["threshold"]
            lines.append(f"|{workflow} |{row['check']} |{threshold} |{_of(row['baseline'])} |{_of(row['run'])} "
                         f"|{', '.join(row['lost']) or '-'} |{', '.join(row['gained']) or '-'} |{row['verdict']} |")
        if entry["judge"]["baseline"] is not None or entry["judge"]["run"] is not None:
            lines.append(f"|{workflow} |judge |not gated |{_judge(entry['judge']['baseline'])} |{_judge(entry['judge']['run'])} "
                         "|- |- |reported |")
    lines.append("")
    if report["passed"]:
        lines.append("The gate passes: no check lost more cases than its threshold allows, and the baseline holds.")
    else:
        failing = [f"{w} {c}" for w, c in report["regressions"]]
        lines.append("The gate fails: " + "; ".join(
            (["the comparison is unsound"] if report["problems"] else [])
            + (["the baseline is invalid"] if report["invalid"] else [])
            + ([f"regressed: {', '.join(failing)}"] if failing else [])) + ".")
    return "\n".join(lines) + "\n"


def describe_baseline(baseline: dict[str, Any]) -> str:
    """What the baseline holds, per workflow: the run it stands for and the checks that fail in it."""
    source = baseline["source"]
    origin = (f"built from the kept results in {source['results']}" if source["kind"] == "kept"
              else f"accepted from {source['path']} on {source['accepted']}")
    lines = [f"The baseline ({origin}): {source['model']} judged by {source['judge']}.", "",
             "|Workflow |Run |Cases |Checks failing in it |", "|---|---|---|---|"]
    for workflow, entry in baseline["workflows"].items():
        failing = [f"{n} {_of(t)}" for n, t in entry["tally"].items() if t["failed"]]
        lines.append(f"|{workflow} |{entry['run']} |{len(entry['cases'])} |{'; '.join(failing) or 'none'} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    import baseline as baseline_file  # its check rebuilds the baseline from its source

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--thresholds", type=Path, default=THRESHOLDS)
    parser.add_argument("--live", type=Path, default=LIVE, help="the folder of committed live results")
    args = parser.parse_args(argv)
    thresholds, problems = load_thresholds(args.thresholds)
    problems += baseline_file.check(args.baseline)
    if not args.baseline.exists():
        print("\n".join(problems))
        return 1
    baseline = registry.read_json(args.baseline)
    latest = latest_live(args.live)
    if problems:
        print("\n".join(f"- {p}" for p in problems) + "\n")
    if latest is None:
        print(describe_baseline(baseline))
        print("No live run is committed in live/, so there is nothing to compare yet: the first one waits for the "
              "workstation's GPU (python ci/live.py).")
        return 1 if problems else 0
    report = compare(baseline, registry.read_json(latest), thresholds)
    print(render(report, args.baseline.name, latest.name), end="")
    return 0 if report["passed"] and not problems else 1


if __name__ == "__main__":
    sys.exit(main())
