"""Chapter 15's judge in the ledger (chapter 16, step 9): every judge call as a cost line under the workflow it
judged, marked as the judge's, and the judge's tokens set against the tokens of the outputs it judged.

Chapter 15 says the ledger "carries the judge's tokens under the workflow that was judged" (ch15:305) and that a
judge that thinks before it answers writes more tokens than the answer it judges (ch15:156). The judge's calls went
through chapter 5's gateway with the judged workflow's tag and the case's data class
(labs/ch15/judge/run_judge.py), so the gateway's log holds one line per judgment under the judged workflow, with the
tokens and no prompt or reply. Chapter 15 kept
each run's log beside its result files: the first run in judge-v1/, the second in judge-v2/, and the third as the
current files, which judged W1 to W3 again and kept W4's and W5's second-run files and lines; `run_judge.runs` and
`run_judge.origins` are chapter 15's own reading of that layout, imported here. A current line that is also in
judge-v2/ is one call, counted once, under the run that made it.

Each judgment is one Run of one CostLine under the judged workflow: the judge's model as the line's model, the
alias and class the call carried, the tokens and latency the gateway recorded, and three fields the workflows' own
lines never carry: `judge` (the run, v1, v2, or v3), `judged` (the kept run whose output the judge read, "<model>
<label>"), and `judge_slice` (cross, self, or padded). costlines.collect() leaves these runs out, so cost per run,
the month, and the allocation stay the workflows' own; collect() here returns them, report.py prices them like any
line and writes them after the workflows' lines in costlines.jsonl, and the summary's last section sets them
against what they judged.

The comparison: for each judgment, the judge's tokens against the tokens of the output it read, which are the kept
run's own cost lines for that case: every model call of the run for W1 to W4, and for W5 the one call that wrote
the pull request body, paired to the night's pull requests in the order the night wrote them. A padded copy counts
the original's tokens. W3's and W4's judged outputs come from chapter 15's kept runs, which kept no tokens (their
gateway logs stayed in the scratch folders, step 2), so for those two the tokens of step 3b's run of the same case
on the same model stand in, and every table says which ratio is measured and which rests on the stand-in. Sums per
judge run, per workflow, and per judge; the ratios are prompt, completion, and total, in total over a group's
judgments, and each group also counts the judgments whose completion tokens exceed the output's.

What the section concludes is derived here, once, and the two pages that print it (ledger/render.py's section 14 and
the review's section 1) only format it: which judge has thinking on, from the think flag in the result files; in
which workflows its completion tokens, in total, exceed the outputs'; the counts by judgment; the all-token ratios,
which count a prompt token like a completion token and are token figures and not prices; and the two populations of
the median completion tokens a judgment, the three runs' judgments (the ledger's) and the current files' calls
(chapter 15's README and ch15:156).
"""

from __future__ import annotations

import json
import statistics
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import costlines  # noqa: E402
import price  # noqa: E402
import registry  # noqa: E402

JUDGE_FOLDER = "labs/ch15/judge"
WRITTEN = ("opened", "updated")  # a pull request the night wrote a body for: one model call each (W5's writer)
JUDGES = ("gemma4-12b", "gpt-oss-20b")
WORKFLOWS = ("w1", "w2", "w3", "w4", "w5")
SLICES = ("cross", "self", "padded")
MEASURED, STAND_IN, NONE = "measured", "stand-in", "none"


def results_folder() -> Path:
    """Chapter 15's newest dated results folder that holds a judge log."""
    folders = sorted(p for p in (registry.LAB / "results").iterdir()
                     if p.is_dir() and any(p.glob("judge-gateway-*.jsonl")))
    if not folders:
        raise FileNotFoundError("chapter 15 kept no judge log")
    return folders[-1]


def layout(folder: Path) -> tuple[list[tuple[str, dict[str, Path]]], dict[str, str]]:
    """Chapter 15's own reading of its folder (judge/run_judge.py): each run's result files, oldest first, and the
    run each current file comes from."""
    with registry.isolated((JUDGE_FOLDER,)):
        import run_judge
        return run_judge.runs(folder), run_judge.origins(folder)


