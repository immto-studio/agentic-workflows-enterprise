"""Synthetic labels (chapter 15, step 4), so that agreement.py runs before a person's labels exist.

Each sampled output the rules read gets the rules' verdict on its prose as its label, and a seeded SHARE of them
gets the other label. The rules' agreement with these labels is therefore 1 - SHARE by construction, which the
tests check through agreement.py. CORRECTED outputs also get a first line with the other label, early in the file,
that a later line for the same output replaces, as a correction on the page does. w3-10, which no rule reads, gets
no label, so the file also exercises a sample that is not labeled throughout.

The labels are marked synthetic in the file's path (labels/synthetic/labels-S.jsonl), in every line (labeler "S",
"synthetic": true, a note that starts with "synthetic"), and in everything agreement.py computes from them. No
person made them, and the chapter prints no number from them.

Run from labs/ch15:
  python labels/synthetic.py           write labels/synthetic/labels-S.jsonl
  python labels/synthetic.py --check   exit 1 if the file is not what this script writes now
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
LAB = HERE.parent
for folder in (LAB / "layers", LAB / "cases", LAB, LAB / "judge", HERE):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import judge as judging  # noqa: E402
import registry  # noqa: E402
import sample as sampling  # noqa: E402

LABELER = "S"
PATH = HERE / "synthetic" / f"labels-{LABELER}.jsonl"
SEED = "chapter 15, step 4: synthetic labels"
SHARE = 0.10  # the share of the rules' verdicts flipped
CORRECTED = 3  # outputs whose first label a later line corrects
START = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)  # the lines' times: fixed, one second apart


def flipped_count(n: int) -> int:
    """SHARE of n, rounded half up: 14 of the 139 outputs the rules read."""
    return int(SHARE * n + 0.5)


def _other(label: str) -> str:
    return "wrong" if label == "right" else "right"


def build(document: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """The file's lines, in order."""
    document = sampling.load() if document is None else document
    entries = sorted((e for e in document["items"] if e["rules"]["pass"] is not None), key=lambda e: e["id"])
    ids = [e["id"] for e in entries]
    flipped = set(random.Random(f"{SEED} flipped").sample(ids, flipped_count(len(ids))))
    corrected = set(random.Random(f"{SEED} corrected").sample(ids, CORRECTED))
    hashes = {w: sampling.rubric_sha256(w) for w in judging.JUDGED}
    lines: list[dict[str, Any]] = []

    def add(entry: dict[str, Any], label: str, note: str) -> None:
        time = (START + timedelta(seconds=len(lines))).strftime("%Y-%m-%dT%H:%M:%SZ")
        lines.append({"id": entry["id"], "label": label, "note": note, "time": time,
                      "rubric_sha256": hashes[entry["workflow"]], "labeler": LABELER, "synthetic": True})

    final = {}
    for e in entries:
        rules = "right" if e["rules"]["pass"] else "wrong"
        final[e["id"]] = (_other(rules), "synthetic: the rules' verdict, flipped") if e["id"] in flipped else \
            (rules, "synthetic: the rules' verdict")
        if e["id"] in corrected:
            add(e, _other(final[e["id"]][0]), "synthetic: a first label, which a later line for this output corrects")
        else:
            add(e, *final[e["id"]])
    for e in entries:  # the corrections, after every other label, as a labeler who went back writes them
        if e["id"] in corrected:
            add(e, *final[e["id"]])
    return lines


def dump(lines: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if the file is not what this script writes now")
    args = parser.parse_args(argv)
    text = dump(build())
    if args.check:
        same = PATH.exists() and PATH.read_text(encoding="utf-8").replace("\r\n", "\n") == text
        print(f"{PATH.name} is what synthetic.py writes" if same else f"{PATH.name} differs from what synthetic.py writes")
        return 0 if same else 1
    PATH.parent.mkdir(exist_ok=True)
    PATH.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {registry.rel(PATH)}: {text.count(chr(10))} synthetic lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
