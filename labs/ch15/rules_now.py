"""The calibration report with the rules' verdicts as the scorers give them now (chapter 15, step 5, E-D5).

labels/sample.json keeps the verdicts it was drawn with, and labels/agreement.py reads the rules' verdict on each
sampled output from it. The scorer fixes of companion #8 and #10 came after the author's labels and moved some of
those verdicts, so this writes the same report with each output's rules verdict on the prose taken from the
scorers as they are now (judge/items.py) and everything else as before: the author's labels, the judge's verdicts,
and the sample's outputs, ids, and judges. Only the rules' columns can differ from what agreement.py prints.

Run (from labs/ch15):  python rules_now.py            print the report
                       python rules_now.py --write    save it as labels/agreement-A.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True  # import the workflows' code without leaving caches in their folders
HERE = Path(__file__).resolve().parent
for folder in (HERE / "layers", HERE / "cases", HERE, HERE / "judge", HERE / "labels"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import agreement  # noqa: E402
import items as itemize  # noqa: E402
import sample as sampling  # noqa: E402

REPORT = HERE / "labels" / "agreement-A.md"


def document(all_items: dict[str, list[itemize.Item]] | None = None) -> dict[str, Any]:
    """sample.json with each output's rules verdict on the prose as the scorers give it now."""
    committed = sampling.load()
    all_items = itemize.build_all() if all_items is None else all_items
    by_key = {i.key: i for its in all_items.values() for i in its}
    entries = []
    for entry in committed["items"]:
        rules = by_key[sampling.key_of(entry)].rules
        entries.append({**entry, "rules": {"pass": rules["pass"], "failing": sorted(rules["failing"]),
                                           "exact": rules["exact"]}})
    return {**committed, "items": entries}


def report(all_items: dict[str, list[itemize.Item]] | None = None) -> str:
    """The author's labels against the judge's verdicts and the rules' verdicts as the scorers give them now."""
    return agreement.report(agreement.LABELS, document(all_items))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--write", action="store_true", help="save the report as labels/agreement-A.md")
    args = parser.parse_args(argv)
    text = report()
    print(text, end="")
    if args.write:
        REPORT.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
