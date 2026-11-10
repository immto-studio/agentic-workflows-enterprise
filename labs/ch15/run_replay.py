"""Replay the deterministic and trajectory layers over every kept run of every workflow, with no model.

Chapter 15, step 2 (companion #13, E-D3, E-D8). The conversion check runs first, so a golden set that
changed since its conversion stops the replay. Then, workflow by workflow, the workflow's own code is
imported once (registry.loaded), and for every run it kept (registry.kept_runs) each case's output is
scored three ways: by the workflow's own scorer, by the deterministic layer, and by the trajectory layer.
Where a layer and the scorer disagree on the checks they share, the case lists the difference, and so it
does where the run's stored verdict is not what its scorer gives today.

It writes results/<date>/replay-<workflow>-<model>.json, one file per workflow and model with every run
of that model in it, and replay-summary.md, the table the README prints. Nothing written holds a time or
a path of this machine, so two runs write the same bytes.

Run (from labs/ch15):  python run_replay.py [--out results/<date>]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True  # import the workflows' code without leaving caches in their folders
HERE = Path(__file__).resolve().parent
for folder in (HERE / "layers", HERE / "cases"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import convert  # noqa: E402
import deterministic  # noqa: E402
import registry  # noqa: E402
import trajectory  # noqa: E402

CODE = ("layers/registry.py", "layers/deterministic.py", "layers/trajectory.py", "cases/convert.py")


def _failing(verdict: dict[str, Any]) -> dict[str, Any]:
    return {name: c["detail"] for name, c in verdict["checks"].items() if c["ok"] is False}


def differences(own: dict[str, Any], det: dict[str, Any], traj: dict[str, Any]) -> list[dict[str, Any]]:
    """Where a layer and the scorer disagree on what they share, and where the stored verdict is stale.

    The deterministic layer shares the scorer's checks on the output; the trajectory layer shares the
    scorer's checks on the calls where there are any (the skeleton's tool_ok, W2's and W3's reads_ok), and
    where there are none, a trajectory failure is a difference of its own."""
    out = []
    if det["pass"] != own["deterministic"]:
        out.append({"layer": "deterministic", "layer_pass": det["pass"], "scorer_pass": own["deterministic"],
                    "checks": _failing(det)})
    share, verdict = own["trajectory"], traj["pass"]
    if verdict is not None and (verdict != share if share is not None else verdict is False):
        out.append({"layer": "trajectory", "layer_pass": verdict, "scorer_pass": share, "checks": _failing(traj)})
    if own.get("stored") is not None and own["stored"] != own["pass"]:
        out.append({"layer": "stored", "layer_pass": own["stored"], "scorer_pass": own["pass"],
                    "checks": {"stored": "the results file holds another verdict than the scorer gives today"}})
    return out


def replay_run(workflow: str, mods: Any, ctx: dict[str, Any], cases: dict[str, dict[str, Any]],
               run: registry.Run) -> dict[str, Any]:
    outputs = registry.outputs(run)
    own = deterministic.own_verdicts(workflow, mods, run, outputs, ctx)
    stored = registry.stored_verdicts(run)
    det = deterministic.check_run(workflow, mods, cases, outputs, ctx)
    traj = trajectory.check_run(workflow, mods, cases, outputs, ctx)
    rows = []
    for cid in det:
        scorer = own[cid] | {"stored": stored.get(cid)}
        rows.append({"id": cid, "scorer": scorer, "deterministic": det[cid], "trajectory": traj[cid],
                     "differences": differences(scorer, det[cid], traj[cid])})
    kept = [r for r in rows if r["trajectory"]["pass"] is not None]
    summary = {
        "cases": len(rows),
        "scorer": sum(r["scorer"]["pass"] for r in rows),
        "deterministic": sum(r["deterministic"]["pass"] for r in rows),
        "trajectory": sum(bool(r["trajectory"]["pass"]) for r in kept) if kept else None,
        "both": sum(r["deterministic"]["pass"] and r["trajectory"]["pass"] is not False for r in rows),
        "differences": sum(len(r["differences"]) for r in rows),
    }
    return {"run": run.label, "folder": run.folder,
            "files": [{"path": f, "sha256": registry.sha256_of(registry.path(f))} for f in run.files],
            "summary": summary, "cases": rows}


def replay(out: Path) -> list[dict[str, Any]]:
    problems = convert.check()
    if problems:
        raise SystemExit("the conversion check failed; nothing replayed:\n" + "\n".join(problems))
    code = [{"path": f"labs/ch15/{c}", "sha256": registry.sha256_of(HERE / c)} for c in CODE]
    out.mkdir(parents=True, exist_ok=True)
    table = []
    for workflow in registry.ORDER:
        spec = registry.WORKFLOWS[workflow]
        cases = {c["id"]: c for c in registry.read_jsonl(registry.CASES / f"{workflow}.jsonl")}
        runs = registry.kept_runs(workflow)
        with registry.loaded(workflow) as mods:
            ctx = deterministic.context(workflow, mods) | trajectory.context(workflow, mods)
            by_model: dict[str, list[dict[str, Any]]] = {}
            for run in runs:
                by_model.setdefault(run.model, []).append(replay_run(workflow, mods, ctx, cases, run))
        for model, replayed in by_model.items():
            document = {
                "workflow": workflow, "name": spec.name, "model": model,
                "set": {"path": f"labs/ch15/cases/{workflow}.jsonl", "version": convert.version(workflow),
                        "cases": len(cases), "source": spec.golden,
                        "source_sha256": registry.sha256_of(registry.path(spec.golden))},
                "scorer": {"path": spec.scorer, "sha256": registry.sha256_of(registry.path(spec.scorer))},
                "code": code,
                "checks": {"deterministic": {name: {"family": f, "how": how, "decides": what}
                                             for name, (f, how, what) in deterministic.CHECKS[workflow].items()},
                           "trajectory": trajectory.CHECKS[workflow],
                           "trajectory_not_kept": trajectory.NOT_KEPT[workflow]},
                "runs": replayed,
            }
            (out / f"replay-{workflow}-{model}.json").write_text(
                json.dumps(document, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
            table += [{"workflow": workflow, "model": model, "run": r["run"], **r["summary"]} for r in replayed]
    (out / "replay-summary.md").write_text(render_table(table), encoding="utf-8", newline="\n")
    return table


def render_table(table: list[dict[str, Any]]) -> str:
    def of(n: int | None, total: int) -> str:
        return "not kept" if n is None else f"{n} of {total}"

    lines = ["|Workflow |Model |Run |Cases |Scorer |Deterministic |Trajectory |Both layers |Differences |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in table:
        lines.append(f"|{r['workflow']} |{r['model']} |{r['run']} |{r['cases']} |{of(r['scorer'], r['cases'])} "
                     f"|{of(r['deterministic'], r['cases'])} |{of(r['trajectory'], r['cases'])} "
                     f"|{of(r['both'], r['cases'])} |{r['differences']} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=HERE / "results" / date.today().isoformat())
    args = parser.parse_args(argv)
    table = replay(args.out)
    print(render_table(table), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