def read_logs(folder: Path) -> dict[tuple[Path, str], dict[str, Any]]:
    """Every `call` line of every judge log under the folder, by the log's place and the trace id."""
    out: dict[tuple[Path, str], dict[str, Any]] = {}
    for path in sorted(folder.glob("**/judge-gateway-*.jsonl")):
        for entry in registry.read_jsonl(path):
            if entry.get("event") == "call":
                out[(path.parent, entry["trace_id"])] = entry
    return out


@dataclass(frozen=True)
class Judgment:
    workflow: str
    run: str            # v1, v2, v3
    judge: str          # the judge's model tag
    slice: str          # cross, self, padded
    case: str
    part: str           # W5: the pull request's finding key
    judged: str         # the kept run the output came from, "<model> <label>"
    judged_model: str
    line: dict[str, Any]
    seconds: float | None
    verdict: str | None
    source: str         # the log, repository-relative
    measured: str | None = None   # the date chapter 15 recorded in the result file
    thinking: Any = None          # the judge's think flag as the result file records it (False, or "model default")

    @property
    def case_id(self) -> str:
        return f"{self.case}:{self.part}" if self.part else self.case


def judgments(folder: Path | None = None) -> list[Judgment]:
    """Every judgment of every run, each joined to its gateway line by trace id, counted once."""
    folder = folder or results_folder()
    runs_, origins = layout(folder)
    logs = read_logs(folder)
    seen: set[str] = set()
    out: list[Judgment] = []
    for label, files in runs_:
        for name, path in files.items():
            if path.parent == folder and origins[name] != label:
                continue  # a current file an earlier run made: counted under that run
            data = registry.read_json(path)
            log = path.parent / f"judge-gateway-{data['judge']}.jsonl"
            for item in data["items"]:
                trace = item["trace_id"]
                if trace in seen:
                    raise ValueError(f"{name}: judgment {trace} counted twice")
                seen.add(trace)
                line = logs[(path.parent, trace)]
                if (line["prompt_tokens"], line["completion_tokens"]) != (item["tokens"]["prompt"], item["tokens"]["completion"]):
                    raise ValueError(f"{name}: {trace} has other tokens in the log than in the result file")
                out.append(Judgment(data["workflow"], label, data["judge"], item["slice"], item["case"], item["part"],
                                    f"{item['model']} {item['run']}", item["model"], line, item.get("seconds"),
                                    item.get("verdict"), registry.rel(log), data.get("measured"),
                                    (data.get("judge_model") or {}).get("think")))
    return out


def as_run(j: Judgment) -> costlines.Run:
    """The judgment as one Run of one CostLine under the judged workflow, marked as the judge's."""
    e = j.line
    kept_run = f"{j.judge} judge/{j.run}"
    line = costlines.CostLine(e["trace_id"], e["trace_id"], j.workflow, e["workflow"], kept_run, j.case_id, 1,
                              e["served_model"], costlines.model_tag(e["served_model"]), e["requested_alias"],
                              e["served_alias"], e["data_class"], e["prompt_tokens"], e["completion_tokens"],
                              e.get("latency_ms"), bool(e["fallback"]), j.source, judge=j.run, judged=j.judged,
                              judge_slice=j.slice)
    return costlines.Run(e["trace_id"], e["trace_id"], j.workflow, j.judge, kept_run, j.case_id, 1, None, j.seconds,
                         None, (line,), judge=j.run)


def collect(folder: Path | None = None) -> list[costlines.Run]:
    """The judge's runs, in the order of the runs, the workflows, the judges, and the cases."""
    order = {w: i for i, w in enumerate(WORKFLOWS)}
    return [as_run(j) for j in sorted(judgments(folder), key=lambda j: (j.run, order[j.workflow], j.judge, j.case_id))]


# --- what the judge read ------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Judged:
    """The tokens of the output a judgment read, and where they come from."""
    basis: str                  # measured, stand-in, or none
    input_tokens: int = 0
    output_tokens: int = 0
    source: str = ""


