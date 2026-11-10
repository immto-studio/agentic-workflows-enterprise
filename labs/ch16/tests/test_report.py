"""Per workflow and model, W2 against chapter 3, and the token counts across models on W1's set."""

from __future__ import annotations

import report
import tokens


def test_nearest_rank_picks_a_value_some_run_had() -> None:
    values = list(range(1, 21))
    assert report.nearest_rank(values, 0.95) == 19 and report.nearest_rank(values, 0.5) == 10
    assert report.nearest_rank([7], 0.95) == 7
    assert report.describe([1, 2, None]) is None


def test_every_workflow_and_model_has_a_row(runs, table) -> None:
    rows = report.per_workflow_model(runs, table, {"gpt-oss-20b": {"input": 1.0, "output": 1.0},
                                                   "gemma4-12b": {"input": 1.0, "output": 1.0}})
    assert [(r["workflow"], r["model"]) for r in rows] == [
        ("skeleton", "gemma4-12b"), ("skeleton", "gpt-oss-20b"), ("w1", "gemma4-12b"), ("w1", "gpt-oss-20b"),
        ("w1", "nova-lite"), ("w2", "gemma4-12b"), ("w2", "gpt-oss-20b"), ("w3", "gpt-oss-20b"),
        ("w4", "gemma4-12b"), ("w4", "gpt-oss-20b"), ("w5", "gemma4-12b"), ("w5", "gpt-oss-20b")]
    by = {(r["workflow"], r["model"]): r for r in rows}
    # Tokens and cost from the runs that kept them: for W3 and W4, step 3b's alone.
    assert {key: (by[key]["runs"], by[key]["runs_with_tokens"]) for key in (("w3", "gpt-oss-20b"), ("w4", "gpt-oss-20b"),
                                                                          ("w4", "gemma4-12b"))} == {
        ("w3", "gpt-oss-20b"): (48, 24), ("w4", "gpt-oss-20b"): (32, 8), ("w4", "gemma4-12b"): (16, 8)}
    for key in (("w3", "gpt-oss-20b"), ("w4", "gpt-oss-20b"), ("w4", "gemma4-12b")):
        assert by[key]["cost_usd"]["median"] > 0 and by[key]["input_tokens"]["median"] > 0
    assert all(r["runs_with_tokens"] == r["runs"] for r in rows if r["workflow"] not in ("w3", "w4"))
    assert by[("skeleton", "gpt-oss-20b")]["cost_usd"]["p95"] == 0  # the restricted alias, zero per token
    for r in rows:
        if r["cost_usd"] and r["recounted_as_nova_lite_usd"]:
            assert r["recounted_as_nova_lite_usd"]["mean"] == r["cost_usd"]["mean"]  # ratios of one recount nothing
        if r["cost_pct_of_run_budget"]:
            assert r["cost_pct_of_run_budget"]["p95"] < 5


def test_w2s_median_is_chapter_3s_two_model_calls_and_one_tool_call(runs) -> None:
    check = report.w2_against_chapter_3(runs)
    assert (check["all"]["runs"], check["answers"]["runs"]) == (135, 108)  # step 3b's run of the golden set among them
    assert len(check["by_kept_run"]) == 6 and "gpt-oss-20b traced/2026-11-03" in check["by_kept_run"]
    for group in (check["all"], check["answers"], check["skeleton"], *check["by_kept_run"].values()):
        assert (group["model_calls"], group["tool_calls"]) == (2, 1)
    assert check["all"]["model_calls_counts"][2] == 77 and check["all"]["tool_calls_counts"][1] == 94


def test_chapter_11s_prompt_sizes(runs) -> None:
    """ch11:361: about 850 and 1,000 prompt tokens on gpt-oss-20b, about 1,000 and 1,200 on Gemma 4 12B."""
    measured = report.w2_against_chapter_3(runs)["ch11_361_first_two_prompts"]["measured_medians"]
    for model, stated in (("gpt-oss-20b", (850, 1000)), ("gemma4-12b", (1000, 1200))):
        for got, want in zip(measured[model], stated):
            assert abs(got - want) / want < 0.05, (model, got, want)


def test_the_token_counts_across_models_on_w1s_set(runs) -> None:
    t = tokens.compare(runs)
    assert (t["cases"], t["compared"], t["same_number_of_calls"]) == (25, 17, 17)
    assert t["left_out_restricted"] == ["gq-01/vault.custodian", "gq-02/pci.operator", "gq-03/incident.responder"]
    assert list(t["left_out_unanswered"]) == ["gpt-oss-20b"] and len(t["left_out_unanswered"]["gpt-oss-20b"]) == 5
    for row in t["per_case"]:
        assert len({row[m]["calls"] for m in tokens.MODELS}) == 1
    nova = t["ratios"]["nova-lite/gpt-oss-20b"]
    assert nova["input"]["of_totals"] == 1.3638 and nova["output"]["of_totals"] == 0.5381
    assert nova["first_input"]["min"] > 1.6  # the same text: the tokenizer and the template alone
    gemma = t["ratios"]["nova-lite/gemma4-12b"]
    assert (gemma["input"]["of_totals"], gemma["output"]["of_totals"]) == (1.3352, 0.5279)
