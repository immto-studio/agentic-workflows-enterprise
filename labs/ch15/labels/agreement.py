"""The judge's verdicts, and the rules', set against a person's labels (chapter 15, step 4, E-D5).

`python labels/agreement.py [label file]` reads the label file (labels/labels-A.jsonl unless another is named), the
sample (labels/sample.json), and the judge's current results (the newest results folder that holds them), and
prints, for the judge's verdicts and then for the rules' verdicts on the same prose:

- percent agreement with the labels, its 95 percent Wilson interval, and Cohen's kappa, beside the counts of
  "wrong": per workflow with E-D5's trust rule beside each (at least 90 percent agreement), and over the whole
  sample, its drawn and its known outputs apart, and each judge's outputs;
- precision and recall on "wrong", each with its interval;
- how the labels fall where the judge and the rules agree and where they differ, which is what the judge adds;
- every output where the judge and the label differ, with the judge's reason and the person's note.

The formulas are the fact sheet's (section 8.2). Kappa is (p_o - p_e) / (1 - p_e), with p_e = a*b + (1 - a)*(1 - b)
for two raters whose shares of "wrong" are a and b; here the two raters are the person and the judge (or the
rules), and kappa says nothing of whether the labels themselves are right. The interval is the Wilson score
interval as NIST's handbook gives it, with z = 1.959964.

Each label must have been made against the rubric behind the judge's verdict on that output, by the hashes, and a
label file that does not is refused. A file whose lines are synthetic (synthetic.py) gives a report marked
synthetic at its top, in every heading, and at its end; a file that mixes synthetic lines with others is refused.
`--write` saves the report beside the label file as agreement-<labeler>.md. A W1 reason can quote a Restricted
page (W1-D26), so a report whose disagreements hold a W1 row is Restricted data, as W1's result files are.
"""

from __future__ import annotations

import argparse
import math
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import NormalDist
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

Z = NormalDist().inv_cdf(0.975)  # 1.959964, the 95 percent point the fact sheet uses
TRUST = 0.90  # E-D5: a judge is trusted for a workflow's prose at 90 percent agreement or more
LABELS = HERE / "labels-A.jsonl"
SYNTHETIC = ("SYNTHETIC LABELS: {name} holds labels/synthetic.py's labels, the rules' verdicts with a seeded share "
             "flipped. No person made them, every number in this report is synthetic, and the chapter prints none "
             "of them.")


# --- the statistics --------------------------------------------------------------------------------------------

def wilson(k: int, n: int, z: float = Z) -> tuple[float, float]:
    """The Wilson score interval for k of n (the fact sheet, 8.2.3)."""
    if n <= 0 or not 0 <= k <= n:
        raise ValueError(f"{k} of {n} is not a proportion")
    p = k / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return max(0.0, center - half), min(1.0, center + half)


def kappa(pairs: list[tuple[str, str]]) -> float | None:
    """Cohen's kappa for two raters' right or wrong on the same outputs (the fact sheet, 8.2.1). None where it is
    undefined: no pairs, or both raters gave one and the same label to every output."""
    if not pairs:
        return None
    n = len(pairs)
    observed = sum(a == b for a, b in pairs) / n
    a = sum(x == "wrong" for x, _ in pairs) / n
    b = sum(y == "wrong" for _, y in pairs) / n
    expected = a * b + (1 - a) * (1 - b)
    return None if expected == 1 else (observed - expected) / (1 - expected)


@dataclass(frozen=True)
class Agreement:
    """A rater set against the labels, as the counts every figure comes from."""
    n: int  # outputs with both a label and the rater's verdict
    agree: int
    kappa: float | None
    labeled_wrong: int
    rater_wrong: int
    both_wrong: int

    @property
    def rate(self) -> float | None:
        return self.agree / self.n if self.n else None

    @property
    def interval(self) -> tuple[float, float] | None:
        return wilson(self.agree, self.n) if self.n else None

    @property
    def meets(self) -> bool | None:
        """E-D5's rule: at least 90 percent agreement."""
        return None if self.rate is None else self.rate >= TRUST


def agreement(pairs: list[tuple[str, str]]) -> Agreement:
    """pairs: (the label, the rater's verdict), each right or wrong."""
    return Agreement(n=len(pairs), agree=sum(a == b for a, b in pairs), kappa=kappa(pairs),
                     labeled_wrong=sum(a == "wrong" for a, _ in pairs), rater_wrong=sum(b == "wrong" for _, b in pairs),
                     both_wrong=sum(a == b == "wrong" for a, b in pairs))


# --- the labels beside the verdicts ----------------------------------------------------------------------------

@dataclass(frozen=True)
class Row:
    entry: dict[str, Any]  # the sample's entry
    label: str | None
    note: str
    judge: str | None  # the judge's verdict; None where its reply gave none
    reason: str | None
    rules: str | None  # the rules' verdict on the prose as a label; None where no rule reads it


def synthetic(lines: list[dict[str, Any]]) -> bool:
    marks = {line.get("synthetic") is True for line in lines}
    if len(marks) > 1:
        raise ValueError("the label file mixes synthetic lines with others")
    return marks == {True}


