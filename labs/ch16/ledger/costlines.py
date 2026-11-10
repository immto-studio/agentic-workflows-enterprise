"""Every model call in every kept run, as one cost line of a single shape, with no model.

Chapter 16, step 2 (companion #14, O-D5). The workflows kept their runs beside their results, and chapter
15's registry already finds and reads every one of them (labs/ch15/layers/registry.py: `kept_runs`,
`outputs`, `stored_verdicts`), and this module imports it. Each output of a kept run
is one run of the workflow, the unit a trace id names, and each of its model calls is one cost line:

    run_id            the trace id where the run kept one, else <workflow>:<model>:<kept run>:<case>
    workflow          the registry's id (skeleton, w1 ... w5), and the workflow tag the gateway saw
    model             as recorded: the gateway's served model (W5), the run's gateway_models (W1, W2), or
                      the kept run's own model tag (the skeleton, W3, W4); model_tag normalizes it
    alias             the alias asked for and the alias that served; data_class, the call's class
    tokens            input and output, where the run kept them
    duration_ms       per call, where the run kept it
    fallback          whether a fallback served the call

What each workflow kept differs, and each line records what its run kept:

  skeleton  chapter 9's results: each call's tokens and latency, and every tool call with its
            arguments. Chapter 9's runner asks for larkspur-chat-restricted (its --alias default), with
            chapter 5's GatewayModel's tags: workflow w2-ops-assistant, data class Internal.
  W1, W2    each call's class and alias, tokens and latency. W2 keeps every read; W1 keeps no search,
            so its tool calls are the searches its calls imply, as chapter 15's trajectory layer counts
            them: each call but the last asked for one, and a failed search ends the question.
  W3        each call's class and alias, and the reads that returned data. No tokens, and no time per
            call: the gateway's log stayed in the lab's scratch folder.
  W4        one call per change, from the summary's count of the gateway's lines; no tokens, and no tool
            call, since the analyst reads its sources in its own process and logs no call.
  W5        the gateway's own line per call, joined to the night by trace id, and the night's reads.

No lab gateway config named a fallback, and no kept call took one: W5's lines say so, and the other
workflows' gateways couldn't fall back.

Step 3b ran W2, W3, and W4 through chapter 16's Collector (collector/run_workflows.py) and kept each run in the
workflow's eval/traced/<date>/ with the gateway's cost lines beside it, in logs-<model>/gateway.jsonl. Those runs
sit beside eval/results/ because chapter 15's registry takes every run in eval/results/ as one of the runs its
replay, judge and tests were built on, and `traced_runs` finds them where they are. Their lines are the gateway's
own, one per call, joined to each case by its trace id, as W5's are: from the harness's log for W2 (its lines
carry the case), from the trace ids the run kept beside the record for W3, and from each pack for W4.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True  # import chapter 15's registry and the workflows' code without caches
LAB = Path(__file__).resolve().parents[1]
LAYERS = LAB.parent / "ch15" / "layers"
if str(LAYERS) not in sys.path:
    sys.path.insert(0, str(LAYERS))

import registry  # noqa: E402  chapter 15's: where every kept run lives and how to read it

ORDER = registry.ORDER
SKELETON_ALIAS = "larkspur-chat-restricted"  # labs/ch09/run_local_golden.py, the --alias default
RESTRICTED_ALIAS = "larkspur-chat-restricted"
MODEL_TAGS = {
    "gpt-oss-20b": "gpt-oss-20b", "gpt-oss:20b": "gpt-oss-20b", "ollama_chat/gpt-oss:20b": "gpt-oss-20b",
    "gemma4-12b": "gemma4-12b", "gemma4:12b": "gemma4-12b", "ollama_chat/gemma4:12b": "gemma4-12b",
    "nova-lite": "nova-lite", "bedrock/converse/ca.amazon.nova-lite-v1:0": "nova-lite",
}
TOOL_CALLS = {
    "skeleton": "every tool call, with its arguments",
    "w1": "the searches the model calls imply",
    "w2": "every read, with whether it returned data",
    "w3": "the reads that returned data",
    "w4": "not kept",
    "w5": "every read in the night's log",
}


@dataclass(frozen=True)
class CostLine:
    run_id: str
    trace_id: str | None
    workflow: str
    gateway_workflow: str
    kept_run: str           # chapter 15's kept run: "<model> <label>"
    case: str
    call: int               # the call's place in the run, from 1
    model: str
    model_tag: str
    alias: str
    served_alias: str
    data_class: str
    input_tokens: int | None
    output_tokens: int | None
    duration_ms: int | None
    fallback: bool
    source: str             # the kept file the line comes from, repository-relative
    # Chapter 15's judge (judge_lines.py): its run (v1, v2, v3), the kept run whose output it read, and the slice.
    # None on the workflows' own lines, and left out of costlines.jsonl there.
    judge: str | None = None
    judged: str | None = None
    judge_slice: str | None = None


JUDGE_FIELDS = ("judge", "judged", "judge_slice")


@dataclass(frozen=True)
class Run:
    run_id: str
    trace_id: str | None
    workflow: str
    model: str              # the kept run's model
    kept_run: str
    case: str
    model_calls: int
    tool_calls: int | None
    seconds: float | None
    passed: bool | None     # the verdict the kept run's results hold
    lines: tuple[CostLine, ...]
    judge: str | None = None  # the judge's run, on a judgment of chapter 15's judge (judge_lines.py)

    @property
    def tokens_kept(self) -> bool:
        return all(line.input_tokens is not None and line.output_tokens is not None for line in self.lines)

    def tokens(self, alias: str | None = None) -> tuple[int, int] | None:
        """Input and output tokens over the run's calls, or over its calls to one alias; None if not kept."""
        if not self.tokens_kept:
            return None
        lines = [line for line in self.lines if alias is None or line.alias == alias]
        return sum(line.input_tokens for line in lines), sum(line.output_tokens for line in lines)


