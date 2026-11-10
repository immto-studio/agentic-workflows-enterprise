"""Count the typographic characters in the golden-set answers a run stored, by kind and by place.

run_local_golden.py flags an answer as typographic when it holds any of the characters it
normalizes, anywhere. For operations the question is narrower: did the model put a look-alike
character inside a name an engineer will copy into a command? This report answers both from the
stored results, without the model.

Run:  python typography_report.py results/2026-10-29
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

LOOKALIKES = {
    "‐": "U+2010 hyphen",
    "‑": "U+2011 non-breaking hyphen",
    "–": "U+2013 en dash",
    "—": "U+2014 em dash",
    "‘": "U+2018 left single quote",
    "’": "U+2019 right single quote",
    "“": "U+201C left double quote",
    "”": "U+201D right double quote",
    " ": "U+00A0 no-break space",
    " ": "U+202F narrow no-break space",
}
# A service or pod name with a look-alike hyphen inside it, e.g. claims<U+2011>api.
NAME_WITH_LOOKALIKE = re.compile(r"[a-z0-9]+(?:[‐‑][a-z0-9]+)+")


def report(results_dir: Path) -> dict:
    out = {}
    for path in sorted(results_dir.glob("golden-*.json")):
        answers = [r["answer"] for r in json.loads(path.read_text(encoding="utf-8"))["results"]]
        flagged = [r for r in json.loads(path.read_text(encoding="utf-8"))["results"]
                   if str(r.get("typographic")) == "True"]
        out[path.stem.removeprefix("golden-")] = {
            "answers": len(answers),
            "flagged_by_scorer": len(flagged),
            "lookalike_hyphen_inside_a_name": sum(1 for a in answers if NAME_WITH_LOOKALIKE.search(a)),
            "answers_with": {name: sum(1 for a in answers if ch in a)
                             for ch, name in LOOKALIKES.items() if any(ch in a for a in answers)},
        }
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("results", type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(report(args.results), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
