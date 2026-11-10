"""Chapter 15's judge in the ledger (step 9): every judgment counted once and the totals chapter 15's own, each a
cost line under the workflow judged and marked as the judge's, the judge's lines written after the workflows' lines
and nothing else in the committed ledger moved, the judged outputs' tokens the kept runs' own or step 3b's stand-in,
the ratios pinned, the judge's lines priced like any line, and the layout chapter 15's."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest

import costlines
import judge_lines
import price
import registry

LAB = Path(__file__).resolve().parents[1]
RESULTS = LAB / "results" / "2026-11-03"
OWN_LINES = 1189          # the workflows' own cost lines, as step 3b left them
OLD_SUMMARY_BYTES = 41817  # ledger-summary.md before section 14
# The three files as committed before step 9 (the 546-test suite): the judge's lines may only add to them.
BEFORE = {"ledger.json": "b72831aa52f99be65811ac45ec12318cb3e635016992f72a85219e1472fe3c48",
          "costlines.jsonl": "6914538221a3b01f98b677c048b542f4a564e02b58b8575c370002434012befc",
          "ledger-summary.md": "80d0edfe3f0cc69795f12d57a3b65204ebae1a71782321f651d744de0155aa37"}
CH15 = {"calls": 1439, "prompt": 1_231_927, "completion": 338_238}  # chapter 15's README and digest: the three runs
BY_RUN = {("v1", "gemma4-12b"): (360, 321_810, 10_799), ("v1", "gpt-oss-20b"): (240, 210_383, 139_746),
          ("v2", "gemma4-12b"): (360, 322_176, 10_828), ("v2", "gpt-oss-20b"): (240, 210_805, 138_566),
          ("v3", "gemma4-12b"): (152, 105_984, 4_078), ("v3", "gpt-oss-20b"): (87, 60_769, 34_221)}
RATIOS = {  # the judge's tokens over the judged outputs', prompt / completion / total, per workflow and judge
    ("w1", "gemma4-12b"): ("measured", 165, (0.253, 0.0939, 0.2379)),
    ("w1", "gpt-oss-20b"): ("measured", 171, (0.2326, 1.3844, 0.3303)),
    ("w2", "gemma4-12b"): ("measured", 222, (0.301, 0.0823, 0.2733)),
    ("w2", "gpt-oss-20b"): ("measured", 90, (0.2576, 1.8279, 0.3743)),
    ("w3", "gemma4-12b"): ("stand-in", 69, (0.083, 0.0424, 0.0802)),
    ("w4", "gemma4-12b"): ("stand-in", 54, (2.7629, 0.1552, 1.5114)),
    ("w4", "gpt-oss-20b"): ("stand-in", 32, (3.6226, 3.5954, 3.6135)),
    ("w5", "gemma4-12b"): ("measured", 362, (1.733, 0.0387, 0.7705)),
    ("w5", "gpt-oss-20b"): ("measured", 274, (1.5662, 2.9562, 1.9485)),
}


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture(scope="module")
def judged() -> list[judge_lines.Judgment]:
    return judge_lines.judgments()


@pytest.fixture(scope="module")
def judge_runs() -> list[costlines.Run]:
    return judge_lines.collect()


@pytest.fixture(scope="module")
def section(runs, table) -> dict:
    return judge_lines.section(runs, table)


def test_every_judgment_is_counted_once_and_the_totals_are_chapter_15s(judged):
    assert len(judged) == CH15["calls"] == len({j.line["trace_id"] for j in judged})
    assert sum(j.line["prompt_tokens"] for j in judged) == CH15["prompt"]
    assert sum(j.line["completion_tokens"] for j in judged) == CH15["completion"]
    by_run = {}
    for j in judged:
        n, p, c = by_run.get((j.run, j.judge), (0, 0, 0))
        by_run[(j.run, j.judge)] = (n + 1, p + j.line["prompt_tokens"], c + j.line["completion_tokens"])
    assert by_run == BY_RUN
    assert Counter(j.line["workflow"] for j in judged) == {"w1-knowledge": 336, "w2-ops-assistant": 312, "w3-incident": 69,
                                                           "w4-change": 86, "w5-drift": 636}
    assert Counter(j.slice for j in judged) == {"cross": 1227, "self": 120, "padded": 92}
    assert all(j.line["event"] == "call" and not j.line["fallback"] for j in judged)


def test_each_judgment_is_one_line_under_the_workflow_judged_and_marked_as_the_judges(judge_runs, runs):
    assert len(judge_runs) == CH15["calls"]
    kept = {(r.workflow, r.kept_run) for r in runs}
    for r in judge_runs:
        assert len(r.lines) == 1 and r.model_calls == 1 and r.judge in ("v1", "v2", "v3")
        line = r.lines[0]
        assert line.judge == r.judge and line.judge_slice in judge_lines.SLICES and (r.workflow, line.judged) in kept
        assert line.kept_run == f"{r.model} judge/{r.judge}"
        assert r.model in judge_lines.JUDGES
        assert line.model_tag == r.model and line.workflow == r.workflow
        assert line.gateway_workflow == registry.manifest(r.workflow)["workflow"]
        assert line.trace_id == line.run_id == r.run_id and line.input_tokens is not None and line.output_tokens is not None
    # the workflows' own runs carry none of it, so cost per run, the month, and the allocation are theirs alone
    assert all(r.judge is None and all(line.judge is line.judged is line.judge_slice is None for line in r.lines) for r in runs)
    assert judge_runs == sorted(judge_runs, key=lambda r: (r.judge, judge_lines.WORKFLOWS.index(r.workflow), r.model, r.case))


def test_the_judges_lines_follow_the_workflows_lines_and_only_they_carry_the_fields():
    lines = (RESULTS / "costlines.jsonl").read_text(encoding="utf-8").replace("\r\n", "\n").splitlines()
    assert len(lines) == OWN_LINES + CH15["calls"]
    own, theirs = lines[:OWN_LINES], lines[OWN_LINES:]
    assert sha256("\n".join(own) + "\n") == BEFORE["costlines.jsonl"]  # the workflows' lines, byte for byte as before
    fields = [f.name for f in dataclasses.fields(costlines.CostLine)]
    for line in own:
        assert list(json.loads(line)) == [f for f in fields if f not in costlines.JUDGE_FIELDS]
    for line in theirs:
        record = json.loads(line)
        assert list(record) == fields and record["judge"] in ("v1", "v2", "v3") and record["judged"] and record["judge_slice"]
    assert [json.loads(line)["judge"] for line in theirs] == sorted(json.loads(line)["judge"] for line in theirs)


def test_nothing_else_in_the_committed_ledger_moved():
    data = json.loads((RESULTS / "ledger.json").read_text(encoding="utf-8"))
    assert list(data)[-1] == "judge"
    without = {k: v for k, v in data.items() if k != "judge"}
    assert sha256(json.dumps(without, indent=1, default=str) + "\n") == BEFORE["ledger.json"]
    summary = (RESULTS / "ledger-summary.md").read_bytes().replace(b"\r\n", b"\n")  # bytes: the table holds "Montréal"
    assert hashlib.sha256(summary[:OLD_SUMMARY_BYTES - 1] + b"\n").hexdigest() == BEFORE["ledger-summary.md"]
    assert summary[OLD_SUMMARY_BYTES - 1:].startswith(b"\n\n## 14. The judge's tokens, under the workflow judged")
    assert data["judge"]["calls"] == CH15["calls"] and data["judge"]["current_log_lines_also_in_a_kept_run"] == 361


def test_the_judged_outputs_tokens_are_the_kept_runs_own_or_step_3bs_stand_in(section, runs):
    by = {(r["workflow"], r["judge"]): r for r in section["by_workflow"]}
    for (workflow, judge), (basis, judgments, _) in RATIOS.items():
        row = by[(workflow, judge)]
        other = "stand-in" if basis == "measured" else "measured"
        assert row["judgments"] == row[basis]["judgments"] == judgments and row[other]["judgments"] == 0
        assert row["without_tokens"] == 0
    assert ("w3", "gpt-oss-20b") not in by  # W3's kept run is gpt-oss-20b's, and E-D4 has the other model judge it
    assert section["judged_outputs_basis"]["w3"] == section["judged_outputs_basis"]["w4"] == "stand-in"
    bodies = judge_lines.w5_bodies(runs)
    assert len(bodies) == sum(len(r.lines) for r in runs if r.workflow == "w5") == 341  # one call a body, every night
    outputs = judge_lines.Outputs(runs)
    w5 = next(j for j in judge_lines.judgments() if j.workflow == "w5")
    read = outputs.of(w5)
    assert read.basis == "measured" and (read.input_tokens, read.output_tokens) == (bodies[(w5.judged, w5.case, w5.part)].input_tokens,
                                                                                    bodies[(w5.judged, w5.case, w5.part)].output_tokens)


def test_the_ratios_and_where_chapter_15s_sentence_holds(section):
    by = {(r["workflow"], r["judge"]): r for r in section["by_workflow"]}
    for (workflow, judge), (basis, _, (p, c, t)) in RATIOS.items():
        assert by[(workflow, judge)][basis]["ratio"] == {"prompt": p, "completion": c, "total": t}, (workflow, judge)
    sentence = {(s["workflow"], s["judge"]): s for s in section["sentence"]}
    assert set(sentence) == set(RATIOS)
    reasoning = {w: s for (w, j), s in sentence.items() if j == "gpt-oss-20b"}
    # in total: the reasoning judge writes more completion tokens than the outputs it read, in every workflow it judged
    assert all(s["more_completion"] for s in reasoning.values()) and set(reasoning) == {"w1", "w2", "w4", "w5"}
    assert {w for w, s in reasoning.items() if s["more_than_the_output"]} == {"w4", "w5"}  # in all tokens, only W4 and W5
    other = {w: s for (w, j), s in sentence.items() if j == "gemma4-12b"}
    assert not any(s["more_completion"] for s in other.values())
    assert {w for w, s in other.items() if s["more_than_the_output"]} == {"w4"}
    assert section["by_judge"][-1]["judge"] == "both" and section["by_judge"][-1]["judgments"] == CH15["calls"]


def test_the_two_populations_of_the_median_are_the_three_runs_and_the_current_files(section):
    """551 and 559 are two populations: the ledger's three runs' judgments (567 for gpt-oss-20b) and chapter 15's
    current log (240 calls), which is where its README and ch15:156 get 559 and 29."""
    by = {r["judge"]: r for r in section["by_judge"]}
    assert (by["gpt-oss-20b"]["judgments"], by["gpt-oss-20b"]["completion_median"]) == (567, 551)
    assert (by["gemma4-12b"]["judgments"], by["gemma4-12b"]["completion_median"]) == (872, 29)
    assert section["current_files"] == {"gemma4-12b": {"calls": 360, "prompt_median": 976.0, "completion_median": 29.0},
                                        "gpt-oss-20b": {"calls": 240, "prompt_median": 951.0, "completion_median": 559.0}}
    # the ledger's 567 are the three runs' judgments (240 + 240 + 87); the current log's 240 calls are one log's lines
    assert sum(1 for j in judge_lines.judgments() if j.judge == "gpt-oss-20b") == 567 == 240 + 240 + 87


def test_the_think_flags_are_what_the_result_files_record(section, judged):
    assert section["thinking"] == {"gemma4-12b": False, "gpt-oss-20b": "model default"}
    assert section["tag_is_the_judged_workflows"] == CH15["calls"] and section["measured"] == ["2026-11-03"]
    assert judge_lines.thinking_of(judged) == section["thinking"]
    gemma = next(j for j in judged if j.judge == "gemma4-12b")
    assert judge_lines.thinking_of([dataclasses.replace(gemma, thinking="model default"), *judged])["gemma4-12b"] == "varies"
    assert judge_lines.thinking_of([j for j in judged if j.judge == "gpt-oss-20b"]) == {"gpt-oss-20b": "model default"}


def test_the_sentence_is_counted_by_judgment_and_every_output_is_not_claimed(section):
    """In total, gpt-oss-20b's completion tokens exceed the outputs' in all four workflows it judged; judgment by
    judgment they do not always, so no page may say "every output it judges"."""
    counts = {}
    for r in section["by_workflow"]:
        if r["judge"] == "both":
            continue
        counts[(r["workflow"], r["judge"])] = (r["judgments"], (r["measured"] if r["measured"]["judgments"] else r["stand-in"])["completion_over"])
    assert {k: v for k, v in counts.items() if k[1] == "gpt-oss-20b"} == {
        ("w1", "gpt-oss-20b"): (171, 117), ("w2", "gpt-oss-20b"): (90, 84), ("w4", "gpt-oss-20b"): (32, 27),
        ("w5", "gpt-oss-20b"): (274, 254)}
    assert {k: v for k, v in counts.items() if k[1] == "gemma4-12b" and v[1]} == {("w4", "gemma4-12b"): (54, 6)}
    assert all(over < n for (_, judge), (n, over) in counts.items() if judge == "gpt-oss-20b")
    c = section["conclusion"]
    assert c["thinking_on"] == ["gpt-oss-20b"] and c["thinking_off"] == ["gemma4-12b"]
    assert c["completion_in_total"]["gpt-oss-20b"] == {"above": ["w1", "w2", "w4", "w5"], "not_above": []}
    assert c["completion_in_total"]["gemma4-12b"] == {"above": [], "not_above": ["w1", "w2", "w3", "w4", "w5"]}
    assert c["all_tokens_in_total"]["gpt-oss-20b"]["above"] == ["w4", "w5"]
    assert c["all_tokens_in_total"]["gemma4-12b"]["above"] == ["w4"]
    assert c["not_judged_by"] == {"gemma4-12b": {}, "gpt-oss-20b": {"w3": ["gemma4-12b"]}}  # W3 had no reasoning judge
    assert [r["workflow"] for r in c["by_judge"]["gpt-oss-20b"]] == ["w1", "w2", "w4", "w5"]


def row(workflow, judge, completion, total, judgments=10, over=10, basis="measured"):
    return {"workflow": workflow, "judge": judge, "basis": basis, "judgments": judgments, "completion_over": over,
            "total_over": over, "ratio": {"prompt": 1.0, "completion": completion, "total": total}}


def test_the_conclusion_follows_the_rows_it_is_given_and_the_phrases_say_no_more_than_they_hold():
    sentence = [row("w1", "gpt-oss-20b", 2.0, 0.5), row("w2", "gpt-oss-20b", 0.8, 0.3, basis="stand-in"),
                row("w1", "gemma4-12b", 0.1, 0.1), row("w3", "gemma4-12b", 0.1, 0.2)]
    c = judge_lines.conclusion(sentence, {"gemma4-12b": False, "gpt-oss-20b": True})
    assert (c["thinking_on"], c["thinking_off"]) == (["gpt-oss-20b"], ["gemma4-12b"])  # a flag that is not False is thinking on
    assert c["completion_in_total"]["gpt-oss-20b"] == {"above": ["w1"], "not_above": ["w2"]}
    assert c["not_judged_by"] == {"gemma4-12b": {"w2": ["gpt-oss-20b"]}, "gpt-oss-20b": {"w3": ["gemma4-12b"]}}
    rows = c["by_judge"]["gpt-oss-20b"]
    assert judge_lines.more_or_fewer(rows, ["w1"]) == "more than the outputs it read in W1 and fewer in W2"
    assert judge_lines.more_or_fewer(rows, ["w1", "w2"]) == "more than the outputs it read in every workflow it judged"
    assert judge_lines.more_or_fewer(rows, []) == "fewer than the outputs it read in every workflow it judged"
    assert judge_lines.ratios_text(rows, "completion") == "W1 (2.00) and W2 (0.80, on the stand-in)"
    assert judge_lines.sides_text(rows, ["w1"]) == "above the output's for W1 (0.50) and below it for W2 (0.30, on the stand-in)"
    assert judge_lines.sides_text(rows, []) == "below the output's for W1 (0.50) and W2 (0.30, on the stand-in)"
    assert judge_lines.alone_text({"w3": ["gemma4-12b"]}) == "W3 was judged by Gemma 4 12B alone"
    assert judge_lines.alone_text({"w3": ["gemma4-12b"], "w5": ["gemma4-12b"]}) == "W3 and W5 were judged by Gemma 4 12B alone"
    assert judge_lines.over_text([row("w1", "gpt-oss-20b", 2.0, 0.5, judgments=171, over=117)]) == "117 of 171 W1 judgments"
    assert judge_lines.over_text([row("w1", "gemma4-12b", 0.1, 0.1, over=0)]) == "none of its judgments"
    assert judge_lines.join([]) == "none" and judge_lines.join(["a"]) == "a" and judge_lines.join(["a", "b", "c"]) == "a, b and c"
    # a judge that wrote above the output's in no workflow it judged is not credited with the sentence
    assert judge_lines.conclusion([row("w1", "gpt-oss-20b", 0.9, 0.5)], {"gpt-oss-20b": True})[
        "completion_in_total"]["gpt-oss-20b"]["above"] == []


def test_the_judges_lines_are_priced_like_any_line(judge_runs, table, section):
    total = Decimal(0)
    for r in judge_runs:
        line = r.lines[0]
        cost = price.line_cost(table, line)
        assert cost is not None
        if line.alias == costlines.RESTRICTED_ALIAS:
            assert cost == 0
        else:
            assert cost > 0
        total += cost
    both = next(r for r in section["by_judge"] if r["judge"] == "both")
    assert both["usd"] == pytest.approx(float(total), abs=1e-6)
    assert Counter(r.lines[0].alias for r in judge_runs) == {"larkspur-chat": 1209, costlines.RESTRICTED_ALIAS: 230}


def test_the_layout_is_chapter_15s_own(section):
    assert section["folder"] == "labs/ch15/results/2026-11-03"
    layout = {r["run"]: r for r in section["layout"]}
    assert list(layout) == ["v1", "v2", "v3"]
    assert layout["v1"]["place"].endswith("/judge-v1") and len(layout["v1"]["files"]) == 10
    assert layout["v2"]["place"].endswith("/judge-v2") and len(layout["v2"]["files"]) == 10  # its six, and W4's and W5's current files
    assert layout["v3"]["place"] == section["folder"] and len(layout["v3"]["files"]) == 6
    assert {name: run for name, run in section["origins"].items() if name.startswith(("judge-w4", "judge-w5"))} == \
        {f"judge-w{n}-{j}.json": "v2" for n in (4, 5) for j in judge_lines.JUDGES}
    assert section["by_alias_and_class"] == {"larkspur-chat-restricted/restricted": 230, "larkspur-chat/confidential": 782,
                                             "larkspur-chat/internal": 312, "larkspur-chat/restricted": 115}