def joined(document: dict[str, Any], labels: dict[str, dict[str, Any]],
           docs: dict[tuple[str, str], dict[str, Any]]) -> list[Row]:
    """Each sampled output with its label, the judge's verdict and reason, and the rules' verdict. Refused if the
    judge's results lack an output's cross verdict, or if a label was made against another rubric."""
    crossed = sampling.cross_rows(docs)
    out, other = [], Counter()
    for e in document["items"]:
        result = crossed.get((e["judge"], sampling.key_of(e)))
        if result is None:
            raise ValueError(f"{e['id']}: the judge's results hold no verdict of {e['judge']} on it")
        line = labels.get(e["id"])
        if line and line.get("rubric_sha256") != docs[(e["workflow"], e["judge"])]["rubric"]["sha256"]:
            other[e["workflow"]] += 1
        rules = None if e["rules"]["pass"] is None else "right" if e["rules"]["pass"] else "wrong"
        out.append(Row(e, line["label"] if line else None, (line or {}).get("note") or "", result["verdict"],
                       result["reason"], rules))
    if other:
        raise ValueError("labels made against another rubric than the one behind the judge's verdicts: " +
                         ", ".join(f"{w} {n}" for w, n in sorted(other.items())) +
                         "; label those outputs again, or set them against the judge's run on that rubric")
    return out


def pairs(rows: list[Row], rater: str) -> list[tuple[str, str]]:
    return [(r.label, getattr(r, rater)) for r in rows if r.label and getattr(r, rater)]


def calibration(path: Path = LABELS, folder: Path | None = None) -> dict[str, Agreement] | None:
    """The judge against a person's label file, per workflow (E-D5), or None while the file doesn't exist. Synthetic
    labels calibrate nothing, so a file of them is refused."""
    if not path.exists():
        return None
    document = sampling.load()
    labels, lines = sampling.read_labels(path, {e["id"] for e in document["items"]})
    if synthetic(lines):
        raise ValueError(f"{path.name} holds synthetic labels, which calibrate nothing")
    rows = joined(document, labels, sampling.judge_results(folder or sampling.results_folder()))
    workflows = sorted({r.entry["workflow"] for r in rows})
    return {w: agreement(pairs([r for r in rows if r.entry["workflow"] == w], "judge")) for w in workflows}


# --- the report ------------------------------------------------------------------------------------------------

def _pct(x: float) -> str:
    return f"{100 * x:.1f}"


def _of(k: int, n: int) -> str:
    """k of n with its percentage and Wilson interval, or "none"."""
    if not n:
        return "none"
    low, high = wilson(k, n)
    return f"{k} of {n}, {_pct(k / n)} ({_pct(low)} to {_pct(high)})"


def _cells(a: Agreement) -> list[str]:
    if not a.n:
        return ["0", "", "", "", "", "", ""]
    low, high = a.interval  # type: ignore[misc]
    return [str(a.n), str(a.agree), _pct(a.rate), f"{_pct(low)} to {_pct(high)}",  # type: ignore[arg-type]
            "n/a" if a.kappa is None else f"{a.kappa:.2f}", str(a.labeled_wrong), str(a.rater_wrong)]


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    return ["|" + " |".join(header) + " |", "|" + "---|" * len(header)] + ["|" + " |".join(r) + " |" for r in rows]


def _cell(text: str | None) -> str:
    return " ".join((text or "").split()).replace("|", "\\|")


def _groups(rows: list[Row]) -> list[tuple[str, list[Row]]]:
    return [("all", rows), ("drawn by the seed", [r for r in rows if r.entry["pick"] == "drawn"]),
            ("known outputs", [r for r in rows if r.entry["pick"] == "known"])] + \
           [(f"judged by {j}", [r for r in rows if r.entry["judge"] == j]) for j in sorted({r.entry["judge"] for r in rows})]


RATERS = {"judge": ("The judge", "the judge's", "the judge calls"),
          "rules": ("The rules", "the rules'", "the rules call")}


def _section(rows: list[Row], rater: str, mark: str) -> list[str]:
    """One rater against the labels: per workflow with E-D5's rule, over the sample, and precision and recall."""
    who, whose, calls = RATERS[rater]
    head = ["Labeled", "Agree", "Agreement", "95% interval", "Kappa", "Labeled wrong", f"{who}: wrong"]
    per = []
    for workflow in judging.JUDGED:
        a = agreement(pairs([r for r in rows if r.entry["workflow"] == workflow], rater))
        per.append([workflow.upper(), *_cells(a), "" if a.meets is None else "yes" if a.meets else "no"])
    over = [[name, *_cells(agreement(pairs(group, rater)))] for name, group in _groups(rows)]
    recall = []
    for name, group in [*_groups(rows)[:3], *[(w.upper(), [r for r in rows if r.entry["workflow"] == w])
                                              for w in judging.JUDGED]]:
        a = agreement(pairs(group, rater))
        recall.append([name, _of(a.both_wrong, a.rater_wrong), _of(a.both_wrong, a.labeled_wrong)])
    return ([f"## {who} against the labels{mark}", "",
             f"Per workflow, with E-D5's rule beside each, at least {round(100 * TRUST)} percent agreement{mark}:", ""] +
            _table(["Workflow", *head, "At least 90%"], per) +
            ["", f"Over the sample{mark}:", ""] + _table(["Outputs", *head], over) +
            ["", f"Precision and recall on \"wrong\"{mark}. Precision is the share of {whose} \"wrong\" that the "
                 f"labels also call wrong, and recall the share of the outputs labeled wrong that {calls} wrong.", ""] +
            _table(["Outputs", "Precision", "Recall"], recall) + [""])


