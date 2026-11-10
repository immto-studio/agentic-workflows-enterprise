"""The author's answers from the e-reader export into labels-A.jsonl (chapter 15, E-D6 and E-D7 as amended on
3 November 2026).

The author reads labels/export/ch15-labels.epub and sends his answers as text, one per line: the number, R or W
(В or Н, or the words right, wrong, верно, неверно), then an optional note. This script reads them, checks every
number against labels/kindle-key.json, and writes each label through the labeling page's own store, so a label
line has the same shape, labeler "A", and rubric hash as one the page writes. A later answer for a number replaces
an earlier one, in the file as on the page: the last line for an output is its label.

Run from labs/ch15:
  python labels/answers.py answers.txt           check the answers and print what would be written
  python labels/answers.py answers.txt --write   append them to labels/labels-A.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

KEY = HERE / "kindle-key.json"
WORDS = {"r": "right", "right": "right", "в": "right", "верно": "right", "+": "right",
         "w": "wrong", "wrong": "wrong", "н": "wrong", "неверно": "wrong", "-": "wrong"}
LINE = re.compile(r"^\s*(\d{1,3})\s*[.:)]?\s*(right|wrong|верно|неверно|[rwвн+-])(?=\s|$|[.,;:—–-])"
                  r"\s*[.,;:—–-]?\s*(.*?)\s*$", re.IGNORECASE)


def parse(text: str, total: int) -> tuple[dict[int, tuple[str, str]], list[str]]:
    """{number: (label, note)}, the last answer per number winning, and the problems found, by line."""
    answers: dict[int, tuple[str, str]] = {}
    problems = []
    for n, raw in enumerate(text.replace("\r\n", "\n").split("\n"), start=1):
        line = raw.strip()
        if not line:
            continue
        m = LINE.match(line)
        if not m:
            problems.append(f"line {n}: not an answer: {raw!r}")
            continue
        number, word, note = int(m.group(1)), m.group(2).lower(), m.group(3)
        if not 1 <= number <= total:
            problems.append(f"line {n}: no output numbered {number} (1 to {total})")
            continue
        answers[number] = (WORDS[word], note)
    return answers, problems


def main(argv: list[str] | None = None) -> int:
    import page  # noqa: PLC0415  (the lab's code, only when run)

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("answers", type=Path, help="a text file with the author's answers")
    parser.add_argument("--write", action="store_true", help="append the labels to labels/labels-A.jsonl")
    args = parser.parse_args(argv)
    key: dict[str, Any] = json.loads(KEY.read_text(encoding="utf-8"))
    numbers = {int(n): id_ for n, id_ in key["numbers"].items()}
    answers, problems = parse(args.answers.read_text(encoding="utf-8"), len(numbers))
    for p in problems:
        print(p)
    if problems:
        print("Nothing written: fix the lines above first.")
        return 1
    labeling = page.prepare()
    if set(labeling.shown) != set(numbers.values()):
        raise SystemExit("kindle-key.json no longer matches the sample: run labels/export.py again and resend")
    missing = sorted(set(numbers) - set(answers))
    counts = {"right": sum(1 for a in answers.values() if a[0] == "right"),
              "wrong": sum(1 for a in answers.values() if a[0] == "wrong")}
    print(f"{len(answers)} answers: {counts['right']} right, {counts['wrong']} wrong, "
          f"{sum(1 for a in answers.values() if a[1])} with a note; {labeling.done} already in labels-A.jsonl")
    if missing:
        print(f"not answered yet ({len(missing)}): {', '.join(map(str, missing))}")
    if not args.write:
        print("Checked only; --write appends them.")
        return 0
    for number in sorted(answers):
        label, note = answers[number]
        labeling.label({"id": numbers[number], "label": label, "note": note})
    print(f"appended {len(answers)} labels; {labeling.done} of {labeling.total} outputs now labeled")
    return 0


if __name__ == "__main__":
    sys.exit(main())
