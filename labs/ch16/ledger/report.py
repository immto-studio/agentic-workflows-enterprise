"""The ledger of step 2, computed from the kept runs and written as the summary, its JSON, and the lines.

Chapter 16, step 2 (companion #14, O-D5, O-D6). Per workflow and model: model calls and tool calls per
run, tokens per run, cost per run, and cost per run as a share of the manifest's per_run_usd, each as a
median and a 95th percentile (nearest rank, so every value is one a run had). W2's runs against chapter
3's median (ch03:58). Then the rest of the step, from the other modules: the token counts across models
(tokens.py), the custom prices in LiteLLM (price.py) and its built-in map (litellm_map.py), the month and
the allocation (month.py), and the sampling drift (sampling.py).

The two LiteLLM checks run in processes of their own, with LITELLM_LOCAL_MODEL_COST_MAP=True and the
network blocked, because a Router changes LiteLLM's price map for the rest of the process. This process
blocks the network too. Nothing written holds a time or a path of this machine, so two runs write the same
bytes.

Step 9 adds chapter 15's judge (judge_lines.py): its judgments as cost lines under the workflow judged, written after
the workflows' own lines in costlines.jsonl and marked as the judge's, the judge's tokens against the tokens of the
outputs it judged as the summary's last section, and nothing else changed: cost per run, the month, and the allocation
read the workflows' own runs alone.

Writes results/<date>/ledger-summary.md, ledger.json (every table's data) and costlines.jsonl (every cost
line). Run (from labs/ch16):  python ledger/report.py --out results/2026-11-03
"""

from __future__ import annotations

import json
import math
import os
import statistics
import subprocess
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
LAB = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import costlines  # noqa: E402
import judge_lines  # noqa: E402
import month as months  # noqa: E402
import offline  # noqa: E402
import price  # noqa: E402
import registry  # noqa: E402
import render  # noqa: E402
import sampling  # noqa: E402
import tokens  # noqa: E402

CHILD_ENV = {"LITELLM_LOCAL_MODEL_COST_MAP": "True", "LEDGER_OFFLINE": "1", "PYTHONUTF8": "1",
             "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0"}


