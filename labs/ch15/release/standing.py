"""The release criteria per rung (chapter 15, step 7, E-D11), and where each workflow stands against its own rung.

release/criteria.yaml holds the criteria and the rungs. This prints what the README prints: the rungs of chapter 1's
ladder with the evidence a workflow needs before it climbs to each; each workflow against the rung its manifest
gives it; and the detail behind each cell.

What the lab's results decide is read from them: the controls and the trajectory checks from step 2's replay of the
runs that stand for each workflow on each local model, containment from step 6's red-team results, the approval
criterion from W3's suite, where each test the criteria name must exist, and the judge's calibration from the
author's labels through labels/agreement.py (step 5, E-D5). Two things are states of the project that no result
records, and they are written here as of the date they were last true (TODAY): the CI gate, whose job runs once the
author copies it into .github/workflows/, and the rerun on every model change, whose first live run waits for the
GPU. Read from the repository instead, the author's copy of the job, or an accepted run, would fail the test that
holds this text to the README.

Run (from labs/ch15):  python release/standing.py
"""

from __future__ import annotations

import argparse
import functools
import re
import sys
import textwrap
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
LAB = HERE.parent
for folder in (LAB / "layers", LAB / "cases", LAB, LAB / "labels"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import agreement  # noqa: E402
import deterministic  # noqa: E402
import registry  # noqa: E402
import trajectory  # noqa: E402

CRITERIA = HERE / "criteria.yaml"
RESULTS = LAB / "results" / "2026-11-03"
ORDER = ("controls", "contained", "trajectory", "prose", "approval", "gate", "rerun")
COLUMNS = {"controls": "Controls", "contained": "Planted texts", "trajectory": "Trajectory", "prose": "Prose",
           "approval": "Approval", "gate": "CI gate", "rerun": "Rerun"}
NAMED = {"controls": "controls", "contained": "planted texts", "trajectory": "trajectory checks", "prose": "prose",
         "approval": "approval tests"}
MODELS = {"gpt-oss-20b": "gpt-oss-20b", "gemma4-12b": "Gemma 4 12B"}
MET, NOT_MET, WAITS, PERSON = "met", "not met", "waits", "met by a person"
WIDTH = 115  # the README's prose width
# The states of the project, as of the date given. Update them as they change, and the README with them.
TODAY = {
    "date": "3 November 2026",
    "gate": (WAITS, "the job is labs/ch15/ci/regression.yml, and it gates pull requests once the author copies it "
                    "into .github/workflows/"),
    "rerun": (WAITS, "the live job is built and tested with a fake model (ci/live.py); its first run waits for the "
                     "GPU, and the baseline holds no model digest until a run is accepted"),
}


@functools.lru_cache(maxsize=1)
def _calibration() -> dict[str, agreement.Agreement] | None:
    return agreement.calibration()


def judge_state(workflow: str) -> str:
    """The judge's calibration for one workflow's prose, from the author's labels (step 5, E-D5)."""
    found = _calibration()
    if found is None:
        return "a calibrated judge waits for the author's labels (E-D5)"
    a = found[workflow]
    said = f"the judge agrees with the author's labels on {a.agree} of {a.n} outputs ({100 * a.agree / a.n:.1f} percent)"
    if not a.meets:
        return f"{said}, under E-D5's 90, so the person's reading stays"
    if a.labeled_wrong == 0:
        return f"{said}, which meets E-D5's rule, though the author labeled none of them wrong"
    return f"{said}, which meets E-D5's rule"


def load(path: Path = CRITERIA) -> dict[str, Any]:
    return registry.read_yaml(path)


def needed(criteria: dict[str, Any], rung: int) -> list[str]:
    """What a workflow on this rung needs: every rung's four, and what each rung up to it adds."""
    names = list(criteria["every_rung"])
    for entry in criteria["rungs"]:
        if entry["rung"] <= rung:
            names += entry["adds"]
    return [n for n in ORDER if n in names]


def _replay(workflow: str, model: str, label: str) -> list[dict[str, Any]]:
    document = registry.read_json(RESULTS / f"replay-{workflow}-{model}.json")
    return next(r for r in document["runs"] if r["run"] == label)["cases"]


def _list(items: list[str]) -> str:
    """a; a and b; a, b, and c."""
    if len(items) < 3:
        return " and ".join(items)
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def _failures(rows: list[dict[str, Any]], layer: str, names: list[str]) -> str:
    found: dict[str, list[str]] = {}
    for row in rows:
        for name in names:
            if row[layer]["checks"].get(name, {}).get("ok") is False:
                found.setdefault(name, []).append(row["id"])
    return "; ".join(f"{name} fails on {_list(cases)}" for name, cases in found.items())


def _across(models: list[str], said: dict[str, str], none: str) -> str:
    """What each model's runs show, said once where the models show the same."""
    if len(models) == 1:
        return f"on {MODELS[models[0]]}, the only model its golden set ran on, {said[models[0]] or none}"
    if len(set(said.values())) == 1:
        return f"{said[models[0]] or none}, on each local model"
    return "; ".join(f"on {MODELS[m]}, {said[m] or none}" for m in models)


def status(workflow: str, criterion: str, spec: dict[str, Any]) -> tuple[str, str]:
    """(met, not met, met by a person, or waits; the detail, a clause) for one criterion of one workflow."""
    runs = spec["runs"]
    if criterion in ("controls", "trajectory"):
        layer = "deterministic" if criterion == "controls" else "trajectory"
        names = ([n for n, (family, _, _) in deterministic.CHECKS[workflow].items() if family == "controls"]
                 if criterion == "controls" else list(trajectory.CHECKS[workflow]))
        said = {m: _failures(_replay(workflow, m, label), layer, names) for m, label in runs.items()}
        detail = _across(list(runs), said, f"{_list(names)} hold on every case")
        if not any(said.values()):
            return MET, detail
        if criterion == "trajectory" and "forbidden" not in " ".join(said.values()):
            detail += "; no call was forbidden"
        return NOT_MET, detail
    if criterion == "contained":
        models = [m for m in MODELS if (RESULTS / f"redteam-{workflow}-{m}.json").exists()]
        said, broke = {}, False
        for model in models:
            outputs = registry.read_json(RESULTS / f"redteam-{workflow}-{model}.json")["outputs"]
            by_case: dict[str, list[str]] = {}
            for o in outputs:
                if o["contained"] is not True:
                    by_case.setdefault(o["case"].split("/")[0], []).append(o["variant"])
            said[model] = f"{sum(o['contained'] is True for o in outputs)} of {len(outputs)} outputs contained" + (
                ", and " + "; ".join(f"{_list(v)} on {case}" for case, v in by_case.items()) + " broke a check"
                if by_case else "")
            broke = broke or bool(by_case)
        return (NOT_MET if broke else MET), _across(models, said, "")
    if criterion == "prose":
        return PERSON, f"{spec['reader']}; {judge_state(workflow)}"
    if criterion == "approval":
        missing = [t for t in spec["approval_tests"] if not _test_exists(t)]
        if missing:
            return NOT_MET, "no such test: " + _list(missing)
        return MET, f"{workflow.upper()}'s suite holds " + _list([t.split("::")[1] for t in spec["approval_tests"]])
    return TODAY[criterion]


def _test_exists(test: str) -> bool:
    path, name = test.split("::")
    file = registry.path(path)
    return file.is_file() and re.search(rf"^def {re.escape(name)}\(", file.read_text(encoding="utf-8"), re.MULTILINE) is not None


def standing(criteria: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Each workflow at its manifest's rung, with every criterion that rung needs and its status."""
    criteria = criteria or load()
    out = []
    for workflow, spec in criteria["workflows"].items():
        rung = registry.manifest(workflow)["rung"]
        out.append({"workflow": workflow, "rung": rung,
                    "criteria": {c: status(workflow, c, spec) for c in needed(criteria, rung)}})
    return out


def render(criteria: dict[str, Any] | None = None) -> str:
    criteria = criteria or load()
    defined = criteria["criteria"]
    names = {r["rung"]: r["name"] for r in criteria["rungs"]}
    lines = ["|Rung |What the workflow does there (chapter 1) |Evidence it needs before it climbs there |", "|---|---|---|"]
    for entry in criteria["rungs"]:
        evidence = entry.get("left") or "; ".join(defined[n]["evidence"] for n in needed(criteria, entry["rung"]))
        lines.append(f"|{entry['rung']}, {entry['name']} |{entry['does']} |{evidence} |")
    rows = standing(criteria)
    lines += ["", f"Where each workflow stands against its own rung, {TODAY['date']}:", "",
              "|Workflow |Rung |" + " |".join(COLUMNS[c] for c in ORDER) + " |", "|" + "---|" * (len(ORDER) + 2)]
    for row in rows:
        cells = [row["criteria"][c][0] if c in row["criteria"] else "-" for c in ORDER]
        lines.append(f"|{row['workflow'].upper()} |{row['rung']}, {names[row['rung']]} |" + " |".join(cells) + " |")
    lines.append("")
    for row in rows:
        for criterion in ORDER:
            if criterion in row["criteria"] and criterion not in ("gate", "rerun"):
                state, detail = row["criteria"][criterion]
                lines.append(_bullet(f"{row['workflow'].upper()}'s {NAMED[criterion]}, {state}: {detail}."))
    lines += ["", "Every workflow waits on the last two columns:", "",
              _bullet(f"The CI gate: {TODAY['gate'][1]}."), _bullet(f"The rerun: {TODAY['rerun'][1]}.")]
    return "\n".join(lines) + "\n"


def _bullet(text: str) -> str:
    """A list item wrapped as the README wraps its prose."""
    return textwrap.fill(text, width=WIDTH, initial_indent="- ", subsequent_indent="  ", break_long_words=False,
                         break_on_hyphens=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.parse_args(argv)
    print(render(), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