def model_tag(model: str) -> str:
    """The model's short name; a model no kept run used yet fails here, so it gets a name on purpose."""
    return MODEL_TAGS[model]


def _ms(seconds: float | None) -> int | None:
    return None if seconds is None else int(round(seconds * 1000))


def _kept_name(kept: registry.Run) -> str:
    return f"{kept.model} {kept.label}"


def _run_id(workflow: str, kept: registry.Run, case: str, trace_id: str | None) -> str:
    return trace_id or f"{workflow}:{kept.model}:{kept.label}:{case}"


# --- what each workflow's code says, imported -----------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class Context:
    gateway_workflow: str
    data_class: str | None = None
    search_failed: str | None = None


def context(workflow: str) -> Context:
    """The constants the lines need, from the workflows' own modules and manifests."""
    if workflow == "skeleton":
        with registry.loaded("skeleton") as mods:
            fields = {f.name: f.default for f in dataclasses.fields(mods.run_local_golden.GatewayModel)}
        return Context(fields["workflow"], data_class=fields["data_class"])
    gateway_workflow = registry.manifest(workflow)["workflow"]
    if workflow == "w1":
        with registry.loaded("w1") as mods:
            return Context(gateway_workflow, search_failed=mods.answer.SEARCH_FAILED)
    if workflow == "w4":
        with registry.isolated(("workflows/w4-change/a2a",)):
            import rationale_model  # W4's model seam: the class its one call carries
            return Context(gateway_workflow, data_class=rationale_model.DATA_CLASS)
    return Context(gateway_workflow)


# --- one reader per workflow ----------------------------------------------------------------------------

def _skeleton(kept: registry.Run, ctx: Context) -> list[Run]:
    data = registry.read_json(registry.path(kept.main))
    verdicts = registry.stored_verdicts(kept)
    runs = []
    for r in data["results"]:
        run_id = _run_id("skeleton", kept, r["id"], None)
        lines = tuple(CostLine(run_id, None, "skeleton", ctx.gateway_workflow, _kept_name(kept), r["id"], i,
                               kept.model, model_tag(kept.model), SKELETON_ALIAS, SKELETON_ALIAS, ctx.data_class,
                               c["prompt_tokens"], c["completion_tokens"], _ms(c["latency_s"]), False, kept.main)
                      for i, c in enumerate(r["model_calls"], 1))
        runs.append(Run(run_id, None, "skeleton", kept.model, _kept_name(kept), r["id"], len(lines),
                        len(r["calls"]), r["seconds"], verdicts.get(r["id"]), lines))
    return runs


def _labeled(workflow: str, kept: registry.Run, ctx: Context) -> list[Run]:
    """W1 and W2: a label and a usage record per call, and the model each alias was served by."""
    data = registry.read_json(registry.path(kept.main))
    served = data["meta"]["gateway_models"]
    verdicts = registry.stored_verdicts(kept)
    runs = []
    for r in data["results"]:
        case = f"{r['id']}/{r['persona']}" if workflow == "w1" else r["id"]
        labels, usage = r["calls"], r["model_calls"]
        if len(labels) != len(usage):
            raise ValueError(f"{kept.main} {case}: {len(labels)} labels for {len(usage)} calls")
        run_id = _run_id(workflow, kept, case, None)
        lines = tuple(CostLine(run_id, None, workflow, ctx.gateway_workflow, _kept_name(kept), case, i,
                               served[label["alias"]], model_tag(served[label["alias"]]), label["alias"],
                               label["alias"], label["data_class"], u["prompt_tokens"], u["completion_tokens"],
                               _ms(u["latency_s"]), False, kept.main)
                      for i, (label, u) in enumerate(zip(labels, usage), 1))
        if workflow == "w1":  # the searches the calls imply (labs/ch15/layers/trajectory.py, _w1)
            tools = len(usage) if r["answer"] == ctx.search_failed else max(len(usage) - 1, 0)
        else:
            tools = len(r.get("read_events") or [])
        runs.append(Run(run_id, None, workflow, kept.model, _kept_name(kept), case, len(lines), tools,
                        r["seconds"], verdicts.get(case), lines))
    return runs


