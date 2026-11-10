"""The cost lines: every model call of every kept run is one line, of one shape from each workflow, and
the lines agree with what each workflow's own files count. Step 3b's runs through the Collector are read from
each workflow's eval/traced/, their lines the gateway's own, and chapter 15's registry still holds its own runs."""

from __future__ import annotations

import dataclasses

import pytest

import costlines
import registry

RUNS = {"skeleton": 40, "w1": 75, "w2": 110, "w3": 24, "w4": 32, "w5": 33}  # chapter 15's kept runs
KEPT = {"skeleton": 2, "w1": 3, "w2": 5, "w3": 1, "w4": 4, "w5": 11}  # chapter 15's tests/test_replay.py
TRACED = {"w2": 25, "w3": 24, "w4": 16}  # step 3b: W2's golden set, W3's incidents, W4's changes on two models


def counted_calls(workflow: str) -> int:
    """The model calls each workflow's own files count, read without the ledger."""
    total = 0
    for kept in registry.kept_runs(workflow):
        data = registry.read_json(registry.path(kept.main))
        if workflow in ("skeleton", "w1", "w2"):
            total += sum(len(r["model_calls"]) for r in data["results"])
        elif workflow == "w3":
            total += sum(len(r["labels"]) for r in data["records"])
        elif workflow == "w4":
            total += registry.read_json(registry.path(kept.folder) / f"summary-{kept.model}.json")["gateway_events"]["call"]
        else:
            total += sum(n["record"]["cost"]["gateway_calls"] for n in registry.outputs(kept).values())
    return total


def test_every_output_of_every_kept_run_is_a_run_and_every_call_a_line(runs) -> None:
    for workflow, count in RUNS.items():
        mine = [r for r in runs if r.workflow == workflow and not costlines.is_traced(r)]
        outputs = sum(len(registry.outputs(kept)) for kept in registry.kept_runs(workflow))
        assert len(mine) == count == outputs, workflow
        assert sum(len(r.lines) for r in mine) == sum(r.model_calls for r in mine) == counted_calls(workflow), workflow
    traced = [r for r in runs if costlines.is_traced(r)]
    assert {w: sum(1 for r in traced if r.workflow == w) for w in TRACED} == TRACED
    assert len(runs) == 314 + 65 and len(costlines.lines(runs)) == 982 + sum(len(r.lines) for r in traced)
    assert len({r.run_id for r in runs}) == len(runs)


def test_step_3b_s_runs_stay_out_of_chapter_15_s_registry() -> None:
    """In eval/results/ the four runs would have become chapter 15's 27th to 30th, which its replay never saw."""
    assert {w: len(registry.kept_runs(w)) for w in KEPT} == KEPT
    assert not any("traced" in kept.folder for w in KEPT for kept in registry.kept_runs(w))
    traced = {w: [(k.model, k.label, k.folder) for k in costlines.traced_runs(w)] for w in registry.ORDER}
    assert traced == {"skeleton": [], "w1": [], "w5": [],
                      "w2": [("gpt-oss-20b", "traced/2026-11-03", "workflows/w2-ops-assistant/eval/traced/2026-11-03")],
                      "w3": [("gpt-oss-20b", "traced/2026-11-03", "workflows/w3-incident/eval/traced/2026-11-03")],
                      "w4": [("gemma4-12b", "traced/2026-11-03", "workflows/w4-change/eval/traced/2026-11-03"),
                             ("gpt-oss-20b", "traced/2026-11-03", "workflows/w4-change/eval/traced/2026-11-03")]}


def test_step_3b_s_lines_are_the_gateway_s_own_one_per_call_joined_by_trace_id(runs) -> None:
    for workflow in TRACED:
        for kept in costlines.traced_runs(workflow):
            calls, source = costlines.gateway_calls(kept)
            mine = [r for r in runs if r.workflow == workflow and r.kept_run == f"{kept.model} {kept.label}"]
            assert sum(len(r.lines) for r in mine) == len(calls) > 0, kept.main  # every call the gateway logged
            data = registry.read_json(registry.path(kept.main))
            if workflow == "w2":
                expected = {r["id"]: [(c["prompt_tokens"], c["completion_tokens"]) for c in r["model_calls"]] for r in data["results"]}
            elif workflow == "w3":
                expected = {r["id"]: len(r["labels"]) for r in data["records"]}
            else:
                expected = {case: 1 for case in data}
            if workflow == "w2":  # the harness's own record of each call's usage is the gateway's line
                assert {r.case: [(line.input_tokens, line.output_tokens) for line in r.lines] for r in mine} == expected
            else:
                assert {r.case: r.model_calls for r in mine} == expected
            for r in mine:
                assert r.trace_id == r.run_id and len(r.trace_id) == 32 and r.tokens_kept, r.case
                assert all(line.source == source and line.duration_ms is not None and line.trace_id == r.trace_id
                           and line.model_tag == kept.model for line in r.lines), r.case