def w5_bodies(own: list[costlines.Run]) -> dict[tuple[str, str, str], costlines.CostLine]:
    """Each W5 pull request body's call: the night's pull requests in the order it wrote them, paired with its
    gateway lines in order, one call a body. A night whose counts differ raises, since any pairing of it would be a
    guess."""
    nights = {(r.kept_run, r.case): r for r in own if r.workflow == "w5"}
    out = {}
    for kept in registry.kept_runs("w5"):
        name = f"{kept.model} {kept.label}"
        for night, data in registry.outputs(kept).items():
            run = nights.get((name, night))
            if run is None:
                continue
            written = [pr for pr in data["record"]["pull_requests"] if pr["action"] in WRITTEN]
            if len(written) != len(run.lines):
                raise ValueError(f"W5 {name} {night}: {len(written)} bodies written and {len(run.lines)} calls")
            for pr, line in zip(written, run.lines):
                out[(name, night, pr["key"])] = line
    return out


class Outputs:
    """What each judgment read, from the workflows' own runs: measured where the kept run kept tokens, step 3b's run
    of the same case on the same model standing in where it didn't (W3 and W4), none where neither exists."""

    def __init__(self, own: list[costlines.Run]) -> None:
        self.by_case = {(r.workflow, r.kept_run, r.case): r for r in own if r.workflow != "skeleton"}
        self.traced = {(r.workflow, r.model, r.case): r for r in own if costlines.is_traced(r)}
        self.bodies = w5_bodies(own)

    def of(self, j: Judgment) -> Judged:
        if j.workflow == "w5":
            line = self.bodies[(j.judged, j.case, j.part)]
            return Judged(MEASURED, line.input_tokens, line.output_tokens, f"{j.judged}, the body's call")
        run = self.by_case[(j.workflow, j.judged, j.case)]
        if run.tokens_kept:
            tin, tout = run.tokens()
            return Judged(MEASURED, tin, tout, j.judged)
        stand_in = self.traced.get((j.workflow, j.judged_model, j.case))
        if stand_in is None:
            return Judged(NONE)
        tin, tout = stand_in.tokens()
        return Judged(STAND_IN, tin, tout, f"{stand_in.kept_run}, the same case on the same model")


# --- the comparison -----------------------------------------------------------------------------------------------

def _tokens(js: list[Judgment]) -> dict[str, int]:
    p = sum(j.line["prompt_tokens"] for j in js)
    c = sum(j.line["completion_tokens"] for j in js)
    return {"prompt": p, "completion": c, "total": p + c}


def _judged_tokens(reads: list[Judged]) -> dict[str, int]:
    p = sum(r.input_tokens for r in reads)
    c = sum(r.output_tokens for r in reads)
    return {"prompt": p, "completion": c, "total": p + c}


def _ratio(judge: dict[str, int], judged: dict[str, int]) -> dict[str, float] | None:
    if not judged["total"]:
        return None
    return {k: round(judge[k] / judged[k], 4) if judged[k] else None for k in ("prompt", "completion", "total")}


def group(js: list[Judgment], outputs: Outputs, table: dict[str, Any]) -> dict[str, Any]:
    """One group's sums: the judge's tokens, the judged outputs' tokens on each basis, and the ratios over the
    judgments that share a basis, so a ratio never mixes a measured denominator with a stand-in."""
    reads = {id(j): outputs.of(j) for j in js}
    by_basis = {basis: [j for j in js if reads[id(j)].basis == basis] for basis in (MEASURED, STAND_IN, NONE)}
    usd = sum((price.line_cost(table, as_run(j).lines[0]) or Decimal(0) for j in js), Decimal(0))
    seconds = [j.seconds for j in js if j.seconds is not None]
    out = {"judgments": len(js), "judge_tokens": _tokens(js), "seconds": round(sum(seconds), 1), "usd": float(round(usd, 8)),
           "completion_median": statistics.median(j.line["completion_tokens"] for j in js) if js else None,
           "prompt_median": statistics.median(j.line["prompt_tokens"] for j in js) if js else None}
    for basis in (MEASURED, STAND_IN):
        mine = by_basis[basis]
        judged = _judged_tokens([reads[id(j)] for j in mine])
        out[basis] = {"judgments": len(mine), "judge_tokens": _tokens(mine), "judged_tokens": judged,
                      "ratio": _ratio(_tokens(mine), judged),
                      # judgment by judgment, as against the totals the ratio compares
                      "completion_over": sum(1 for j in mine if j.line["completion_tokens"] > reads[id(j)].output_tokens),
                      "total_over": sum(1 for j in mine if j.line["prompt_tokens"] + j.line["completion_tokens"]
                                        > reads[id(j)].input_tokens + reads[id(j)].output_tokens)}
    out["without_tokens"] = len(by_basis[NONE])
    return out


