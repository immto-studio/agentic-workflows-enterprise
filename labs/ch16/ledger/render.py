"""The ledger's summary as Markdown, from the data report.build computes. Formatting only: every number
comes from the data, and none is written here."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import judge_lines as jl

NAMES = {"skeleton": "skeleton", "w1": "W1", "w2": "W2", "w3": "W3", "w4": "W4", "w5": "W5"}


# --- numbers --------------------------------------------------------------------------------------------

def sig(value: Any, digits: int = 3) -> str:
    """The value to `digits` significant digits, never in exponent form."""
    if value is None:
        return "not kept"
    d = Decimal(str(value))
    if d == 0:
        return "0"
    rounded = d.quantize(Decimal(1).scaleb(d.adjusted() - digits + 1))
    text = format(rounded, "f")
    if "." in text:
        whole, frac = text.split(".")
        return f"{int(whole):,}.{frac}" if abs(rounded) >= 1000 else text
    return f"{int(text):,}"


def money(value: Any) -> str:
    if value is None:
        return "not kept"
    return f"{value:,.2f}" if abs(value) >= 1 else sig(value, 3)


def pct(value: Any, digits: int = 2) -> str:
    """A percentage to `digits` significant digits; a share just under 100 keeps three decimals, so 99.997
    doesn't round to 100."""
    if value is None:
        return "not kept"
    if 99.9 <= value < 100:
        return f"{value:.3f}%"
    return f"{sig(value, max(digits, 3) if value >= 100 else digits)}%"


def rate(value: float) -> str:
    return f"{value * 100:g}%"


def num(value: Any) -> str:
    """A price as written, never in exponent form."""
    return format(Decimal(str(value)), "f")


def count(value: Any) -> str:
    if value is None:
        return "not kept"
    if float(value).is_integer():
        return f"{int(value):,}"
    return sig(value, 3)


def ratio(value: Any) -> str:
    return "none" if value is None else f"{value:.2f}"


WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")


def words(n: Any) -> str:
    """A count in prose: a word up to ten, digits above."""
    n = int(n)
    return WORDS[n] if 0 <= n <= 10 else f"{n:,}"


def half(value: Any) -> str:
    """A median of whole numbers: whole, or a half."""
    return count(value) if float(value).is_integer() else f"{value:,.1f}"


def pair(stats: dict[str, Any] | None, fmt: Any = count) -> str:
    return "not kept" if stats is None else f"{fmt(stats['median'])} / {fmt(stats['p95'])}"


