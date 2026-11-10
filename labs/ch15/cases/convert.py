"""The six golden sets in one case format, converted from their files and never retyped (E-D2).

Chapter 15, step 2. One JSON Lines file per set under cases/: chapter 5's skeleton, whose kept runs are
chapter 9's on two local models, and W1 to W5. Each set is read with its workflow's own loader where one
exists (chapter 5's load_cases, W3's load_incidents, W4's load_changes, W5's load_nights) and with
yaml.safe_load where the scorer reads it that way (W1, W2). Every case has the same fields:

  id            the set's id; W1's adds the persona, because W1's scorer asks each access question twice,
                as the on-call engineer and as a member of the page's group (25 cases from 20 questions)
  workflow      skeleton, w1, w2, w3, w4, w5
  data_class    the class a call carrying the case needs: the case's own `class` where the set has one
                (W3), else the manifest's data_class_max
  input         what the workflow is given: a question and a persona, a change, or a night
  expected      what the set expects, under the set's own names, except that the skeleton's expected call
                and W3's step are `tool_calls`, and W4's expected_class and expected_flags are `class`
                and `flags`; a prose expectation is `answer`
  negative      refusal (the right output is the workflow's refusal), trap (the set's trap value), and
                planted (the planted text, or the patterns the set gives for it)
  owner         the manifest's owner
  source        the golden file, and source_sha256 its hash
  derived_from  the other files a field came from, with their hashes: the manifest (owner, data class),
                and for W1's five member cases W1's scorer, whose MEMBER_OF names the member who asks

`scorer_case` turns a converted case back into the shape the workflow's scorer reads; the layers call
the scorers with it, and a test checks that it gives back every entry of every golden file.

Run (from labs/ch15):  python cases/convert.py            write the six files
                       python cases/convert.py --check    exit 1 if a source changed since the conversion
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True  # import the workflows' code without leaving caches in their folders
HERE = Path(__file__).resolve().parent
if str(HERE.parent / "layers") not in sys.path:
    sys.path.insert(0, str(HERE.parent / "layers"))

import registry  # noqa: E402

FIELDS = ("id", "workflow", "data_class", "input", "expected", "negative", "owner", "source", "source_sha256",
          "derived_from")
ONCALL = "oncall.engineer"  # the persona every set names unless a case names another
W2_REFUSING = ("hidden", "scope", "empty")  # W2's scorer: these traps end in the fixed refusal
W3_REFUSING = ("hidden", "scope")  # W3 inherits W2's refusal; its other traps end in "propose nothing"


def _source(relative: str) -> dict[str, str]:
    return {"path": relative, "sha256": registry.sha256_of(registry.path(relative))}


def _case(workflow: str, id: str, data_class: str, input: dict, expected: dict, negative: dict,
          derived: list[str]) -> dict[str, Any]:
    spec = registry.WORKFLOWS[workflow]
    owner = registry.manifest(workflow)["owner"]
    golden = _source(spec.golden)
    return {"id": id, "workflow": workflow, "data_class": data_class, "input": input, "expected": expected,
            "negative": negative, "owner": owner, "source": golden["path"], "source_sha256": golden["sha256"],
            "derived_from": [_source(spec.manifest)] + [_source(d) for d in derived]}


def _attribute(folders: tuple[str, ...], module: str, name: str) -> Any:
    """A constant of a workflow's module, imported under the workflow's own sys.path."""
    with registry.isolated(folders):
        return getattr(importlib.import_module(module), name)


def _call(folders: tuple[str, ...], module: str, function: str, *args: Any) -> Any:
    """A workflow's own loader, imported and called under the workflow's own sys.path."""
    with registry.isolated(folders):
        return getattr(importlib.import_module(module), function)(*args)


# --- one converter per set ---------------------------------------------------------------------------------

def _skeleton() -> list[dict[str, Any]]:
    source = registry.path(registry.WORKFLOWS["skeleton"].golden)
    data_class = registry.manifest("skeleton")["data_class_max"]
    out = []
    for c in _call(("labs/ch05/golden",), "run_golden", "load_cases", source):
        expect = c["expect"]
        calls = [{"tool": expect["tool"], "args": expect.get("args", {})}] if expect.get("tool") else []
        out.append(_case("skeleton", c["id"], data_class, {"question": c["question"]},
                         {"tool_calls": calls, "answer": expect["answer"]},
                         {"refusal": not calls, "trap": None, "planted": None}, []))
    return out


def _w1() -> list[dict[str, Any]]:
    spec = registry.WORKFLOWS["w1"]
    member_of = _attribute(spec.path, "answer_eval", "MEMBER_OF")
    golden = registry.read_yaml(registry.path(spec.golden))
    data_class = registry.manifest("w1")["data_class_max"]
    # The scorer's order: every question as the on-call engineer, then each access question as a member.
    asked = [(q, ONCALL, q["trap"] == "access") for q in golden]
    asked += [(q, member_of[q["required_access_group"]], False) for q in golden if q["trap"] == "access"]
    out = []
    for q, persona, denied in asked:
        expected = {"answer": q["expected_answer"], "source_document": q["source_document"]}
        if "stale_document" in q:
            expected["stale_document"] = q["stale_document"]
        expected |= {"required_access_group": q["required_access_group"], "evidence": q["evidence"]}
        out.append(_case("w1", f"{q['id']}/{persona}", data_class, {"question": q["question"], "persona": persona},
                         expected, {"refusal": denied, "trap": q["trap"], "planted": None},
                         [] if persona == ONCALL else [spec.scorer]))
    return out


def _w2() -> list[dict[str, Any]]:
    golden = registry.read_yaml(registry.path(registry.WORKFLOWS["w2"].golden))
    data_class = registry.manifest("w2")["data_class_max"]
    out = []
    for q in golden:
        expected = {"answer": q["expected"], "facts": q.get("facts", []), "reads": q.get("reads", [])}
        if "reads_allowed" in q:
            expected["reads_allowed"] = q["reads_allowed"]
        out.append(_case("w2", q["id"], data_class, {"question": q["question"], "persona": q.get("persona", ONCALL)},
                         expected, {"refusal": q["trap"] in W2_REFUSING, "trap": q["trap"],
                                    "planted": q.get("planted")}, []))
    return out


def _w3() -> list[dict[str, Any]]:
    spec = registry.WORKFLOWS["w3"]
    out = []
    for c in _call(spec.path, "score", "load_incidents", registry.path(spec.golden)):
        expected = {"answer": c["expected"], "facts": c.get("facts", []),
                    "tool_calls": [c["step"]] if c.get("step") else [], "runbook": c.get("runbook"),
                    "reads": c.get("reads", [])}
        out.append(_case("w3", c["id"], c["class"], {"question": c["question"], "persona": c.get("persona", ONCALL)},
                         expected, {"refusal": c["trap"] in W3_REFUSING, "trap": c["trap"],
                                    "planted": c.get("planted")}, []))
    return out


def _w4() -> list[dict[str, Any]]:
    spec = registry.WORKFLOWS["w4"]
    data_class = registry.manifest("w4")["data_class_max"]
    return [_case("w4", c["id"], data_class, {"change_ref": c["change_ref"]},
                  {"class": c["expected_class"], "flags": c["expected_flags"]},
                  {"refusal": False, "trap": c["trap"], "planted": None}, [])
            for c in _call(spec.path, "score", "load_changes", registry.path(spec.golden))]


def _w5() -> list[dict[str, Any]]:
    spec = registry.WORKFLOWS["w5"]
    nights = _call(spec.path, "score", "load_nights", registry.path(spec.golden))
    data_class = registry.manifest("w5")["data_class_max"]
    # The golden file lists the four plants once, under night-1, and checks them on every night.
    plants = [p for n in nights for p in (n["expected"].get("plants") or [])]
    return [_case("w5", n["id"], data_class,
                  {"date": n["date"], "trigger": n["trigger"], "workspaces": n["workspaces"], "before": n["before"]},
                  {k: v for k, v in n["expected"].items() if k != "plants"},
                  {"refusal": False, "trap": None, "planted": plants}, [])
            for n in nights]


CONVERTERS = {"skeleton": _skeleton, "w1": _w1, "w2": _w2, "w3": _w3, "w4": _w4, "w5": _w5}


def convert(workflow: str) -> list[dict[str, Any]]:
    cases = CONVERTERS[workflow]()
    ids = [c["id"] for c in cases]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{workflow}: duplicate case ids")
    return cases


# --- back to the scorer's shape -----------------------------------------------------------------------------

def scorer_case(case: dict[str, Any]) -> dict[str, Any]:
    """The case in the shape the workflow's own scorer reads (W1's: the question and whether it is denied)."""
    workflow, i, e, n = case["workflow"], case["input"], case["expected"], case["negative"]
    if workflow == "skeleton":
        call = e["tool_calls"][0] if e["tool_calls"] else None
        expect = {"tool": call["tool"], "args": call["args"]} if call else {"tool": None}
        return {"id": case["id"], "question": i["question"], "expect": expect | {"answer": e["answer"]}}
    if workflow == "w1":
        q = {"id": case["id"].split("/")[0], "question": i["question"], "expected_answer": e["answer"],
             "source_document": e["source_document"]}
        if "stale_document" in e:
            q["stale_document"] = e["stale_document"]
        q |= {"required_access_group": e["required_access_group"], "trap": n["trap"], "evidence": e["evidence"]}
        return {"question": q, "denied": n["refusal"]}
    if workflow == "w2":
        q = {"id": case["id"], "question": i["question"], "persona": i["persona"], "expected": e["answer"],
             "facts": e["facts"], "reads": e["reads"]}
        if "reads_allowed" in e:
            q["reads_allowed"] = e["reads_allowed"]
        q["trap"] = n["trap"]
        if n["planted"] is not None:
            q["planted"] = n["planted"]
        return q
    if workflow == "w3":
        q = {"id": case["id"], "question": i["question"], "persona": i["persona"], "expected": e["answer"],
             "facts": e["facts"], "runbook": e["runbook"], "step": e["tool_calls"][0] if e["tool_calls"] else None,
             "trap": n["trap"]}
        if n["planted"] is not None:
            q["planted"] = n["planted"]
        return q | {"reads": e["reads"], "class": case["data_class"]}
    if workflow == "w4":
        return {"id": case["id"], "change_ref": i["change_ref"], "expected_class": e["class"], "trap": n["trap"],
                "expected_flags": e["flags"]}
    return {"id": case["id"], "date": i["date"], "trigger": i["trigger"], "workspaces": i["workspaces"],
            "before": i["before"], "expected": {**e, "plants": n["planted"]}}


# --- the files and the check ----------------------------------------------------------------------------------

def render(cases: list[dict[str, Any]]) -> str:
    return "".join(json.dumps({k: c[k] for k in FIELDS}, ensure_ascii=False) + "\n" for c in cases)


def write(workflow: str, folder: Path = registry.CASES) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{workflow}.jsonl"
    out.write_text(render(convert(workflow)), encoding="utf-8", newline="\n")
    return out


def check(folder: Path = registry.CASES, workflows: tuple[str, ...] = registry.ORDER) -> list[str]:
    """What no longer matches: a source whose hash changed since the conversion, or a converted file that a
    fresh conversion of unchanged sources would not write (the file or the converter was edited)."""
    problems = []
    for workflow in workflows:
        file = folder / f"{workflow}.jsonl"
        if not file.exists():
            problems.append(f"{workflow}: {file.name} is missing; run cases/convert.py")
            continue
        recorded: dict[str, str] = {}
        for case in registry.read_jsonl(file):
            for source in [{"path": case["source"], "sha256": case["source_sha256"]}] + case["derived_from"]:
                recorded.setdefault(source["path"], source["sha256"])
        changed = []
        for relative, sha in sorted(recorded.items()):
            where = registry.path(relative)
            now = registry.sha256_of(where) if where.exists() else "missing"
            if now != sha:
                changed.append(f"{workflow}: {relative} changed since the conversion "
                               f"(recorded {sha[:12]}, now {now[:12]}); convert again and review the diff")
        problems += changed
        if not changed:
            text = file.read_text(encoding="utf-8").replace("\r\n", "\n")
            if text != render(convert(workflow)):
                problems.append(f"{workflow}: {file.name} differs from a fresh conversion of its sources")
    return problems


def version(workflow: str, folder: Path = registry.CASES) -> str:
    """A set's version: the hash of its converted file."""
    return registry.sha256_of(folder / f"{workflow}.jsonl")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if a converted set no longer matches its sources")
    parser.add_argument("--out", type=Path, default=registry.CASES)
    args = parser.parse_args(argv)
    if args.check:
        problems = check(args.out)
        print("\n".join(problems) if problems else "every converted set matches its sources")
        return 1 if problems else 0
    for workflow in registry.ORDER:
        out = write(workflow, args.out)
        print(f"{out.name}: {len(registry.read_jsonl(out))} cases, version {version(workflow, args.out)[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