def current_files(folder: Path) -> dict[str, dict[str, Any]]:
    """The calls of each judge's log in chapter 15's current files, the population of chapter 15's own medians
    (ch15:156: 360 and 240 calls, 29 and 559 completion tokens at the median); the ledger's by_judge is the three
    runs' judgments."""
    out = {}
    for judge in JUDGES:
        path = folder / f"judge-gateway-{judge}.jsonl"
        if not path.exists():
            continue
        calls = [e for e in registry.read_jsonl(path) if e.get("event") == "call"]
        out[judge] = {"calls": len(calls),
                      "prompt_median": statistics.median(e["prompt_tokens"] for e in calls),
                      "completion_median": statistics.median(e["completion_tokens"] for e in calls)}
    return out


def thinking_of(js: list[Judgment]) -> dict[str, Any]:
    """Each judge's think flag as its result files record it: False when thinking was turned off, else the model's
    default; "varies" if the files disagree."""
    out: dict[str, Any] = {}
    for judge in JUDGES:
        values = {json.dumps(j.thinking) for j in js if j.judge == judge}
        if values:
            out[judge] = json.loads(values.pop()) if len(values) == 1 else "varies"
    return out


def conclusion(sentence: list[dict[str, Any]], thinking: dict[str, Any]) -> dict[str, Any]:
    """What the ratios say about ch15:156 ("a judge that thinks before it answers writes more tokens than the answer
    it judges"), for the pages to format: the judges with thinking on and off, and for each judge its workflows with
    the ratios in total, the judgments over the output's completion tokens, and the workflows it judged not at all.
    Completion tokens are what a judge writes; the all-token ratio counts a prompt token like a completion token and
    is a token figure, not a price."""
    on = [j for j in JUDGES if j in thinking and thinking[j] is not False]
    off = [j for j in JUDGES if j in thinking and thinking[j] is False]
    by_judge: dict[str, list[dict[str, Any]]] = {}
    for s in sentence:
        by_judge.setdefault(s["judge"], []).append(
            {"workflow": s["workflow"], "basis": s["basis"], "judgments": s["judgments"],
             "completion": s["ratio"]["completion"], "total": s["ratio"]["total"], "prompt": s["ratio"]["prompt"],
             "completion_over": s["completion_over"], "total_over": s["total_over"]})
    rows_of = {j: {r["workflow"] for r in by_judge.get(j, [])} for j in JUDGES}
    return {"thinking_on": on, "thinking_off": off, "by_judge": by_judge,
            # a workflow another judge judged and this one did not, with the judges that did
            "not_judged_by": {j: {w: [o for o in JUDGES if o != j and w in rows_of[o]] for w in WORKFLOWS
                                  if w not in rows_of[j] and any(w in rows_of[o] for o in JUDGES if o != j)}
                              for j in JUDGES if j in thinking},
            "completion_in_total": {j: {"above": [r["workflow"] for r in by_judge.get(j, []) if r["completion"] > 1],
                                        "not_above": [r["workflow"] for r in by_judge.get(j, []) if r["completion"] <= 1]}
                                    for j in JUDGES if j in thinking},
            "all_tokens_in_total": {j: {"above": [r["workflow"] for r in by_judge.get(j, []) if r["total"] > 1],
                                        "not_above": [r["workflow"] for r in by_judge.get(j, []) if r["total"] <= 1]}
                                    for j in JUDGES if j in thinking}}