def report(path: Path, document: dict[str, Any] | None = None, folder: Path | None = None) -> str:
    """The report for one label file, as Markdown."""
    document = sampling.load() if document is None else document
    labels, lines = sampling.read_labels(path, {e["id"] for e in document["items"]})
    fake = synthetic(lines)
    mark = " (synthetic labels)" if fake else ""
    folder = folder or sampling.results_folder()
    docs = sampling.judge_results(folder)
    rows = joined(document, labels, docs)
    labeled = [r for r in rows if r.label]
    labeler = {line.get("labeler") for line in lines} - {None} or {path.stem.removeprefix("labels-")}
    hashes = sorted({(w, d["rubric"]["sha256"][:12]) for (w, _), d in docs.items()})
    try:
        where = registry.rel(folder)
    except ValueError:  # a results folder outside the repository
        where = str(folder)
    out = [f"# {'SYNTHETIC: the' if fake else 'The'} judge and the rules against {path.name}", ""]
    if fake:
        out += [SYNTHETIC.format(name=path.name), ""]
    out += [f"Labeler {', '.join(sorted(labeler))}: {len(labeled)} of {len(rows)} sampled outputs labeled, from "
            f"{len(lines)} lines, {len(lines) - len(labels)} of them replaced by a later line for the same output. "
            f"The judge's verdicts are those in {where}, on the rubrics "
            + ", ".join(f"{w} `{h}`" for w, h in hashes) + ", and every label was made against the same rubric.",
            ""]
    out += _section(rows, "judge", mark)
    out += _section(rows, "rules", mark)
    both = [r for r in labeled if r.judge and r.rules]
    cells = []
    for rules in ("right", "wrong"):
        for judge in ("right", "wrong"):
            group = [r for r in both if (r.rules, r.judge) == (rules, judge)]
            cells.append([rules, judge, str(len(group)), str(sum(r.label == "right" for r in group)),
                          str(sum(r.label == "wrong" for r in group))])
    differ = [r for r in both if r.rules != r.judge]
    sides = sum(r.label == r.judge for r in differ)
    out += [f"## Where the judge and the rules agree and differ{mark}", ""] + \
        _table(["Rules", "Judge", "Outputs", "Labeled right", "Labeled wrong"], cells) + \
        ["", f"Where the two differ, the labels side with the judge on {sides} of {len(differ)} outputs and with the "
             f"rules on {len(differ) - sides}{mark}. Outputs no rule reads: "
             f"{sum(1 for r in labeled if r.rules is None)}.", ""]
    split = sorted((r for r in labeled if r.judge and r.judge != r.label),
                   key=lambda r: (r.entry["workflow"], r.entry["id"]))
    out += [f"## Where the judge and the labels differ{mark}", "",
            "A W1 reason can quote a Restricted page (W1-D26), so this table is Restricted data wherever it holds a "
            "W1 row.", ""]
    out += _table(["Id", "Workflow", "Case", "Written by", "Judge", "Label", "Judge said", "Rules", "Note",
                   "The judge's reason"],
                  [[r.entry["id"], r.entry["workflow"].upper(), _cell(f"{r.entry['case']} {r.entry['part']}"),
                    r.entry["model"], r.entry["judge"], r.label or "", r.judge or "", r.rules or "no rule",
                    _cell(r.note), _cell(r.reason)] for r in split]) if split else ["None."]
    silent = [r for r in labeled if not r.judge]
    out += ["", f"Labeled outputs the judge gave no verdict: {len(silent)}" +
            (" (" + ", ".join(r.entry["id"] for r in silent) + ")." if silent else ".")]
    if fake:
        out += ["", SYNTHETIC.format(name=path.name)]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("labels", nargs="?", type=Path, default=LABELS, help="the label file (labels/labels-A.jsonl)")
    parser.add_argument("--results", type=Path, help="the folder of the judge's results (default: the newest)")
    parser.add_argument("--write", action="store_true", help="save the report beside the label file")
    args = parser.parse_args(argv)
    if not args.labels.exists():
        raise SystemExit(f"{args.labels.name} does not exist yet; the labeling page (python labels/page.py) writes it")
    try:
        text = report(args.labels, folder=args.results)
    except ValueError as exc:
        raise SystemExit(f"{args.labels.name}: {exc}") from exc
    print(text, end="")
    if args.write:
        target = args.labels.parent / f"agreement-{args.labels.stem.removeprefix('labels-')}.md"
        target.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