def nearest_rank(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[max(math.ceil(q * len(ordered)) - 1, 0)]


def describe(values: list[Any]) -> dict[str, Any] | None:
    """Median and 95th percentile (nearest rank) of the values, None when none was kept."""
    if not values or any(v is None for v in values):
        return None
    floats = [float(v) for v in values]
    return {"median": round(statistics.median(floats), 10), "p95": round(nearest_rank(floats, 0.95), 10),
            "mean": round(statistics.fmean(floats), 10)}


def recounted(table: dict[str, Any], run: costlines.Run, ratios: dict[str, float]) -> Decimal | None:
    """The run's cost with each priced line's tokens recounted the way Nova Lite counts them (tokens.py)."""
    total = Decimal(0)
    for line in run.lines:
        if line.input_tokens is None or line.output_tokens is None:
            return None
        d = price.deployment(table, price.serving_alias(table, line))
        total += (Decimal(str(line.input_tokens * ratios["input"])) * price.per_token(d["input_per_million"])
                  + Decimal(str(line.output_tokens * ratios["output"])) * price.per_token(d["output_per_million"]))
    return total


def per_workflow_model(runs: list[costlines.Run], table: dict[str, Any],
                       recount: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
    rows = []
    for workflow in costlines.ORDER:
        budget = registry.manifest(workflow)["budget"]["per_run_usd"]
        models = sorted({r.model for r in runs if r.workflow == workflow})
        for model in models:
            mine = [r for r in runs if r.workflow == workflow and r.model == model]
            # Tokens and cost over the runs that kept tokens: all of them, but for W3 and W4 only step 3b's runs.
            priced = [r for r in mine if r.tokens_kept]
            costs = [price.run_cost(table, r) for r in priced]
            guard = [price.run_guardrail(table, r) for r in priced]
            share = [None if c is None else c / Decimal(str(budget)) * 100 for c in costs]
            ratio = None
            if priced and sum(costs) > 0:
                ratio = round(float(sum(guard) / sum(costs)), 2)
            again = [recounted(table, r, recount[model]) for r in priced] if model in recount else None
            rows.append({
                "workflow": workflow, "model": model, "kept_runs": len({r.kept_run for r in mine}), "runs": len(mine),
                "runs_with_tokens": len(priced),
                "model_calls": describe([r.model_calls for r in mine]),
                "tool_calls": describe([r.tool_calls for r in mine]), "tool_calls_kept_as": costlines.TOOL_CALLS[workflow],
                "input_tokens": describe([r.tokens()[0] for r in priced]),
                "output_tokens": describe([r.tokens()[1] for r in priced]),
                "cost_usd": describe(costs), "per_run_usd": budget, "cost_pct_of_run_budget": describe(share),
                "recounted_as_nova_lite_usd": describe(again) if again else None,
                "guardrail_usd": describe(guard), "guardrail_over_tokens": ratio,
                "restricted_calls": sum(1 for r in mine for line in r.lines if line.alias == costlines.RESTRICTED_ALIAS),
            })
    return rows


def lines_summary(runs: list[costlines.Run]) -> list[dict[str, Any]]:
    rows = []
    for workflow in costlines.ORDER:
        mine = [r for r in runs if r.workflow == workflow]
        lines = costlines.lines(mine)
        rows.append({
            "workflow": workflow, "kept_runs": len({(r.model, r.kept_run) for r in mine}),
            "traced_runs": len({(r.model, r.kept_run) for r in mine if costlines.is_traced(r)}), "runs": len(mine),
            "lines": len(lines), "with_tokens": sum(1 for line in lines if line.input_tokens is not None),
            "with_duration": sum(1 for line in lines if line.duration_ms is not None),
            "runs_with_trace_id": sum(1 for r in mine if r.trace_id), "fallbacks": sum(line.fallback for line in lines),
            "aliases": dict(sorted(Counter(f"{line.alias}/{line.data_class}" for line in lines).items())),
            "tool_calls_kept_as": costlines.TOOL_CALLS[workflow],
        })
    return rows


def w2_against_chapter_3(runs: list[costlines.Run]) -> dict[str, Any]:
    """ch03:58: "the operations assistant's median at Larkspur is two model calls and one tool call".

    All of W2's kept runs, and the answers alone: the cases chapter 15's converted set doesn't mark as a
    refusal (labs/ch15/cases/w2.jsonl, negative.refusal)."""
    cases = {c["id"]: c for c in registry.read_jsonl(registry.CASES / "w2.jsonl")}
    w2 = [r for r in runs if r.workflow == "w2"]
    answers = [r for r in w2 if not cases[r.case]["negative"]["refusal"]]

    def medians(group: list[costlines.Run]) -> dict[str, Any]:
        return {"runs": len(group), "model_calls": statistics.median(r.model_calls for r in group),
                "tool_calls": statistics.median(r.tool_calls for r in group),
                "model_calls_counts": dict(sorted(Counter(r.model_calls for r in group).items())),
                "tool_calls_counts": dict(sorted(Counter(r.tool_calls for r in group).items()))}

    by_kept: dict[str, list[costlines.Run]] = {}
    for r in w2:
        by_kept.setdefault(r.kept_run, []).append(r)
    first_two = {}
    for model in sorted({r.model for r in answers}):
        mine = [r for r in answers if r.model == model and r.model_calls >= 2]
        first_two[model] = [statistics.median(r.lines[i].input_tokens for r in mine) for i in (0, 1)]
    skeleton = [r for r in runs if r.workflow == "skeleton"]
    return {"claim": "ch03:58", "golden_cases": len(cases),
            "golden_refusal_cases": sum(1 for c in cases.values() if c["negative"]["refusal"]),
            "all": medians(w2), "answers": medians(answers),
            "by_kept_run": {k: medians(v) for k, v in by_kept.items()}, "skeleton": medians(skeleton),
            "ch11_361_first_two_prompts": {"words": "about 850 prompt tokens for the first and 1,000 for the second; "
                                                    "Gemma 4 12B's run to about 1,000 and 1,200",
                                           "measured_medians": first_two}}


def tenants(runs: list[costlines.Run]) -> dict[str, Any]:
    """Who uses larkspur-chat-restricted, by each source the plan's consistency note names."""
    listing = [w for w in months.WORKFLOWS if costlines.RESTRICTED_ALIAS in registry.manifest(w)["models"]]
    sent = {}
    for w in costlines.ORDER:
        calls = sum(1 for r in runs if r.workflow == w for line in r.lines if line.alias == costlines.RESTRICTED_ALIAS)
        if calls:
            sent[w] = calls
    return {"manifests": listing, "kept_runs": sent,
            "chapter 9": {"workflows": ["w3", "w2"], "lines": ["ch09:18", "ch09:200"],
                          "words": "On this path Larkspur runs all of them, for two workflows."},
            "chapter 10": {"workflows": ["w1"], "lines": ["ch10:72", "ch10:78"],
                           "words": "Restricted calls go to the self-hosted model on EKS from month six"}}


def child(script: str, *args: str) -> Any:
    """Run one of the ledger's scripts in a fresh, offline process and read its JSON."""
    env = {**os.environ, **CHILD_ENV}
    done = subprocess.run([sys.executable, str(HERE / script), *args, "--json"], env=env, cwd=str(LAB),
                          capture_output=True, text=True, encoding="utf-8", check=False)
    if done.returncode:
        raise RuntimeError(f"{script} failed:\n{done.stderr[-2000:]}")
    return json.loads(done.stdout)


def rate_limits() -> dict[str, Any]:
    """Each manifest that lists the restricted alias, with its request rate: the alias's only stop at the gateway."""
    out = {}
    for w in costlines.ORDER:
        m = registry.manifest(w)
        if costlines.RESTRICTED_ALIAS in m["models"]:
            out[m["workflow"]] = m["budget"].get("requests_per_minute")
    return out


def measured_against_proxies(before: dict[str, Any], after: dict[str, Any], alloc_before: dict[str, Any],
                             alloc_after: dict[str, Any]) -> dict[str, Any]:
    """Step 3b's measured tokens against step 2's proxies. Per call, for each workflow whose basis changed (W3 and
    W4); and for every workflow, the month and its shares of what isn't a call, as step 2 had them (chapter 15's
    kept runs alone, the proxies for W3 and W4) and as they are with step 3b's runs."""
    tokens_rows = []
    for w in months.WORKFLOWS:
        pb, pa = before["profiles"][w], after["profiles"][w]
        if pb["basis"] == pa["basis"]:
            continue
        tokens_rows.append({
            "workflow": w, "basis": [pb["basis"], pa["basis"]], "runs": [pb["runs"], pa["runs"]],
            "calls_per_run": [pb["calls"], pa["calls"]],
            "restricted_calls_per_run": [pb["restricted_calls"], pa["restricted_calls"]],
            "input_per_call": [pb["input"] / pb["calls"], pa["input"] / pa["calls"]],
            "output_per_call": [pb["output"] / pb["calls"], pa["output"] / pa["calls"]],
            "input_per_run": [pb["input"], pa["input"]], "output_per_run": [pb["output"], pa["output"]],
            "cost_per_run_usd": [pb["cost"], pa["cost"]]})
    b_rows, a_rows = {r["workflow"]: r for r in before["rows"]}, {r["workflow"]: r for r in after["rows"]}
    fb, fa = alloc_before["fixed"]["splits"], alloc_after["fixed"]["splits"]
    reading = "manifests and chapter 10"
    gb, ga = alloc_before["gpu"]["readings"][reading]["split"], alloc_after["gpu"]["readings"][reading]["split"]
    month_rows = []
    for w in months.WORKFLOWS:
        b, a = b_rows[w], a_rows[w]
        month_rows.append({
            "workflow": w, "runs_per_month": [b["runs_per_month"], a["runs_per_month"]],
            "calls_per_month": [b["calls_per_month"], a["calls_per_month"]],
            "tokens_per_month": [b["tokens_per_month"], a["tokens_per_month"]],
            "direct_usd": [b["direct_usd"], a["direct_usd"]], "direct_pct_of_month": [b["direct_pct_of_month"], a["direct_pct_of_month"]],
            "guardrail_pct_of_month": [b["guardrail_pct_of_month"], a["guardrail_pct_of_month"]],
            "calls_share": [fb["gateway calls"][w]["share"], fa["gateway calls"][w]["share"]],
            "tokens_share": [fb["tokens"][w]["share"], fa["tokens"][w]["share"]],
            "fixed_by_calls_usd": [fb["gateway calls"][w]["usd"], fa["gateway calls"][w]["usd"]],
            "fixed_by_tokens_usd": [fb["tokens"][w]["usd"], fa["tokens"][w]["usd"]],
            "gpu_usd": [gb[w]["usd"] if w in gb else None, ga[w]["usd"] if w in ga else None],
            "gpu_token_share": [gb[w]["token_share"] if w in gb else None, ga[w]["token_share"] if w in ga else None]})
    return {"tokens": tokens_rows, "month": month_rows,
            "fixed_priced_usd": alloc_after["fixed"]["priced_usd"], "gpu_reading": reading}


def build(runs: list[costlines.Run] | None = None) -> dict[str, Any]:
    runs = runs if runs is not None else costlines.collect()
    table, volumes = price.load(), months.load_volumes()
    across = tokens.compare(runs)
    recount = {model: {"input": across["ratios"][f"nova-lite/{model}"]["input"]["of_totals"],
                       "output": across["ratios"][f"nova-lite/{model}"]["output"]["of_totals"]}
               for model in ("gpt-oss-20b", "gemma4-12b")}
    month = months.month(runs, table, volumes, recount[volumes["reference_model"]])
    allocation = months.allocation(month, table, volumes)
    # Step 2's month, from chapter 15's kept runs alone: W3 and W4 at their proxies.
    before = months.month([r for r in runs if not costlines.is_traced(r)], table, volumes, recount[volumes["reference_model"]])
    per_month = {r["workflow"]: r["runs_per_month"] for r in month["rows"]}
    return {
        "date_of_the_kept_runs": "2026-10-29 to 2026-11-03",
        "table": {"file": "ledger/prices.yaml", "entries": len(price.entries(table))},
        "lines": lines_summary(runs),
        "recount_ratios": recount,
        "per_run": per_workflow_model(runs, table, recount),
        "w2_against_chapter_3": w2_against_chapter_3(runs),
        "tokens_across_models": across,
        "litellm_custom_prices": child("price.py", "--check-litellm"),
        "litellm_map": child("litellm_map.py"),
        "restricted_alias_rates": rate_limits(),
        "month": {**month, "recount_ratios": recount[volumes["reference_model"]]},
        "tenants": tenants(runs),
        "allocation": allocation,
        "sampling": sampling.experiment(runs, table, per_month),
        "measured": measured_against_proxies(before, month, months.allocation(before, table, volumes), allocation),
        "judge": judge_lines.section(runs, table),
    }


def write(out: Path, runs: list[costlines.Run] | None = None) -> dict[str, Any]:
    runs = runs if runs is not None else costlines.collect()
    data = build(runs)
    out.mkdir(parents=True, exist_ok=True)
    costlines.write_jsonl(runs + judge_lines.collect(), out / "costlines.jsonl")  # the judge's lines after the workflows'
    (out / "ledger.json").write_text(json.dumps(data, indent=1, default=str) + "\n", encoding="utf-8", newline="\n")
    table = price.load()
    (out / "ledger-summary.md").write_text(render.summary(data, table), encoding="utf-8", newline="\n")
    return data


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=LAB / "results" / "2026-11-03")
    args = parser.parse_args(argv)
    offline.block_network()
    write(args.out)
    print(f"wrote {args.out / 'ledger-summary.md'}, ledger.json and costlines.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
