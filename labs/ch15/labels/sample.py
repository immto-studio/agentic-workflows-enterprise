"""The sample the author labels (chapter 15, step 4, E-D5): about 140 outputs, chosen by a seed.

The pool is every output a judge read as another model's (items.assign's cross slice), so each sampled output
has a verdict from a model that did not write it. The self and padded slices stay out, and so does every text no
model wrote. Outputs whose text a judge would read word for word twice are one text to label: W5's bodies repeat
across nights and runs, so the 494 cross-judged outputs hold 334 texts, and a person who read the same text twice
would count one judgement as two. The first copy in key order stands for the others, and `copies` says how many
there are.

The pick, in this order:

- An equal share of SIZE for each workflow, none larger than the texts it has (`even`). W3 and W4 have fewer
  texts than a fifth of 140 and give all of theirs; the other three share the rest, the odd one going to the
  workflow with the most texts.
- In each workflow the known outputs come first, whatever the draw: every output a workflow's README records as
  wrong (items.KNOWN), which holds W5's excused tag listed as present, W5's snapshot called "attached", and W1's
  restated planted claims; and the outputs step 3 left to the labels, gpt-oss-20b's refusals on w2-14 and the
  out-of-scope w3-10 (SETTLE).
- The rest of the workflow's share is drawn by the seed from its other texts, split between the ones the rules
  pass and the ones they fail in proportion to how many of each it has (`proportional`). The rules' verdict is
  the deterministic layer's on the prose the label reads (items.RULES), the one a label can be set against.
- An output both judges read, which in W1 is Nova Lite's, gets one of them, alternately in a seeded order, so
  that every sampled output has one cross-judge verdict.

Nothing here reads the judge's verdicts: the sample comes from the outputs and the rules' verdicts, so a run of
the judge leaves it as it was. sample.json is for the analysis (agreement.py); the labeling page never shows its
verdict fields.

Run from labs/ch15:
  python labels/sample.py           draw the sample and write labels/sample.json
  python labels/sample.py --check   exit 1 if labels/sample.json is not what the seed draws now
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True  # import the workflows' code without leaving caches in their folders
HERE = Path(__file__).resolve().parent
LAB = HERE.parent
for folder in (LAB / "layers", LAB / "cases", LAB, LAB / "judge", HERE):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import items as itemize  # noqa: E402
import judge as judging  # noqa: E402
import registry  # noqa: E402

SIZE = 140  # E-D5: chapter 5's "about 140 labeled answers"
SEED = "chapter 15, step 4"
SAMPLE = HERE / "sample.json"
LABELS = HERE / "labels-A.jsonl"  # the author's labels (page.py writes them)
STRATA = ("pass", "fail", "none")  # the rules' verdict on the prose; "none" where no rule reads it (w3-10)
# The outputs step 3 left to the labels, beside items.KNOWN's wrong readings: by workflow, writer, and case.
SETTLE = {
    ("w2", "gpt-oss-20b", "w2-14"): "W2: a refusal W2's scorer fails on its wording rule and W2's README calls "
                                    "correct; step 3 left it to the labels",
    ("w3", "gpt-oss-20b", "w3-10"): "W3: the out-of-scope refusal, which no rule reads; step 3 left it to the labels",
}


@dataclass(frozen=True)
class Unit:
    """One text to label: the output that stands for it, and what the pick needs to know about it."""
    item: itemize.Item  # the first of the text's copies in key order
    readers: tuple[str, ...]  # the judges that read it as another model's output
    copies: int  # the cross-judged outputs with this text, itself included
    known: tuple[str, ...]  # why it is in the sample whatever the draw; empty for a drawn text

    @property
    def workflow(self) -> str:
        return self.item.workflow

    @property
    def stratum(self) -> str:
        return stratum(self.item)


def stratum(item: itemize.Item) -> str:
    verdict = item.rules["pass"]
    return "none" if verdict is None else "pass" if verdict else "fail"


def text_key(item: itemize.Item) -> str:
    """What makes two outputs one text to label: the workflow, the rubric's conditions, the reference, and the
    output, which together are everything the judge's request holds that varies by output."""
    blob = json.dumps([item.workflow, list(item.conditions), item.reference, item.output], ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def item_id(key: tuple[str, ...]) -> str:
    """A sampled output's id: its workflow and eight hex characters of its key's hash, which say nothing of the
    model, the run, or a verdict."""
    return f"{key[0]}-{hashlib.sha256(json.dumps(list(key)).encode('utf-8')).hexdigest()[:8]}"


def key_of(entry: dict[str, Any]) -> tuple[str, str, str, str, str]:
    """A sample entry's Item key: workflow, the run's model, the run, the case, and W5's finding."""
    return (entry["workflow"], entry["run_model"], entry["run"], entry["case"], entry["part"])


# --- the pool --------------------------------------------------------------------------------------------------

def known(all_items: dict[str, list[itemize.Item]]) -> dict[tuple, list[str]]:
    """The known outputs by key, with why each is one: the wrong readings of items.KNOWN, and SETTLE's."""
    reasons: dict[tuple, list[str]] = defaultdict(list)
    for entry, item in itemize.known(all_items):
        if entry["says"] == "wrong":
            reasons[item.key].append(entry["readme"])
    for workflow, its in all_items.items():
        for item in its:
            why = SETTLE.get((workflow, item.author, item.case))
            if why and item.judged:
                reasons[item.key].append(why)
    return reasons


def units(all_items: dict[str, list[itemize.Item]]) -> list[Unit]:
    """Every text a judge read as another model's output, once, in key order."""
    readers: dict[tuple, set[str]] = defaultdict(set)
    for judge in itemize.JUDGES:
        for slice_, item in itemize.assign(all_items, judge):
            if slice_ == "cross":
                readers[item.key].add(judge)
    by_key = {i.key: i for its in all_items.values() for i in its}
    reasons = known(all_items)
    groups: dict[str, list[itemize.Item]] = defaultdict(list)
    for key in sorted(readers):
        groups[text_key(by_key[key])].append(by_key[key])
    out = []
    for members in groups.values():
        first = members[0]
        if len({stratum(m) for m in members}) > 1:
            raise ValueError(f"{first.key}: the rules give one text two verdicts")
        why = tuple(sorted({r for m in members for r in reasons.get(m.key, [])}))
        out.append(Unit(first, tuple(sorted(readers[first.key])), len(members), why))
    return sorted(out, key=lambda u: u.item.key)


# --- the pick --------------------------------------------------------------------------------------------------

def even(sizes: dict[str, int], total: int) -> dict[str, int]:
    """Equal shares of total, none larger than its size: one at a time to the smallest share, a tie going to the
    larger size, then to the name that sorts first."""
    out = dict.fromkeys(sizes, 0)
    for _ in range(min(total, sum(sizes.values()))):
        name = min((n for n in out if out[n] < sizes[n]), key=lambda n: (out[n], -sizes[n], n))
        out[name] += 1
    return out


def proportional(sizes: dict[str, int], total: int) -> dict[str, int]:
    """total split in proportion to sizes by the largest remainder, a tie going to the larger size."""
    whole = sum(sizes.values())
    total = min(total, whole)
    if not whole:
        return dict.fromkeys(sizes, 0)
    out = {n: total * s // whole for n, s in sizes.items()}
    order = sorted(sizes, key=lambda n: (-(total * sizes[n] % whole), -sizes[n], n))
    for n in order[:total - sum(out.values())]:
        out[n] += 1
    return out


def draw(all_units: list[Unit], size: int = SIZE, seed: str = SEED) -> tuple[list[Unit], dict[str, Any]]:
    """The sampled texts and the allocation behind them, by workflow."""
    by_workflow: dict[str, list[Unit]] = defaultdict(list)
    for unit in all_units:
        by_workflow[unit.workflow].append(unit)
    shares = even({w: len(by_workflow[w]) for w in judging.JUDGED}, size)
    picked: list[Unit] = []
    plan: dict[str, Any] = {}
    for workflow in judging.JUDGED:
        units_ = by_workflow[workflow]
        certain = [u for u in units_ if u.known]
        rest = [u for u in units_ if not u.known]
        if len(certain) > shares[workflow]:
            raise ValueError(f"{workflow}: {len(certain)} known outputs and a share of {shares[workflow]}")
        sizes = {s: sum(u.stratum == s for u in rest) for s in STRATA}
        quotas = proportional(sizes, shares[workflow] - len(certain))
        drawn = []
        for s in STRATA:
            pool = [u for u in rest if u.stratum == s]
            drawn += random.Random(f"{seed} {workflow} {s}").sample(pool, quotas[s])
        picked += certain + drawn
        plan[workflow] = {
            "texts": len(units_), "outputs": sum(u.copies for u in units_),
            "texts_by_rules": {s: sum(u.stratum == s for u in units_) for s in STRATA},
            "share": shares[workflow],
            "known": {s: sum(u.stratum == s for u in certain) for s in STRATA},
            "drawn": quotas, "drawn_from": sizes,
        }
    return picked, plan


def judges(picked: list[Unit], seed: str = SEED) -> dict[tuple, str]:
    """One cross-judge for each sampled output: its only reader, or, where both judges read it, the two in turn
    over a seeded order."""
    out = {u.item.key: u.readers[0] for u in picked if len(u.readers) == 1}
    both = sorted((u for u in picked if len(u.readers) > 1), key=lambda u: u.item.key)
    random.Random(f"{seed} judges").shuffle(both)
    for n, unit in enumerate(both):
        out[unit.item.key] = itemize.JUDGES[n % len(itemize.JUDGES)]
    return out


def build(all_items: dict[str, list[itemize.Item]] | None = None, size: int = SIZE,
          seed: str = SEED) -> dict[str, Any]:
    """sample.json's document."""
    all_items = itemize.build_all() if all_items is None else all_items
    everything = units(all_items)
    picked, plan = draw(everything, size, seed)
    judge_of = judges(picked, seed)
    entries = []
    for unit in picked:
        item = unit.item
        entries.append({
            "id": item_id(item.key), "workflow": item.workflow, "case": item.case, "part": item.part,
            "run": item.run, "run_model": item.model, "model": item.author, "judge": judge_of[item.key],
            "read_by": list(unit.readers), "data_class": item.data_class,
            "rules": {"pass": item.rules["pass"], "failing": sorted(item.rules["failing"]),
                      "exact": item.rules["exact"]},
            "verdicts": item.verdicts, "stratum": unit.stratum,
            "pick": "known" if unit.known else "drawn", "known": list(unit.known), "copies": unit.copies,
        })
    ids = [e["id"] for e in entries]
    if len(set(ids)) != len(ids):
        raise ValueError("two sampled outputs share an id")
    pool = Counter(u.workflow for u in everything)
    return {
        "about": "Chapter 15, step 4 (E-D5): the outputs the author labels, drawn by labels/sample.py. For the "
                 "analysis only: the labeling page never shows the verdict fields.",
        "seed": seed, "size": len(entries),
        "pool": {"outputs": sum(u.copies for u in everything), "texts": len(everything),
                 "texts_by_workflow": {w: pool[w] for w in judging.JUDGED}},
        "allocation": plan,
        "items": sorted(entries, key=lambda e: (e["workflow"], key_of(e))),
    }


def dump(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=1, ensure_ascii=False) + "\n"


# --- what the page and the analysis read -----------------------------------------------------------------------

def load(path: Path = SAMPLE) -> dict[str, Any]:
    return registry.read_json(path)


def results_folder() -> Path:
    """The newest results folder that holds the judge's result files: the judge's current verdicts."""
    found = [p for p in sorted((LAB / "results").iterdir()) if p.is_dir() and list(p.glob("judge-w*-*.json"))]
    if not found:
        raise FileNotFoundError("no results folder holds the judge's result files")
    return found[-1]


def judge_results(folder: Path) -> dict[tuple[str, str], dict[str, Any]]:
    """The judge's result files in a folder, by workflow and judge."""
    out = {}
    for path in sorted(folder.glob("judge-w*-*.json")):
        doc = registry.read_json(path)
        out[(doc["workflow"], doc["judge"])] = doc
    return out


def cross_rows(docs: dict[tuple[str, str], dict[str, Any]]) -> dict[tuple, dict[str, Any]]:
    """Each cross-judged row of the judge's results, by judge and Item key."""
    return {(d["judge"], (d["workflow"], r["model"], r["run"], r["case"], r["part"])): r
            for d in docs.values() for r in d["items"] if r["slice"] == "cross"}


def rubric_sha256(workflow: str) -> str:
    """The rubric file's hash as every result records it (CRLF read as LF)."""
    return registry.sha256_of(judging.RUBRICS / f"{workflow}.yaml")


def read_labels(path: Path, ids: set[str] | None = None) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """A label file: the last line for each id, which is its label, and every line in order. Refused if a line is
    not JSON, has no label of the two, or names an output the sample doesn't hold."""
    lines: list[dict[str, Any]] = []
    if path.exists():
        for n, text in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not text.strip():
                continue
            try:
                line = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name}, line {n}: not a JSON line ({exc.msg})") from exc
            if not isinstance(line, dict) or line.get("label") not in judging.VERDICTS:
                raise ValueError(f"{path.name}, line {n}: no label, or one that is not right or wrong")
            if ids is not None and line.get("id") not in ids:
                raise ValueError(f"{path.name}, line {n}: {line.get('id')!r} is not in the sample")
            lines.append(line)
    return {line["id"]: line for line in lines}, lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if sample.json is not what the seed draws now")
    parser.add_argument("--force", action="store_true", help="write sample.json even though labels-A.jsonl exists")
    args = parser.parse_args(argv)
    document = build()
    text = dump(document)
    if args.check:
        same = SAMPLE.exists() and SAMPLE.read_text(encoding="utf-8").replace("\r\n", "\n") == text
        print("sample.json is what the seed draws" if same else "sample.json differs from what the seed draws now")
        return 0 if same else 1
    if LABELS.exists() and not args.force:
        raise SystemExit(f"{LABELS.name} exists: a new sample would leave its labels without their outputs; "
                         "--force writes it anyway")
    SAMPLE.write_text(text, encoding="utf-8", newline="\n")
    counts = Counter((e["workflow"], e["pick"], e["stratum"]) for e in document["items"])
    for workflow in judging.JUDGED:
        print(workflow, ", ".join(f"{pick} {s} {n}" for (w, pick, s), n in sorted(counts.items()) if w == workflow))
    print(f"wrote {registry.rel(SAMPLE)}: {document['size']} outputs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