def section(own: list[costlines.Run], table: dict[str, Any], folder: Path | None = None) -> dict[str, Any]:
    """The judge's tokens in the ledger: the runs, the lines, and the judge against what it judged."""
    folder = folder or results_folder()
    js = judgments(folder)
    runs_, origins = layout(folder)
    outputs = Outputs(own)
    logs = read_logs(folder)
    current = {trace for (place, trace) in logs if place == folder}
    kept = {trace for (place, trace) in logs if place != folder}
    all_tokens = _tokens(js)

    def rows(keys: list[tuple[str, str, str]]) -> list[dict[str, Any]]:
        out = []
        for workflow, run, judge in keys:
            mine = [j for j in js if (workflow in ("all", j.workflow)) and (run in ("all", j.run)) and (judge in ("both", j.judge))]
            if mine:
                out.append({"workflow": workflow, "run": run, "judge": judge, **group(mine, outputs, table)})
        return out

    labels = [label for label, _ in runs_]
    by_run = rows([("all", run, judge) for run in labels for judge in JUDGES])
    by_workflow = rows([(w, "all", judge) for w in WORKFLOWS for judge in (*JUDGES, "both")])
    by_workflow_run = rows([(w, run, judge) for w in WORKFLOWS for run in labels for judge in JUDGES])
    by_judge = rows([("all", "all", judge) for judge in (*JUDGES, "both")])
    by_slice = []
    for s in SLICES:
        mine = [j for j in js if j.slice == s]
        if mine:
            by_slice.append({"slice": s, **group(mine, outputs, table)})
    sentence = []
    for row in by_workflow:
        if row["judge"] == "both":
            continue
        for basis in (MEASURED, STAND_IN):
            r = row[basis]["ratio"]
            if r is None:
                continue
            sentence.append({"workflow": row["workflow"], "judge": row["judge"], "basis": basis,
                             "judgments": row[basis]["judgments"], "ratio": r,
                             "more_than_the_output": r["total"] > 1, "more_completion": (r["completion"] or 0) > 1,
                             "more_prompt": (r["prompt"] or 0) > 1,
                             "completion_over": row[basis]["completion_over"], "total_over": row[basis]["total_over"]})
    thinking = thinking_of(js)
    expected = {w: registry.manifest(w)["workflow"] for w in WORKFLOWS}
    return {
        "folder": registry.rel(folder),
        "measured": sorted({j.measured for j in js if j.measured}),
        "thinking": thinking,
        "tag_is_the_judged_workflows": sum(1 for j in js if j.line["workflow"] == expected[j.workflow]),
        "current_files": current_files(folder),
        "layout": [{"run": label, "place": registry.rel(next(iter(files.values())).parent) if files else None,
                    "files": sorted(name for name, path in files.items()
                                    if not (path.parent == folder and origins[name] != label))}
                   for label, files in runs_],
        "origins": dict(sorted(origins.items())),
        "calls": len(js), "prompt_tokens": all_tokens["prompt"], "completion_tokens": all_tokens["completion"],
        "current_log_lines_also_in_a_kept_run": len(current & kept),
        "by_workflow_tag": dict(sorted(_count(j.line["workflow"] for j in js).items())),
        "by_alias_and_class": dict(sorted(_count(f"{j.line['requested_alias']}/{j.line['data_class']}" for j in js).items())),
        "judged_outputs_basis": {"w1": MEASURED, "w2": MEASURED, "w5": MEASURED + ", the body's call", "w3": STAND_IN, "w4": STAND_IN,
                                 "why": "W3's and W4's judged outputs come from chapter 15's kept runs, whose gateway logs "
                                        "stayed in the scratch folders (step 2), so step 3b's run of the same case on the "
                                        "same model stands in for their tokens"},
        "by_run": by_run, "by_workflow": by_workflow, "by_workflow_run": by_workflow_run, "by_judge": by_judge,
        "by_slice": by_slice, "sentence": sentence, "conclusion": conclusion(sentence, thinking),
    }