def _w3(kept: registry.Run, ctx: Context) -> list[Run]:
    data = registry.read_json(registry.path(kept.main))
    verdicts = registry.stored_verdicts(kept)
    runs = []
    for r in data["records"]:
        run_id = _run_id("w3", kept, r["id"], None)
        lines = tuple(CostLine(run_id, None, "w3", ctx.gateway_workflow, _kept_name(kept), r["id"], i,
                               data["model"], model_tag(data["model"]), alias, alias, data_class, None, None,
                               None, False, kept.main)
                      for i, (data_class, alias) in enumerate(r["labels"], 1))
        runs.append(Run(run_id, None, "w3", kept.model, _kept_name(kept), r["id"], len(lines), len(r["reads"]),
                        r.get("seconds"), verdicts.get(r["id"]), lines))
    return runs


def w4_calls_per_change(kept: registry.Run) -> int:
    """The gateway's lines over the changes, from the run's summary; each kept run made one per change."""
    summary = registry.read_json(registry.path(kept.folder) / f"summary-{kept.model}.json")
    calls, changes = summary["gateway_events"]["call"], summary["changes"]
    if calls % changes:
        raise ValueError(f"{kept.folder}: {calls} gateway calls for {changes} changes")
    return calls // changes


def _w4(kept: registry.Run, ctx: Context) -> list[Run]:
    alias = registry.manifest("w4")["models"][0]  # W4's manifest lists one alias, larkspur-chat
    per_change = w4_calls_per_change(kept)
    verdicts = registry.stored_verdicts(kept)
    source = f"{kept.folder}/summary-{kept.model}.json"
    runs = []
    for case, output in registry.outputs(kept).items():
        pack = output["pack"]
        trace = pack.get("trace_id")
        run_id = _run_id("w4", kept, case, trace)
        lines = tuple(CostLine(run_id, trace, "w4", ctx.gateway_workflow, _kept_name(kept), case, i, kept.model,
                               model_tag(kept.model), alias, alias, ctx.data_class, None, None, None, False, source)
                      for i in range(1, per_change + 1))
        runs.append(Run(run_id, trace, "w4", kept.model, _kept_name(kept), case, len(lines), None,
                        pack.get("seconds"), verdicts.get(case), lines))
    return runs


def _w5(kept: registry.Run, ctx: Context) -> list[Run]:
    verdicts = registry.stored_verdicts(kept)
    source = f"{kept.folder}/logs-{kept.model}/gateway.jsonl"
    runs = []
    for case, night in registry.outputs(kept).items():
        record = night["record"]
        trace = record["trace_id"]
        calls = [e for e in night["gateway"] if e.get("event") == "call"]
        lines = tuple(CostLine(trace, trace, "w5", e["workflow"], _kept_name(kept), case, i, e["served_model"],
                               model_tag(e["served_model"]), e["requested_alias"], e["served_alias"],
                               e["data_class"], e["prompt_tokens"], e["completion_tokens"], e.get("latency_ms"),
                               bool(e["fallback"]), source)
                      for i, e in enumerate(calls, 1))
        tools = sum(1 for e in night["events"] if e.get("event") == "tool_call")
        runs.append(Run(trace, trace, "w5", kept.model, _kept_name(kept), case, len(lines), tools,
                        record.get("seconds"), verdicts.get(case), lines))
    return runs


READERS = {"skeleton": _skeleton, "w1": lambda k, c: _labeled("w1", k, c),
           "w2": lambda k, c: _labeled("w2", k, c), "w3": _w3, "w4": _w4, "w5": _w5}


# --- step 3b: the runs through the Collector, priced from the gateway's own lines ------------------------------

TRACED = "traced"
TRACED_MAIN = {"w2": "answers-", "w3": "runs-", "w4": "packs-"}  # the file each workflow's runner writes