def test_one_shape_from_each_workflow(runs) -> None:
    fields = {f.name for f in dataclasses.fields(costlines.CostLine)}
    seen = {}
    for run in runs:
        for line in run.lines:
            assert set(dataclasses.asdict(line)) == fields
            assert line.run_id == run.run_id and line.workflow == run.workflow and line.case == run.case
            assert isinstance(line.fallback, bool) and line.alias and line.data_class and line.model_tag
            seen.setdefault(run.workflow, line)
    assert set(seen) == set(RUNS)
    sk, w1, w2, w3, w4, w5 = (seen[w] for w in ("skeleton", "w1", "w2", "w3", "w4", "w5"))
    assert (sk.alias, sk.data_class, sk.gateway_workflow) == ("larkspur-chat-restricted", "internal", "w2-ops-assistant")
    assert sk.input_tokens and sk.duration_ms is not None and sk.trace_id is None
    assert w1.gateway_workflow == "w1-knowledge" and w1.input_tokens and w1.run_id.startswith("w1:")
    assert w2.gateway_workflow == "w2-ops-assistant" and w2.duration_ms is not None
    assert w3.input_tokens is None and w3.output_tokens is None and w3.duration_ms is None
    assert w4.trace_id == w4.run_id and len(w4.trace_id) == 32 and w4.data_class == "internal" and w4.input_tokens is None
    assert w5.trace_id == w5.run_id and w5.gateway_workflow == "w5-drift" and w5.input_tokens is not None
    traced = {run.workflow: run.lines[0] for run in runs if costlines.is_traced(run) and run.lines}
    assert {w: (line.gateway_workflow, line.input_tokens is not None, line.trace_id == line.run_id)
            for w, line in traced.items()} == {"w2": ("w2-ops-assistant", True, True), "w3": ("w3-incident", True, True),
                                               "w4": ("w4-change", True, True)}


def test_the_nova_lite_run_records_the_model_each_alias_was_served_by(runs) -> None:
    nova = [line for r in runs if r.workflow == "w1" and r.model == "nova-lite" for line in r.lines]
    managed = {line.model for line in nova if line.alias == "larkspur-chat"}
    restricted = {line.model for line in nova if line.alias == "larkspur-chat-restricted"}
    assert managed == {"bedrock/converse/ca.amazon.nova-lite-v1:0"} and restricted == {"ollama_chat/gpt-oss:20b"}
    assert {line.model_tag for line in nova} == {"nova-lite", "gpt-oss-20b"}


def test_w5s_lines_are_the_nights_own_count(runs) -> None:
    for kept in registry.kept_runs("w5"):
        nights = registry.outputs(kept)
        for run in (r for r in runs if r.workflow == "w5" and r.kept_run == f"{kept.model} {kept.label}"):
            cost = nights[run.case]["record"]["cost"]
            assert run.model_calls == cost["gateway_calls"]
            assert run.tokens() == (cost["prompt_tokens"], cost["completion_tokens"])


def test_w4_made_one_call_per_change() -> None:
    assert {costlines.w4_calls_per_change(kept) for kept in registry.kept_runs("w4")} == {1}


def test_tool_calls_are_counted_where_kept_and_none_where_not(runs) -> None:
    by = {w: [r.tool_calls for r in runs if r.workflow == w] for w in RUNS}
    assert all(t is None for t in by["w4"])
    assert all(isinstance(t, int) for w in ("skeleton", "w1", "w2", "w3", "w5") for t in by[w])
    w1 = [r for r in runs if r.workflow == "w1"]
    assert all(r.tool_calls == max(r.model_calls - 1, 0) for r in w1)  # no kept search failed
    assert set(costlines.TOOL_CALLS) == set(RUNS)


def test_no_kept_call_took_a_fallback(runs) -> None:
    assert not any(line.fallback for line in costlines.lines(runs))
    assert all(line.served_alias == line.alias for line in costlines.lines(runs))


def test_a_model_no_kept_run_used_gets_no_tag_by_guess() -> None:
    with pytest.raises(KeyError):
        costlines.model_tag("anthropic.claude-haiku-5-5")