def _count(items: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in items:
        out[item] = out.get(item, 0) + 1
    return out


# --- the words for it ---------------------------------------------------------------------------------------------
# The phrases the two pages share, built from the rows of `conclusion` and nothing else, so that a sentence says
# "in every workflow it judged" only when the data does.

NAMES = {w: w.upper() for w in WORKFLOWS}
JUDGE_NAMES = {"gemma4-12b": "Gemma 4 12B", "gpt-oss-20b": "gpt-oss-20b"}


def join(items: list[str]) -> str:
    """A list in prose: A, B and C."""
    return "none" if not items else items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def ratios_text(rows: list[dict[str, Any]], key: str) -> str:
    """The ratios of one kind in prose, the workflow first: W1 (1.38), W4 (3.60, on the stand-in)."""
    return join([f"{NAMES[r['workflow']]} ({r[key]:.2f}{', on the stand-in' if r['basis'] == STAND_IN else ''})" for r in rows])


def more_or_fewer(rows: list[dict[str, Any]], above: list[str]) -> str:
    """Whether a judge wrote more or fewer than the outputs it read, in total: in every workflow it judged, or more in
    the ones it is above in and fewer in the rest."""
    up = [NAMES[r["workflow"]] for r in rows if r["workflow"] in above]
    down = [NAMES[r["workflow"]] for r in rows if r["workflow"] not in above]
    if not down:
        return "more than the outputs it read in every workflow it judged"
    if not up:
        return "fewer than the outputs it read in every workflow it judged"
    return f"more than the outputs it read in {join(up)} and fewer in {join(down)}"


def alone_text(not_judged: dict[str, list[str]]) -> str:
    """The workflows a judge did not judge, and who did: W3 was judged by Gemma 4 12B alone."""
    groups: dict[tuple[str, ...], list[str]] = {}
    for workflow, judges in not_judged.items():
        groups.setdefault(tuple(judges), []).append(workflow)
    return "; ".join(f"{join([NAMES[w] for w in ws])} {'was' if len(ws) == 1 else 'were'} judged by "
                     f"{join([JUDGE_NAMES[j] for j in judges])} alone" for judges, ws in groups.items())


def over_text(rows: list[dict[str, Any]]) -> str:
    """The judgments whose completion tokens exceed the output's, by workflow: 117 of 171 W1 judgments."""
    hits = [r for r in rows if r["completion_over"]]
    if not hits:
        return "none of its judgments"
    return join([f"{r['completion_over']:,} of {r['judgments']:,} {NAMES[r['workflow']]} judgments" for r in hits])


def sides_text(rows: list[dict[str, Any]], above: list[str]) -> str:
    """The all-token ratios on each side of one: above the output's for W4 (3.61) and below it for W1 (0.33)."""
    up = [r for r in rows if r["workflow"] in above]
    down = [r for r in rows if r["workflow"] not in above]
    parts = []
    if up:
        parts.append(f"above the output's for {ratios_text(up, 'total')}")
    if down:
        parts.append(f"below it for {ratios_text(down, 'total')}" if up else f"below the output's for {ratios_text(down, 'total')}")
    return " and ".join(parts)


def main(argv: list[str] | None = None) -> int:
    own = costlines.collect()
    data = section(own, price.load())
    print(f"{data['calls']} judgments, {data['prompt_tokens']:,} prompt and {data['completion_tokens']:,} completion tokens; "
          f"{data['current_log_lines_also_in_a_kept_run']} current lines also in a kept run")
    for name in ("by_run", "by_judge", "by_workflow", "by_workflow_run", "by_slice"):
        print(f"-- {name}")
        for r in data[name]:
            t = r["judge_tokens"]
            head = " ".join(str(r.get(k, "")) for k in ("workflow", "run", "judge", "slice") if k in r)
            parts = [f"{head:28s} n={r['judgments']:4d} judge {t['prompt']:>9,}/{t['completion']:>8,}/{t['total']:>9,} "
                     f"usd {r['usd']:.4f} median c {r['completion_median']}"]
            for basis in (MEASURED, STAND_IN):
                b = r[basis]
                if b["judgments"]:
                    ratio = b["ratio"] or {}
                    parts.append(f"{basis} n={b['judgments']} judged {b['judged_tokens']['prompt']:,}/{b['judged_tokens']['completion']:,}"
                                 f"/{b['judged_tokens']['total']:,} ratio {ratio.get('prompt')}/{ratio.get('completion')}/{ratio.get('total')}")
            if r["without_tokens"]:
                parts.append(f"without tokens {r['without_tokens']}")
            print("  " + " | ".join(parts))
    print("-- sentence")
    for s in data["sentence"]:
        print("  ", json.dumps(s))
    c = data["conclusion"]
    print("-- thinking", data["thinking"], "| current files", json.dumps(data["current_files"]))
    print("-- conclusion: thinking on", c["thinking_on"], "off", c["thinking_off"], "| completion tokens above the output's, in total",
          json.dumps(c["completion_in_total"]), "| all tokens", json.dumps(c["all_tokens_in_total"]),
          "| not judged by", json.dumps(c["not_judged_by"]))
    print("-- tags", data["by_workflow_tag"], "aliases", data["by_alias_and_class"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