def traced_runs(workflow: str) -> list[registry.Run]:
    """Step 3b's runs of a workflow, from its eval/traced/<date>/, in the shape of chapter 15's kept runs."""
    prefix = TRACED_MAIN.get(workflow)
    if prefix is None:
        return []
    runs = []
    for main in sorted((registry.path(registry.RESULTS[workflow]).parent / TRACED).glob(f"*/{prefix}*.json")):
        model = main.stem.removeprefix(prefix)
        files = [main, *sorted((main.parent / f"logs-{model}").glob("*.jsonl"))]
        runs.append(registry.Run(workflow, model, f"{TRACED}/{main.parent.name}", registry.rel(main.parent),
                                 registry.rel(main), tuple(registry.rel(f) for f in files)))
    return runs


def is_traced(run: Run) -> bool:
    """A run step 3b made through the Collector, which chapter 15's registry doesn't hold."""
    return run.kept_run.split(" ", 1)[1].startswith(f"{TRACED}/")


def gateway_calls(kept: registry.Run) -> tuple[list[dict], str]:
    """The gateway's `call` lines of a traced run, and their file, repository-relative."""
    source = f"{kept.folder}/logs-{kept.model}/gateway.jsonl"
    return [e for e in registry.read_jsonl(registry.path(source)) if e.get("event") == "call"], source


def _traced(workflow: str, kept: registry.Run, ctx: Context) -> list[Run]:
    """Each case of a traced run, its lines the gateway's own with its trace id, in order, as W5's are read."""
    calls, source = gateway_calls(kept)
    verdicts = registry.stored_verdicts(kept)
    data = registry.read_json(registry.path(kept.main))
    folder = registry.path(kept.folder)
    if workflow == "w2":  # each line of the harness's log names its case and its trace id
        trace_of: dict[str, str] = {}
        for entry in registry.read_jsonl(folder / f"logs-{kept.model}" / "harness.jsonl"):
            trace_of.setdefault(entry["case"], entry["trace_id"])
        cases = [(r["id"], trace_of[r["id"]], len(r["read_events"]), r["seconds"]) for r in data["results"]]
    elif workflow == "w3":  # W3's record keeps no trace id: the run kept each incident's beside it
        traces = registry.read_json(folder / f"trace-ids-{kept.model}.json")
        cases = [(r["id"], traces[r["id"]], len(r["reads"]), r.get("seconds")) for r in data["records"]]
    else:
        cases = [(case, pack["trace_id"], None, pack.get("seconds")) for case, pack in data.items()]
    runs = []
    for case, trace, tools, seconds in cases:
        lines = tuple(CostLine(trace, trace, workflow, e["workflow"], _kept_name(kept), case, i, e["served_model"],
                               model_tag(e["served_model"]), e["requested_alias"], e["served_alias"], e["data_class"],
                               e["prompt_tokens"], e["completion_tokens"], e.get("latency_ms"), bool(e["fallback"]), source)
                      for i, e in enumerate((e for e in calls if e["trace_id"] == trace), 1))
        runs.append(Run(trace, trace, workflow, kept.model, _kept_name(kept), case, len(lines), tools, seconds,
                        verdicts.get(case), lines))
    return runs


def collect(workflows: Iterable[str] = ORDER) -> list[Run]:
    """Every run of every kept run, in the registry's order (workflow, model, kept run, case), each workflow's
    step 3b runs after its kept ones."""
    runs: list[Run] = []
    for workflow in workflows:
        ctx = context(workflow)
        for kept in registry.kept_runs(workflow):
            runs += sorted(READERS[workflow](kept, ctx), key=lambda r: r.case)
        for kept in traced_runs(workflow):
            runs += sorted(_traced(workflow, kept, ctx), key=lambda r: r.case)
    return runs


def lines(runs: Iterable[Run]) -> list[CostLine]:
    return [line for run in runs for line in run.lines]


def as_record(line: CostLine) -> dict[str, Any]:
    """The line as written: the judge's fields only on the judge's lines, so the workflows' lines are as they were."""
    return {k: v for k, v in asdict(line).items() if k not in JUDGE_FIELDS or v is not None}


def write_jsonl(runs: Iterable[Run], path: Path) -> int:
    """Every cost line, one JSON object a line, in the runs' order; LF on every platform."""
    out = [json.dumps(as_record(line)) for line in lines(runs)]
    path.write_text("".join(f"{line}\n" for line in out), encoding="utf-8", newline="\n")
    return len(out)


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, help="write every cost line to this JSON Lines file")
    args = parser.parse_args(argv)
    runs = collect()
    if args.out:
        print(f"{write_jsonl(runs, args.out)} cost lines in {args.out}")
    for workflow in ORDER:
        mine = [r for r in runs if r.workflow == workflow]
        calls = sum(r.model_calls for r in mine)
        kept = sum(1 for r in mine for line in r.lines if line.input_tokens is not None)
        print(f"{workflow:9s} {len(mine):4d} runs {calls:5d} calls, {kept:5d} with tokens")
    return 0


if __name__ == "__main__":
    sys.exit(main())