def table(headers: list[str], rows: list[list[Any]]) -> str:
    out = ["|" + " |".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["|" + " |".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(out)


# --- sections -------------------------------------------------------------------------------------------

def _price_text(e: dict[str, Any]) -> str:
    if "input_per_million" in e:
        if e["input_per_million"] is None:
            return "none"
        return f"{num(e['input_per_million'])} in, {num(e['output_per_million'])} out, per million tokens"
    if "per_1000_text_units" in e:
        return (", ".join(f"{k.replace('_', ' ')} {num(v)}" for k, v in e["per_1000_text_units"].items())
                + ", per 1,000 text units")
    units = [("per_hour", "an hour"), ("per_month", "a month"), ("per_gb_month", "a GB-month"), ("per_gb", "a GB"),
             ("per_gb_hour", "a GB-hour"), ("per_span", "a span"), ("per_request", "a request"),
             ("per_million_ecpus", "a million ECPUs"), ("input_per_1k_tpm_hour", "per 1K TPM-hour in")]
    parts = []
    for key, word in units:
        if key in e:
            v = e[key]
            if isinstance(v, dict):
                parts.append("; ".join(f"{term.replace('_', ' ')}: {num(p['global'])} global, "
                                       f"{num(p['non_global'])} non-global" for term, p in v.items()) + ", an hour per GSU")
            elif v is None:
                parts.append("none")
            elif key == "input_per_1k_tpm_hour":
                parts.append(f"{num(v)} in, {num(e['output_per_1k_tpm_hour'])} out, per 1K tokens a minute an hour")
            else:
                parts.append(f"{num(v)} {word}")
    if "per_month_reserved" in e:
        parts.append(f"{num(e['per_month_reserved'])} a month or {num(e['per_year_reserved'])} a year reserved, "
                     f"at least {e['minimum_ptus']} PTUs")
    return "; ".join(parts)


def prices(table_data: dict[str, Any]) -> str:
    sections = [("Deployments: what serves an alias where", table_data["deployments"]),
                ("The guardrail on the managed aliases", [table_data["guardrail"]]),
                ("GPU hours", table_data["gpu"]), ("The platform's fixed costs", table_data["platform"]),
                ("Traces and the reconciliation", table_data["observability"]),
                ("Committed capacity, for step 5", table_data["committed"])]
    out = ["## 1. The price table", "",
           "`ledger/prices.yaml`, in US dollars. Chapter 6's design names the deployment for each alias: "
           + ", ".join(f"`{a}` is `{d}`" for a, d in table_data["design"].items())
           + f", and a fallback from `larkspur-chat` is priced at `{table_data['design']['larkspur-chat-fallback']}`, "
           "in its own Region. Every entry carries its source, the date that source records, and the page it cites; "
           "the entries copied from a cost sheet name the place in the sheet, and the rest quote section 8.8 of "
           "the fact sheet.", ""]
    for title, entries in sections:
        out += [f"### {title}", ""]
        rows = []
        for e in entries:
            what = e.get("model") or e.get("what") or ""
            rows.append([f"`{e['id']}`", what, _price_text(e), e["source"], str(e["date"])])
        out += [table(["Entry", "What", "Price (USD)", "Source", "Date"], rows), ""]
    nulls = [e for section in ("deployments", "gpu", "platform") for e in table_data[section]
             if (e.get("input_per_million", 0) is None) or (e.get("per_hour", 0) is None) or (e.get("per_month", 0) is None)]
    out.append("A price no vendor publishes, or no source has, is null and stays a parameter: "
               + "; ".join(f"`{e['id']}` ({e.get('vendor_words') or e.get('reason')})" for e in nulls) + ".")
    return "\n".join(out)


def lines(data: dict[str, Any]) -> str:
    rows = [[NAMES[r["workflow"]], r["kept_runs"], r["traced_runs"], r["runs"], r["lines"], r["with_tokens"],
             r["with_duration"], r["runs_with_trace_id"], r["fallbacks"], r["tool_calls_kept_as"]] for r in data["lines"]]
    total = [sum(r[k] for r in data["lines"]) for k in ("kept_runs", "traced_runs", "runs", "lines", "with_tokens",
                                                      "with_duration", "runs_with_trace_id", "fallbacks")]
    rows.append(["all", *total, ""])
    by = {r["workflow"]: r for r in data["lines"]}
    w3, w4 = by["w3"], by["w4"]
    return "\n".join([
        "## 2. The cost lines", "",
        "`ledger/costlines.py` reads every kept run through chapter 15's registry, and the runs step 3b made through "
        "the Collector from each workflow's `eval/traced/`, which chapter 15's registry doesn't hold, and writes each "
        "model call as one line of one shape (`costlines.jsonl` here): run id, trace id, workflow and the workflow "
        "tag the gateway saw, the kept run and the case, the call's place in the run, the model as recorded, the "
        "alias asked for and the one that served, the data class, input and output tokens, the call's time, and "
        "whether a fallback served it. A run's id is its trace id where it kept one, and otherwise "
        "`<workflow>:<model>:<kept run>:<case>`.", "",
        table(["Workflow", "Kept runs", "Of them, step 3b's", "Runs", "Model calls", "With tokens", "With time",
               "Runs with a trace id", "Fallbacks", "Tool calls, as kept"], rows), "",
        "Chapter 15's kept runs of W3 and W4 hold no tokens: their gateways wrote the lines to the labs' scratch "
        "folders (`eval/_lab/`, which `.gitignore` leaves out), and only W5 committed its gateway's lines beside its "
        "results. Step 3b ran W3's incidents and W4's changes again through the Collector, with W2's golden set for "
        "fig-16-01, and committed the gateway's lines beside each run in the workflow's `eval/traced/2026-11-03/`, as "
        "W5 does. Those lines are the gateway's own, one per call, joined to each case by its trace id, so "
        f"{count(w3['with_tokens'])} of W3's {count(w3['lines'])} lines and {count(w4['with_tokens'])} of W4's "
        f"{count(w4['lines'])} carry tokens and a time: step 3b's, and none of the earlier runs'. O-D5's rule that the "
        "cost lines are never sampled assumes they are kept, and from step 3b on W3's and W4's are. Every step 3b run "
        f"kept a trace id, as W4's and W5's earlier runs did, and {'no kept call was' if not total[-1] else f'{total[-1]} kept calls were'} "
        "served by a fallback; `tests/test_price.py` prices one on a line made for it.",
    ])


def per_run(data: dict[str, Any]) -> str:
    rows = []
    for r in data["per_run"]:
        recount = r.get("recounted_as_nova_lite_usd")
        rows.append([NAMES[r["workflow"]], r["model"], r["runs"], r["runs_with_tokens"], pair(r["model_calls"]),
                     pair(r["tool_calls"]), pair(r["input_tokens"]), pair(r["output_tokens"]), pair(r["cost_usd"], money),
                     pair(r["cost_pct_of_run_budget"], lambda v: pct(v, 2)),
                     "same" if r["model"] == "nova-lite" else pair(recount, money),
                     pair(r["guardrail_usd"], money)])
    over = max((r["cost_pct_of_run_budget"]["p95"] for r in data["per_run"] if r["cost_pct_of_run_budget"]), default=0)
    worst = next(r for r in data["per_run"] if r["cost_pct_of_run_budget"] and r["cost_pct_of_run_budget"]["p95"] == over)
    ordinary = max((r["cost_pct_of_run_budget"]["median"] for r in data["per_run"] if r["cost_pct_of_run_budget"]),
                   default=0)
    w1_restricted = sorted({r["restricted_calls"] for r in data["per_run"] if r["workflow"] == "w1"})
    return "\n".join([
        "## 3. Cost per run, by workflow and model", "",
        "Every kept run of each model, the early ones included. Each cell is the median and the 95th percentile "
        "(nearest rank, a value some run had). Calls count every run, and tokens and cost every run that kept them: "
        "for W3 and W4 those are step 3b's runs alone. Cost is in US dollars at chapter 6's design; the share is of "
        "the manifest's `per_run_usd` (the skeleton's is chapter 5's W2 manifest). The recounted column prices each "
        "call's tokens multiplied by section 5's ratios for its model, the way Nova Lite would have counted them. "
        "The guardrail column is section 8's estimate, which the cost lines don't carry.", "",
        table(["Workflow", "Model", "Runs", "With tokens", "Model calls", "Tool calls", "Input tokens", "Output tokens",
               "Cost per run", "Share of per_run_usd", "Recounted as Nova Lite", "Guardrail estimate"], rows), "",
        "The skeleton's calls cost nothing per token: chapter 9's runner sent them to `larkspur-chat-restricted`, "
        f"whose price is zero. W1's Restricted calls, {' or '.join(map(words, w1_restricted))} in each kept run, are "
        "priced at zero for the same reason. "
        f"No median run costs more than {pct(ordinary, 2)} of its per-run budget. The highest 95th percentile, "
        f"{pct(over, 2)}, is {NAMES[worst['workflow']]}'s on {worst['model']}, whose kept runs include one where the "
        "model looped in its reasoning: the per-run budgets sit far above an ordinary run and bind on a loop.",
    ])


def w2(data: dict[str, Any]) -> str:
    c = data["w2_against_chapter_3"]
    a, ans, sk = c["all"], c["answers"], c["skeleton"]
    per = c["by_kept_run"]
    medians = sorted({(v["model_calls"], v["tool_calls"]) for v in per.values()})
    two = a["model_calls_counts"].get("2", a["model_calls_counts"].get(2, 0))
    one = a["tool_calls_counts"].get("1", a["tool_calls_counts"].get(1, 0))
    p95 = next(r for r in data["per_run"] if r["workflow"] == "w2" and r["model"] == "gpt-oss-20b")
    top_calls, top_reads = p95["model_calls"]["p95"], p95["tool_calls"]["p95"]

    def at_top(counts: dict) -> int:
        return counts.get(int(top_calls), counts.get(str(int(top_calls)), 0))

    top_kept = max((k for k in per if k.startswith("gpt-oss-20b")), key=lambda k: at_top(per[k]["model_calls_counts"]))
    top_n = at_top(per[top_kept]["model_calls_counts"])
    m = c["ch11_361_first_two_prompts"]["measured_medians"]
    held = (a["model_calls"], a["tool_calls"]) == (2, 1) and (ans["model_calls"], ans["tool_calls"]) == (2, 1)
    verdict = "so the claim holds" if held else "so the claim does not hold"
    return "\n".join([
        "## 4. W2 against chapter 3", "",
        "Chapter 3 says \"the operations assistant's median at Larkspur is two model calls and one tool call\" "
        f"(ch03:58). Over W2's {a['runs']} kept runs the median is {count(a['model_calls'])} model calls and "
        f"{count(a['tool_calls'])} read; over the {ans['runs']} answers alone (the cases chapter 15's set doesn't "
        f"mark as a refusal) it is {count(ans['model_calls'])} and {count(ans['tool_calls'])}, and each of the "
        f"{words(len(per))} kept runs has the medians "
        f"{', '.join(f'{count(x)} and {count(y)}' for x, y in medians)}, {verdict}. "
        f"Of the {a['runs']} runs, {two} made two model calls and {one} made one read. The 95th "
        f"percentile on gpt-oss-20b is {count(top_calls)} calls and {count(top_reads)} reads: in its kept run "
        f"`{top_kept}`, {words(top_n)} of {per[top_kept]['runs']} runs made {words(top_calls)} calls. Chapter 5's "
        f"skeleton, W2's first form, has the same medians over its {sk['runs']} runs.", "",
        "Chapter 11's prompt sizes hold as well (ch11:361: \"about 850 prompt tokens for the first and 1,000 for "
        "the second; Gemma 4 12B's run to about 1,000 and 1,200\"). Over the answers with at least two calls, the "
        f"medians of the first two prompts are {half(m['gpt-oss-20b'][0])} and {half(m['gpt-oss-20b'][1])} "
        f"tokens on gpt-oss-20b, and {half(m['gemma4-12b'][0])} and {half(m['gemma4-12b'][1])} on Gemma 4 12B.",
    ])


def across(data: dict[str, Any]) -> str:
    t = data["tokens_across_models"]
    rows = []
    for name, r in t["ratios"].items():
        left, right = name.split("/")
        rows.append([f"{left} over {right}", f"{r['input']['of_totals']:.2f} ({r['input']['median']:.2f})",
                     f"{r['output']['of_totals']:.2f} ({r['output']['median']:.2f})",
                     f"{r['first_input']['of_totals']:.2f}"])
    totals = [[m, count(v["calls"]), count(v["input"]), count(v["output"])] for m, v in t["totals"].items()]
    gpt = t["ratios"]["nova-lite/gpt-oss-20b"]
    gem = t["ratios"]["nova-lite/gemma4-12b"]
    unanswered = sum(len(v) for v in t["left_out_unanswered"].values())
    return "\n".join([
        "## 5. Token counts across models", "",
        f"W1's golden set ran on gpt-oss-20b, Gemma 4 12B and Nova Lite (book D-033, companion #55 and #100). "
        f"Of its {t['cases']} cases, {t['compared']} are compared: {len(t['left_out_restricted'])} are left out "
        "because a call went to `larkspur-chat-restricted`, which served gpt-oss-20b even in the Nova Lite run, "
        f"and {unanswered} because gpt-oss-20b's run of them ended at the step budget with the harness's refusal. "
        f"All {t['same_number_of_calls']} compared cases took the same number of calls on every model.", "",
        table(["Model", "Calls", "Input tokens", "Output tokens"], totals), "",
        table(["Ratio", "Input, totals (median per case)", "Output, totals (median per case)",
               "First call's input"], rows), "",
        f"The first call's prompt is the same text on every model, so its ratio, {gpt['first_input']['of_totals']:.2f} "
        f"for Nova Lite over gpt-oss-20b, is the tokenizer and the chat template alone; over whole cases, with the "
        f"pages each model's searches returned, it is {gpt['input']['of_totals']:.2f}. Output goes the other way, "
        f"{gpt['output']['of_totals']:.2f}: gpt-oss-20b's completion tokens include its reasoning, and Nova Lite "
        "writes shorter answers. The ratios the priced estimates carry: a cost priced from gpt-oss-20b's counts "
        f"multiplies input by {gpt['input']['of_totals']:.2f} and output by {gpt['output']['of_totals']:.2f} to "
        f"approach Nova Lite's count, and one from Gemma 4 12B's by {gem['input']['of_totals']:.2f} and "
        f"{gem['output']['of_totals']:.2f}. They come from one workflow's {t['compared']} cases; W2's and W5's prompts are "
        "shaped differently, so elsewhere they are an estimate.",
    ])


def custom(data: dict[str, Any]) -> str:
    rows = []
    name_only = None
    for r in data["litellm_custom_prices"]:
        if r["deployment"] == "(by name only)":
            name_only = r
            continue
        rows.append([r["gateway"], f"`{r['alias']}`", f"`{r['deployment']}`",
                     f"{count(r['input_tokens'])} / {count(r['output_tokens'])}",
                     sig(r["expected_usd"], 4), sig(r["response_cost_usd"], 4),
                     "embedding" if r["completion_cost_usd"] is None else sig(r["completion_cost_usd"], 4),
                     "yes" if r["budget_checks_skipped"] else "no"])
    rates = data["restricted_alias_rates"]
    return "\n".join([
        "## 6. The table as LiteLLM's custom prices", "",
        "`ledger/litellm.prices.yaml` is generated from the table: every priced deployment with "
        "`input_cost_per_token` and `output_cost_per_token` in `litellm_params`, one `model_list` per gateway "
        "pair. Each list was loaded into LiteLLM 1.106.6's Router in a fresh process with "
        "`LITELLM_LOCAL_MODEL_COST_MAP=True` and the network blocked, and each alias answered one mocked call of "
        "known usage. The cost was read as the gateway's callback receives it (`response_cost`) and from "
        "`completion_cost` with the deployment's id, as the proxy calls it.", "",
        table(["Gateway", "Alias", "Deployment", "Tokens in / out", "Expected", "response_cost",
               "completion_cost by id", "Budget checks skipped"], rows), "",
        "The custom price takes effect on every deployment, the Canadian profile included, which the built-in "
        "map doesn't know (section 7). Priced by its model name alone in the same process, the Canadian "
        f"deployment comes to {'zero' if name_only['completion_cost_usd'] == 0 else sig(name_only['completion_cost_usd'])}: "
        "registering the deployment leaves an empty entry under its model name, so a cost computed from the name "
        "anywhere in the gateway's process is zero, with no error. The ledger prices by deployment, as the "
        "gateway's cost line does.", "",
        "The self-hosted alias is priced at exactly zero, and LiteLLM's own predicate (`is_model_cost_zero`) "
        "says its requests skip every budget check (fact sheet 8.1). Chapter 5's callback sums the same zero "
        "into its per-run budget, so that budget never stops a run on the alias either. What stops a loop there "
        "is the request rate of each manifest that lists the alias ("
        + ", ".join(f"`{w}` {n} a minute" for w, n in rates.items())
        + ") and each harness's step budget (ch09:198).",
    ])


def built_in(data: dict[str, Any]) -> str:
    mp = data["litellm_map"]

    def price_of(p: dict[str, Any] | None) -> str:
        if p is None:
            return "none"
        if "error" in p:
            return p["error"]
        return f"{p['input_per_million']} / {p['output_per_million']}"

    rows = []
    for r in mp["rows"]:
        table_price = "none" if r["table"] is None else f"{r['table']['input']} / {r['table']['output']}"
        rows.append([f"`{r['deployment']}`", f"`{r['name']}`", r["what"], price_of(r["map_entry"]),
                     price_of(r["litellm"]), table_price, r["kind"],
                     "" if r["table_over_litellm"] is None else f"{r['table_over_litellm']:.4f}"])
    by = {(r["deployment"], r["name"]): r for r in mp["rows"]}
    ca = by[("nova-lite-ca", "bedrock/us.amazon.nova-lite-v1:0")]["table_over_litellm"]
    titan = by[("titan-embed-v2-ca", "bedrock/amazon.titan-embed-text-v2:0")]["table_over_litellm"]
    azure = by[("gpt-4o-canada-east", "azure/gpt-4o-2024-11-20")]["table_over_litellm"]
    return "\n".join([
        "## 7. LiteLLM's built-in map against the table", "",
        f"`ledger/litellm_map.py`, LiteLLM {mp['litellm']} with `LITELLM_LOCAL_MODEL_COST_MAP={mp['local_map']}`; "
        f"the map in use is the wheel's own file (`{mp['map']}`): {'yes' if mp['map_in_use_is_the_wheels'] else 'no'}. "
        "Prices per million tokens, input / output; the last column is the table's price over LiteLLM's.", "",
        table(["Deployment", "Name", "What", "Map entry", "LiteLLM prices it at", "Table", "Difference",
               "Table / LiteLLM"], rows), "",
        "It reproduces section 8.1's probe: the map has no entry for the Canadian profile, which LiteLLM can't "
        "price (`ModelNotMappedError`), and a name with a Region prefix prices at the base model's entry. The "
        "differences, one by one:", "",
        "- Missing: the Canadian profile, `ca.amazon.nova-lite-v1:0`. Without the custom price a call to "
        "`larkspur-chat` has no cost at all. The self-hosted model has no entry either and needs its explicit zero.",
        f"- A price the map can't hold: Bedrock bills a profile at the price of the Region it is called in "
        f"(ch06:162), and the map keys one price to a name. Every Nova Lite name LiteLLM can price comes to "
        f"us-east-2's rate, so the Canadian price, {(ca - 1) * 100:.1f} percent higher, is out of its reach, "
        "whether the name is the US profile called in ca-central-1 or the bare model with LiteLLM's ca-central-1 "
        "prefix.",
        f"- Different prices: Titan Text Embeddings V2 costs {titan:g} times the map's price in ca-central-1, "
        f"and the regional gpt-4o deployment in Canada East {azure:g} times the map's Azure entry, which is the "
        "Global price. The map keys neither to a Region.",
        "- Equal: the bare Nova Lite model and the US profile in us-east-2, and gpt-oss-120b on Bedrock in "
        "us-east-1. Gemini 3.5 Flash has a map price and no table price, since no source the table may use "
        "prices it.",
    ])


def guardrail(data: dict[str, Any], table_data: dict[str, Any]) -> str:
    g = table_data["guardrail"]
    rows = []
    for r in data["per_run"]:
        if r["guardrail_over_tokens"] is None:
            continue
        rows.append([NAMES[r["workflow"]], r["model"], pair(r["cost_usd"], money), pair(r["guardrail_usd"], money),
                     ratio(r["guardrail_over_tokens"])])
    month = {r["workflow"]: r for r in data["month"]["rows"]}
    w2m = month["w2"]
    per_unit = sum(g["per_1000_text_units"][p] for p in g["policies"])
    ratios = [r["guardrail_over_tokens"] for r in data["per_run"] if r["guardrail_over_tokens"] is not None]
    return "\n".join([
        "## 8. What the cost lines leave out: the guardrail", "",
        "Chapter 6's gateway runs a Bedrock guardrail before and after every call on the managed aliases "
        "(`labs/ch06/gateway/litellm.aws.yaml`), with a content policy and a sensitive-information policy "
        f"(`labs/ch06/terraform/guardrail.tf`), at {per_unit:.2f} US dollars per 1,000 text units together in "
        "ca-central-1. A text unit is up to 1,000 characters, per policy, and LiteLLM sends the guardrail the "
        "text of every message, tool results included. The gateway's cost line records the model's tokens and "
        "not the guardrail, so `price.guardrail_estimate` prices it from each call's tokens at LiteLLM's "
        f"{g['characters_per_token']} characters a token. It is an estimate: prompt tokens also count the tool "
        "definitions and the chat template, which the guardrail doesn't read, and four characters a token is "
        "LiteLLM's rule of thumb, not a measurement of these prompts.", "",
        table(["Workflow", "Model", "Tokens' cost per run", "Guardrail estimate per run", "Guardrail over tokens"], rows), "",
        f"At Nova Lite's price the guardrail costs {min(ratios):.0f} to {max(ratios):.0f} times the tokens it "
        "screens, less where the calls write more (W5's calls on gpt-oss-20b carry long reasoning, which the "
        f"tokens' cost counts at the output price). Over a month, W2's guardrail comes to "
        f"{pct(w2m['guardrail_pct_of_month'], 2)} of its `per_month_usd` at chapter 9's volume, against "
        f"{pct(w2m['direct_pct_of_month'], 2)} for its tokens (section 9). A ledger that sums the cost lines "
        "misses the larger part of chapter 6's per-call cost, so the guardrail needs a line of its own, from "
        "ApplyGuardrail's own usage or the bill's guardrail usage types.",
    ])


def month(data: dict[str, Any]) -> str:
    m = data["month"]
    vrows = []
    for r in m["rows"]:
        v = r["volume"]
        if "parts" in v:
            amount = " plus ".join(f"{p['runs']} {name}" for name, p in v["parts"].items())
        elif "tokens" in v:
            amount = f"{v['tokens']:,} tokens"
        else:
            amount = f"{v['runs']:,} {v['unit']}s"
        basis = v.get("words") or v.get("basis") or ""
        if "parts" in v:
            basis = "; ".join(f"{name}: {p.get('words') or p.get('basis')}" for name, p in v["parts"].items())
        vrows.append([NAMES[r["workflow"]], amount, "; ".join(r["sources"]), basis])
    rows = []
    for r in m["rows"]:
        lo, hi = r["direct_pct_range_over_kept_runs"]
        rng = pct(lo, 2) if lo == hi else f"{pct(lo, 2)} to {pct(hi, 2)}"
        rows.append([NAMES[r["workflow"]], count(round(r["runs_per_month"])), count(round(r["calls_per_month"])),
                     count(r["tokens_per_month"]), money(r["direct_usd"]), pct(r["direct_pct_of_month"], 2), rng,
                     pct(r["recounted_pct_of_month"], 2), pct(r["guardrail_pct_of_month"], 2), r["basis"]])
    w2r = next(r for r in m["rows"] if r["workflow"] == "w2")
    top = max(m["rows"], key=lambda r: r["direct_pct_of_month"])
    an_hour = 100 * m["month_hours"]
    prof = data["month"]["profiles"]
    return "\n".join([
        "## 9. A month", "",
        "`ledger/volumes.yaml` gives each workflow's month with a source for each number. Chapters 1 to 14 were "
        "searched for each workflow's volume first; where the book states one, the line is cited, and where it "
        "doesn't, the number is a lab assumption, not in the book. A month is 730 hours, as in the cost sheets.", "",
        table(["Workflow", "A month", "Source", "Basis"], vrows), "",
        f"The per-run figures are the reference model's, {m['reference_model']}, over every kept run on it that kept "
        f"tokens. W2's month is chapter 9's 100 million tokens, {count(round(w2r['runs_per_month']))} questions at "
        f"W2's measured tokens per run; chapter 12's \"hundred questions an hour\" (ch12:18) would be {an_hour:,} a "
        "month, the same order. W3's and W4's runs are priced at step 3b's measured tokens, the only runs of theirs "
        f"that kept any: W3 made {sig(prof['w3']['calls'], 3)} calls a run there, {sig(prof['w3']['restricted_calls'], 2)} "
        f"of them to the restricted alias, at {count(round(prof['w3']['input'] / prof['w3']['calls']))} input tokens a "
        f"call, and W4 one call of {count(round(prof['w4']['input']))}. Section 13 sets them against step 2's "
        "proxies.", "",
        table(["Workflow", "Runs a month", "Calls a month", "Tokens a month", "Direct cost (USD)",
               "Share of per_month_usd", "Range over kept runs", "Recounted as Nova Lite", "Guardrail estimate",
               "Basis"], rows), "",
        f"Direct costs, the cost lines summed, are a small share of every monthly budget: {NAMES[top['workflow']]}'s "
        f"is the largest, at {pct(top['direct_pct_of_month'], 2)}. The range is the month priced from each kept run "
        "on its own. The "
        "recounted column multiplies the managed calls' tokens by section 5's ratios. The guardrail's estimate "
        "is larger than the tokens for every workflow (section 8).",
    ])


def allocation(data: dict[str, Any]) -> str:
    a, ten = data["allocation"], data["tenants"]
    g = a["gpu"]
    sent = {w: n for w, n in ten["kept_runs"].items() if w != "skeleton"}
    w2_calls = next(r["lines"] for r in data["lines"] if r["workflow"] == "w2")
    out = ["## 10. Allocating what isn't a call", "", "### The restricted alias's tenants", "",
           "Which workflows use `larkspur-chat-restricted` is one of the plan's consistency notes. Each source says:", "",
           f"- The manifests: {', '.join(NAMES[w] for w in ten['manifests'])} list the alias.",
           "- The kept runs: " + " and ".join(f"{NAMES[w]} sent {n} calls" for w, n in sent.items())
           + f" to it, and the skeleton {ten['kept_runs'].get('skeleton', 0)}, chapter 9's own test of the path. W2 "
           f"sent none: its class is Internal at most, and all {w2_calls} of its calls went to `larkspur-chat`.",
           f"- Chapter 9 ({', '.join(ten['chapter 9']['lines'])}): two workflows, the incident workflow and the "
           "operations assistant, whose manifest lists the alias.",
           f"- Chapter 10 ({', '.join(ten['chapter 10']['lines'])}): W1's Restricted calls go to the self-hosted "
           "model from month six.", "",
           f"The GPUs cost {words(g['replicas'])} replicas at the smallest g6e size's price, the lower bound chapter 9 uses, every hour of "
           f"the month: {money(g['usd'])} US dollars. The tenants' busy time is the tokens each sent the alias at "
           f"chapter 9's measured throughput of gpt-oss-20b ({g['throughput']['prompt_tokens_per_second']:,} prompt "
           f"and {g['throughput']['output_tokens_per_second']:,} output tokens a second on the workstation's GPU, a "
           "stand-in for one L40S and an upper bound on the time, since vLLM batches). That share of the hours is "
           "split among the tenants by their share of the alias's tokens, and the rest is idle, the platform team's "
           "line (O-D6). Both readings:", ""]
    for name, r in g["readings"].items():
        rows = []
        for w, s in r["split"].items():
            rows.append([NAMES[w], count(s["tokens"]), pct(s["token_share"] * 100, 3), money(s["usd"]),
                         pct(s["pct_of_month"], 2), money(s["without_idle_line_usd"]),
                         pct(s["without_idle_line_pct_of_month"], 3)])
        rows.append(["idle, the platform team", "", "", money(r["idle_usd"]), "", "", ""])
        reading = "the manifests and chapter 10" if name == "manifests and chapter 10" else name
        out += [f"Read with {reading} ({', '.join(NAMES[w] for w in r['tenants'])} as the tenants), they used "
                f"{pct(r['used_share'] * 100, 2)} of the GPUs' hours, and {pct(r['idle_share'] * 100)} were idle.", "",
                table(["Tenant", "Tokens a month", "Token share", "GPU share (USD)", "Share of per_month_usd",
                       "Without an idle line (USD)", "Without an idle line, share"], rows), ""]
    b = g["readings"]["manifests and chapter 10"]["split"]
    out += [
        f"With an idle line, the tenants' share is cents and the platform team carries almost all of the GPUs. "
        f"Without one, the whole cost split by tokens would put {pct(b['w1']['without_idle_line_pct_of_month'], 3)} "
        f"of W1's monthly budget on W1, or, read as chapter 9 reads it, "
        f"{pct(g['readings']['chapter 9']['split']['w3']['without_idle_line_pct_of_month'], 3)} of W3's on W3, "
        "which is why O-D6 keeps the idle line apart. W1's share is large here because its golden set puts "
        f"{words(len(data['tokens_across_models']['left_out_restricted']))} of {data['tokens_across_models']['cases']} cases "
        "on Restricted pages; production's share isn't measured.", "",
        "Recommendation, for the chapter and not made in the book here: state three tenants, the workflows whose "
        "manifests list the alias (W1, W2, W3), and split the GPU hours by each month's measured tokens, so the "
        "list can't drift from the bill. W1 and W3 send Restricted prompts (chapters 10 and 12), and W2 sends "
        "nothing in its kept runs, so it pays nothing until it does. Chapter 9's \"two workflows\" (ch09:18, "
        "ch09:200) leaves out W1, which in this month sends most of the alias's tokens; correcting it is a note "
        "for book #23.", "",
        "### The platform's fixed costs", ""]
    f = a["fixed"]
    rows = []
    for line in f["lines"]:
        basis = "parameter" if line["parameter"] else ("stand-in" if line["stand_in"] else "priced")
        rows.append([line["item"], line["quantity"], line["per"].replace("gb_month", "GB-month"),
                     "none" if line["unit_usd"] is None else line["unit_usd"], money(line["usd"]) if line["usd"] is not None else "none",
                     basis, line["source"]])
    out += [table(["Item", "Quantity", "Per", "Unit price (USD)", "A month (USD)", "Basis", "Source"], rows), "",
            f"Priced lines come to {money(f['priced_usd'])} US dollars a month, {money(f['stand_in_usd'])} of them at "
            "us-east-2's EC2 prices standing in for ca-central-1's, which no source has. The lines with no price "
            "stay parameters: " + "; ".join(f["parameters"]) + ". The sizes are lab assumptions, each with its "
            "basis in `volumes.yaml`.", ""]
    split_rows = []
    calls, toks = f["splits"]["gateway calls"], f["splits"]["tokens"]
    direct = {r["workflow"]: r for r in data["month"]["rows"]}
    gpu_b = g["readings"]["manifests and chapter 10"]["split"]
    for w in calls:
        split_rows.append([NAMES[w], pct(calls[w]["share"] * 100, 3), money(calls[w]["usd"]), pct(calls[w]["pct_of_month"], 3),
                           pct(toks[w]["share"] * 100, 3), money(toks[w]["usd"]), pct(toks[w]["pct_of_month"], 3),
                           money(direct[w]["direct_usd"]), money(gpu_b[w]["usd"]) if w in gpu_b else "0"])
    out += [table(["Workflow", "Share of calls", "By calls (USD)", "Of per_month_usd", "Share of tokens",
                   "By tokens (USD)", "Of per_month_usd", "Direct (USD)", "GPU share (USD)"], split_rows), "",
            "Split by gateway calls (O-D6), the fixed costs put "
            f"{pct(calls['w2']['pct_of_month'], 3)} of W2's monthly budget on W2, about "
            f"{round(calls['w2']['usd'] / direct['w2']['direct_usd'])} times its direct cost, so they are shown apart "
            "from the direct costs its owner controls. Chapter 2 splits the shared costs \"in proportion to tokens\" "
            "(ch02:144) and O-D6 by calls; here the two give nearly the same shares, because tokens per call vary "
            "little across the workflows. Calls are the better driver for these lines, since the database, Redis, "
            "the gateway's compute and the trace store grow with requests, while tokens are already the direct "
            "costs. The chapter should name one; if it keeps O-D6's calls, ch02:144 is a second correction for book #23. "
            "O-D6 was amended on 3 November 2026 (companion #14): the fixed costs are split by tokens, "
            f"{pct(toks['w2']['pct_of_month'], 3)} of W2's monthly budget and about "
            f"{round(toks['w2']['usd'] / direct['w2']['direct_usd'])} times its direct cost, and chapter 18 prints "
            "that split."]
    return "\n".join(out)


def sampling(data: dict[str, Any]) -> str:
    s = data["sampling"]
    head_rows, tail_rows = [], []
    for w, r in s["workflows"].items():
        for h in r["head"]:
            e = h["error"]
            head_rows.append([NAMES[w], count(r["runs"]), rate(h["rate"]), pct(e["mean"] * 100, 2),
                              f"{pct(e['p5'] * 100, 2)} to {pct(e['p95'] * 100, 2)}", pct(e["std"] * 100, 2),
                              pct(h["unknown_share"] * 100, 3), count(h["seeds_with_no_trace"])])
        for t in r["tail"]:
            n, wt = t["naive"], t["weighted"]
            tail_rows.append([NAMES[w], pct(r["failed_share"] * 100, 3), rate(t["share_of_the_rest"]),
                              pct(t["kept_share"] * 100, 3), pct(n["mean"] * 100, 3),
                              f"{pct(wt['mean'] * 100, 2)} ({pct(wt['p5'] * 100, 2)} to {pct(wt['p95'] * 100, 2)})"])
    w2 = s["workflows"]["w2"]
    w5 = s["workflows"]["w5"]
    one = next(h for h in w5["head"] if h["rate"] == 0.01)
    w2_one = next(h for h in w2["head"] if h["rate"] == 0.01)["error"]
    return "\n".join([
        "## 11. Sampling: the month from traces", "",
        f"For W1, W2 and W5, a month of runs is drawn from the workflow's kept runs on every model, with seed "
        f"{s['month_seed']} and as many runs as section 9 gives it, each priced by its cost lines; their total is the "
        f"truth. Then, over {s['seeds']:,} seeds, traces are kept by head sampling and the kept runs' cost is scaled "
        "back up. The error is the estimate over the truth, less one. W3 and W4 aren't sampled: only step 3b's runs "
        "of theirs kept tokens.", "",
        table(["Workflow", "Runs", "Head rate", "Mean error", "5th to 95th percentile", "Spread (std)",
               "Runs whose cost is unknown", "Seeds with no trace"], head_rows), "",
        "Head sampling is unbiased at every rate, and exact at 100 percent. Its spread grows as the month shrinks: "
        f"at 1 percent W2's {count(w2['runs'])} runs give a month between {pct(abs(w2_one['p5']) * 100, 2)} below "
        f"and {pct(w2_one['p95'] * 100, 2)} above the truth nine times in ten, and W5's {w5['runs']} nights keep no "
        f"trace at all in {one['seeds_with_no_trace']} of {s['seeds']:,} seeds. At any rate below 100 percent, the "
        "unsampled runs' own cost is unknown from the traces, which is why the cost of a run comes from its cost "
        "lines (O-D5).", "",
        "Tail sampling, as the collector does it (O-D3), keeps every failed run and every run over its budget, and "
        "a share of the rest. A failed run is one whose output failed its golden check, standing in for the error "
        "status a sampler reads; no kept run costs more than its per-run budget at these prices. W2's failed runs "
        f"cost {w2['mean_cost_failed_usd'] / w2['mean_cost_rest_usd']:.1f} times the rest, mostly budget stops.", "",
        table(["Workflow", "Failed", "Share of the rest kept", "Traces kept", "Naive mean error",
               "Weighted mean error (5th to 95th)"], tail_rows), "",
        "Scaled naively, by the share of runs kept, the estimate takes the failed runs' cost for everyone's and "
        f"overstates W2's month by {pct(w2['tail'][0]['naive']['mean'] * 100, 2)} when one in a hundred of the "
        f"rest is kept, and by {pct(w2['tail'][1]['naive']['mean'] * 100, 2)} at one in ten. Weighted, each run "
        "kept from the rest counting for the runs its share stands for, the estimate is unbiased; a trace store "
        "can apply that weight only if each trace records the share it was kept at.",
    ])


def printable(data: dict[str, Any]) -> str:
    t = data["tokens_across_models"]["ratios"]["nova-lite/gpt-oss-20b"]
    m = {r["workflow"]: r for r in data["month"]["rows"]}
    g = data["allocation"]["gpu"]["readings"]["manifests and chapter 10"]
    calls = data["allocation"]["fixed"]["splits"]["gateway calls"]
    w2 = data["sampling"]["workflows"]["w2"]
    return "\n".join([
        "## 12. What the book may print", "",
        "The book prints ratios and shares of the manifests' budgets and never a price (style guide 12.4); the "
        "prices stay in `ledger/prices.yaml`, `ledger.json`, and this record. From this ledger it may print:", "",
        "- Cost per run as a share of `per_run_usd` (section 3), and the month as a share of `per_month_usd` "
        f"(section 9), for example W2's month at {pct(m['w2']['direct_pct_of_month'], 2)} of its budget.",
        "- W2's medians against chapter 3: two model calls and one read, from the kept runs (section 4).",
        f"- The token ratios: Nova Lite counted {t['input']['of_totals']:.2f} times gpt-oss-20b's input and "
        f"{t['output']['of_totals']:.2f} times its output on W1's cases (section 5).",
        "- The guardrail's estimate as a multiple of the tokens' cost, and as a share of a monthly budget (section 8).",
        f"- The GPUs' idle share, {pct(g['idle_share'] * 100)}, and the tenants' token shares (section 10).",
        f"- The fixed costs' shares of calls, W2's {pct(calls['w2']['share'] * 100, 3)}, and their share of each "
        "monthly budget (section 10).",
        f"- The sampling errors, for example W2's month within about {round(max(abs(w2['head'][0]['error']['p5']), w2['head'][0]['error']['p95']) * 100)} "
        "percent nine times in ten at 1 percent, and the naive tail estimate's bias (section 11).",
        "- W3's and W4's tokens per call as multiples of step 2's proxies, and their months as shares of their "
        "budgets before and after (section 13).",
    ])


def _both(values: list[Any], fmt: Any) -> str:
    return " / ".join("none" if v is None else fmt(v) for v in values)


def measured(data: dict[str, Any]) -> str:
    m = data["measured"]
    trows = []
    for r in m["tokens"]:
        for i, label in enumerate(("step 2's proxy", "step 3b, measured")):
            trows.append([NAMES[r["workflow"]], label, r["basis"][i], count(r["runs"][i]), sig(r["calls_per_run"][i], 3),
                          sig(r["restricted_calls_per_run"][i], 2), count(round(r["input_per_call"][i])),
                          count(round(r["output_per_call"][i])), money(r["cost_per_run_usd"][i])])
    mrows = []
    for r in m["month"]:
        mrows.append([NAMES[r["workflow"]], _both(r["tokens_per_month"], count),
                      _both(r["direct_pct_of_month"], lambda v: pct(v, 2)),
                      _both(r["calls_share"], lambda v: pct(v * 100, 3)), _both(r["tokens_share"], lambda v: pct(v * 100, 3)),
                      _both(r["fixed_by_calls_usd"], money), _both(r["fixed_by_tokens_usd"], money),
                      _both(r["gpu_usd"], money)])
    by = {r["workflow"]: r for r in m["tokens"]}
    month_by = {r["workflow"]: r for r in m["month"]}

    def ratio(w: str, key: str) -> str:
        before, after = by[w][key]
        return f"{after / before:.2f}"

    w3, w4 = month_by["w3"], month_by["w4"]
    return "\n".join([
        "## 13. What step 3b's measured tokens changed", "",
        "Step 2 priced W3's and W4's calls by proxy, each at W2's or W5's mean tokens per call on gpt-oss-20b "
        "(`volumes.yaml`, `tokens_proxy`), because their kept runs held no tokens. Step 3b's runs kept the gateway's "
        "lines, and the month now prices both at their own. Step 2's figures here are computed again from chapter "
        "15's kept runs alone, which reproduces them.", "",
        table(["Workflow", "Figures", "Basis", "Runs", "Calls a run", "Restricted calls a run", "Input tokens a call",
               "Output tokens a call", "Cost per run (USD)"], trows), "",
        f"W3's calls carried {ratio('w3', 'input_per_call')} times the proxy's input tokens and "
        f"{ratio('w3', 'output_per_call')} times its output; W4's one call {ratio('w4', 'input_per_call')} times its "
        f"input and {ratio('w4', 'output_per_call')} times its output. Each pair below is step 2's figure, then step "
        "3b's, for every workflow: W2's moves because its golden set ran once more for fig-16-01, and the shares move "
        "with W3's and W4's tokens. The GPU column is the manifests' and chapter 10's reading of the tenants.", "",
        table(["Workflow", "Tokens a month", "Direct share of per_month_usd", "Share of calls", "Share of tokens",
               "Fixed costs by calls (USD)", "Fixed costs by tokens (USD)", "GPU share (USD)"], mrows), "",
        f"W3's month went from {pct(w3['direct_pct_of_month'][0], 2)} to {pct(w3['direct_pct_of_month'][1], 2)} of its "
        f"`per_month_usd` and W4's from {pct(w4['direct_pct_of_month'][0], 2)} to {pct(w4['direct_pct_of_month'][1], 2)}. "
        f"Split by tokens, W3's share of the platform's fixed costs went from {pct(w3['tokens_share'][0] * 100, 3)} to "
        f"{pct(w3['tokens_share'][1] * 100, 3)} and W4's from {pct(w4['tokens_share'][0] * 100, 3)} to "
        f"{pct(w4['tokens_share'][1] * 100, 3)}. Split by calls, which step 2 counted from the kept runs, W3's went "
        f"from {pct(w3['calls_share'][0] * 100, 3)} to {pct(w3['calls_share'][1] * 100, 3)}: step 3b's run made "
        f"{sig(by['w3']['calls_per_run'][1], 3)} calls an incident where the kept run made "
        f"{sig(by['w3']['calls_per_run'][0], 3)}.",
    ])


JUDGE_NAMES = {"gemma4-12b": "Gemma 4 12B", "gpt-oss-20b": "gpt-oss-20b", "both": "both judges"}
ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth")


def _tokens3(t: dict[str, Any]) -> str:
    return f"{count(t['prompt'])} / {count(t['completion'])} / {count(t['total'])}"


def _ratio3(r: dict[str, Any] | None) -> str:
    if r is None:
        return "none"
    return " / ".join("none" if r[k] is None else ratio(r[k]) for k in ("prompt", "completion", "total"))


def _basis(row: dict[str, Any]) -> str:
    return "measured" if row["measured"]["judgments"] else ("stand-in" if row["stand-in"]["judgments"] else "none")


def _join(items: list[str]) -> str:
    """A list in prose: A, B and C."""
    return "none" if not items else items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _day(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%B %Y')}"


def _think(value: Any) -> str:
    if value is False:
        return "thinking off"
    return "thinking at the model's default" if value == "model default" else "thinking varying across its files"


def verdict(j: dict[str, Any]) -> list[str]:
    """What the ratios say about ch15:156, from the data: the median completion tokens and the two populations they
    are over, the totals in completion tokens, the counts by judgment, the all-token ratios, and what is left out.
    The phrases are judge_lines'; the review's section 1 formats the same `conclusion` in fewer words."""
    c, cur = j["conclusion"], j["current_files"]
    by_judge = {r["judge"]: r for r in j["by_judge"] if r["judge"] != "both"}
    judges = [*c["thinking_on"], *c["thinking_off"]]
    states = _join([f"{JUDGE_NAMES[x]} {_think(j['thinking'][x])}" for x in judges])
    medians = _join([f"{half(by_judge[x]['completion_median'])} for {JUDGE_NAMES[x]} over {count(by_judge[x]['judgments'])}"
                     for x in judges])
    current = _join([f"{half(cur[x]['completion_median'])} for {JUDGE_NAMES[x]} over {count(cur[x]['calls'])} calls"
                     for x in judges if x in cur])
    out = [f"Chapter 15 says (ch15:156) that a judge that thinks before it answers writes more tokens than the answer it "
           f"judges. The result files record {states}. The median completion tokens a judgment is {medians} judgments, the "
           f"three runs' judgments that the ledger counts; chapter 15's own medians are over its current files' calls: "
           f"{current}.", ""]
    for x in c["thinking_on"]:
        rows = c["by_judge"].get(x, [])
        above = c["completion_in_total"][x]["above"]
        left = c["not_judged_by"][x]
        out += [f"In completion tokens, in total, {JUDGE_NAMES[x]} wrote {jl.more_or_fewer(rows, above)}: the ratios of its "
                f"completion tokens to the outputs' are {jl.ratios_text(rows, 'completion')}"
                + (f"; {jl.alone_text(left)}" if left else "")
                + f". Judgment by judgment it wrote more than the output in {jl.over_text(rows)}."
                + (" So the sentence holds as written, for completion tokens, in every workflow that judge judged."
                   if rows and len(above) == len(rows) else ""), ""]
        total = c["all_tokens_in_total"][x]
        out += [f"In all tokens, which count a prompt token like a completion token, {JUDGE_NAMES[x]}'s total is "
                f"{jl.sides_text(rows, total['above'])}. These are token figures and not prices.", ""]
    for x in c["thinking_off"]:
        rows = c["by_judge"].get(x, [])
        above = c["completion_in_total"][x]["above"]
        total = c["all_tokens_in_total"][x]
        out += [f"In completion tokens, in total, {JUDGE_NAMES[x]}, with its thinking off, wrote "
                f"{jl.more_or_fewer(rows, above)}: the ratios are {jl.ratios_text(rows, 'completion')}; judgment by judgment "
                f"it wrote more than the output in {jl.over_text(rows)}. In all tokens its total is "
                f"{jl.sides_text(rows, total['above'])}.", ""]
    return out


def judge(data: dict[str, Any]) -> str:
    """Section 14: chapter 15's judge in the ledger, and its tokens against the tokens of the outputs it judged."""
    j = data["judge"]
    by_judge = {r["judge"]: r for r in j["by_judge"]}
    run_rows = [[r["run"], JUDGE_NAMES[r["judge"]], count(r["judgments"]), count(r["judge_tokens"]["prompt"]),
                 count(r["judge_tokens"]["completion"]), count(r["judge_tokens"]["total"]), half(r["completion_median"]),
                 sig(r["seconds"], 4), money(r["usd"])] for r in j["by_run"]]
    wf_rows = []
    for r in j["by_workflow"]:
        basis = _basis(r)
        b = r[basis] if basis != "none" else None
        wf_rows.append([NAMES[r["workflow"]], JUDGE_NAMES[r["judge"]], count(r["judgments"]), _tokens3(r["judge_tokens"]),
                        "none" if b is None else _tokens3(b["judged_tokens"]), "none" if b is None else _ratio3(b["ratio"]),
                        basis])
    detail_rows = []
    for r in j["by_workflow_run"]:
        basis = _basis(r)
        b = r[basis] if basis != "none" else None
        detail_rows.append([NAMES[r["workflow"]], r["run"], JUDGE_NAMES[r["judge"]], count(r["judgments"]),
                            _tokens3(r["judge_tokens"]), "none" if b is None else _tokens3(b["judged_tokens"]),
                            "none" if b is None else _ratio3(b["ratio"]), basis])
    slice_rows = [[r["slice"], count(r["judgments"]), _tokens3(r["judge_tokens"]), half(r["completion_median"]),
                   count(r["measured"]["judgments"]), _tokens3(r["measured"]["judged_tokens"]), _ratio3(r["measured"]["ratio"])]
                  for r in j["by_slice"]]
    sentence_rows = [[NAMES[s["workflow"]], JUDGE_NAMES[s["judge"]], s["basis"], count(s["judgments"]), _ratio3(s["ratio"]),
                      "yes" if s["more_than_the_output"] else "no", "yes" if s["more_completion"] else "no",
                      "yes" if s["more_prompt"] else "no", count(s["completion_over"])] for s in j["sentence"]]
    stand_in = [NAMES[w] for w, basis in j["judged_outputs_basis"].items() if basis == "stand-in"]
    layout, origins = j["layout"], j["origins"]
    last = layout[-1]
    workflow_of = lambda name: NAMES[name.split("-")[1]]  # noqa: E731  judge-w1-gemma4-12b.json -> W1
    own = list(dict.fromkeys(workflow_of(name) for name in last["files"]))
    kept = list(dict.fromkeys(workflow_of(name) for name, run in origins.items() if run != last["run"]))
    kept_from = sorted({run for run in origins.values() if run != last["run"]})
    ordinal = {r["run"]: ORDINALS[i] for i, r in enumerate(layout)}
    earlier = [f"`{r['place'].rsplit('/', 1)[-1]}/`" for r in layout[:-1]]
    by_alias: dict[str, list[str]] = {}
    for key, n in j["by_alias_and_class"].items():
        alias, klass = key.rsplit("/", 1)
        by_alias.setdefault(alias, []).append(f"{klass} {count(n)}")
    aliases = _join([f"`{alias}` ({', '.join(classes)})" for alias, classes in by_alias.items()])
    tag = ("under the judged workflow's tag" if j["tag_is_the_judged_workflows"] == j["calls"]
           else f"under the judged workflow's tag on {count(j['tag_is_the_judged_workflows'])} of them")
    return "\n".join([
        "## 14. The judge's tokens, under the workflow judged", "",
        f"Chapter 15's judge made {count(j['calls'])} judgments in {words(len(layout))} runs on "
        f"{_join([_day(d) for d in j['measured']])}, {count(j['prompt_tokens'])} prompt and {count(j['completion_tokens'])} "
        f"completion tokens, each through chapter 5's gateway {tag} and with the case's class, so each is one cost line here "
        f"under the workflow judged (ch15:305), marked `judge`, with the kept run it read (`judged`) and its slice. Chapter "
        f"15 kept the {' and '.join(ordinal[r['run']] for r in layout[:-1])} runs in {' and '.join(earlier)} and the "
        f"{ordinal[last['run']]} as its current files, which judged {_join(own)} again and hold {_join(kept)}'s files "
        f"of the {_join([ordinal[r] for r in kept_from])} run; "
        f"{count(j['current_log_lines_also_in_a_kept_run'])} lines of the current log are that run's judgments, counted "
        f"once, under the run that made them (`labs/ch15/judge/run_judge.py`'s reading of its folder). The calls went to "
        f"{aliases}; the last column of the first table prices each at its alias's deployment in the dated table "
        f"({money(by_judge['both']['usd'])} USD in all).", "",
        table(["Run", "Judge", "Judgments", "Prompt tokens", "Completion tokens", "Total", "Completion a judgment, median",
               "Seconds", "USD at the table"], run_rows), "",
        f"Against what it judged. Each judgment is set beside the tokens of the output it read: the kept run's own cost lines "
        f"for the case, every model call of the run for W1 to W4 and the one call that wrote the pull request body for W5, "
        f"paired to the night's pull requests in the order it wrote them; a padded copy counts the original's tokens. "
        f"{_join(stand_in)}'s judged outputs are chapter 15's kept runs, which kept no tokens (step 2), so step 3b's "
        f"run of the same case on the same model stands in for them, and the basis column says so; a ratio never mixes the "
        f"two. The ratios are the judge's tokens over the judged outputs' tokens, in total over the group's judgments: "
        f"prompt, completion, and total:", "",
        table(["Workflow", "Judge", "Judgments", "Judge's tokens, prompt / completion / total",
               "Judged outputs' tokens, prompt / completion / total", "Ratio, prompt / completion / total", "Basis"], wf_rows), "",
        *verdict(j),
        table(["Workflow", "Judge", "Basis", "Judgments", "Ratio, prompt / completion / total",
               "In total: more than the output's tokens", "In total: more completion tokens", "In total: more prompt tokens",
               "Judgments with more completion tokens than the output"], sentence_rows), "",
        "By slice, over the judgments whose outputs kept tokens:", "",
        table(["Slice", "Judgments", "Judge's tokens, prompt / completion / total", "Completion a judgment, median",
               "With the output's tokens", "Judged outputs' tokens, prompt / completion / total",
               "Ratio, prompt / completion / total"], slice_rows), "",
        "By workflow, run, and judge:", "",
        table(["Workflow", "Run", "Judge", "Judgments", "Judge's tokens, prompt / completion / total",
               "Judged outputs' tokens, prompt / completion / total", "Ratio, prompt / completion / total", "Basis"], detail_rows),
    ])


def summary(data: dict[str, Any], table_data: dict[str, Any]) -> str:
    n_lines = sum(r["lines"] for r in data["lines"])
    n_runs = sum(r["runs"] for r in data["lines"])
    n_kept = sum(r["kept_runs"] for r in data["lines"])
    n_traced = sum(r["traced_runs"] for r in data["lines"])
    t, c = data["tokens_across_models"], data["w2_against_chapter_3"]
    head = "\n".join([
        "# The ledger, steps 2 and 3b: 3 November 2026", "",
        "Chapter 16's lab, step 2 (companion #14: O-D5, O-D6, and the plan's consistency notes), run again with step "
        f"3b's cost lines. Every model call the workflows kept, {n_lines:,} calls in {n_runs} runs of {n_kept} kept "
        f"runs, {n_kept - n_traced} of them read through chapter 15's registry and {n_traced} made by step 3b through "
        f"the Collector, is one cost line, priced at chapter 6's design from the dated table ({data['table']['entries']} "
        "entries). The ledger itself uses no model, gateway, network, or cloud account.", "",
        "This file is the companion's dated record, so it prints prices; the book prints none, and section 12 "
        "lists what it may print. Per-run figures are measured on the kept runs. Monthly volumes are Larkspur's "
        "estimates where the book states one and lab assumptions where it doesn't (`ledger/volumes.yaml`). The "
        "golden sets were written to test the workflows, so their mix of cases isn't production's: W1's set puts "
        f"{words(len(t['left_out_restricted']))} of its {t['cases']} cases on Restricted pages, and W2's has "
        f"{words(c['golden_refusal_cases'])} refusal cases in {c['golden_cases']}. Per-run figures inherit that mix.",
    ])
    parts = [head, prices(table_data), lines(data), per_run(data), w2(data), across(data), custom(data),
             built_in(data), guardrail(data, table_data), month(data), allocation(data), sampling(data), printable(data),
             measured(data)]
    if "judge" in data:
        parts.append(judge(data))
    return "\n\n".join(parts) + "\n"
