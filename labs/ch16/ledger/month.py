"""A month of the ledger: each workflow's direct cost, and the costs that aren't a call, allocated.

Chapter 16, step 2 (companion #14, O-D5, O-D6, O-D15). The volumes come from volumes.yaml, each with its
source: a line of the book, or "lab assumption, not in the book". The per-run figures come from the kept
runs on the reference model (gpt-oss-20b, which every workflow ran on and chapter 9's restricted alias
serves), priced at chapter 6's design by price.py. Every kept run on that model counts, the early ones
too, and the range across the kept runs goes beside the pooled figure.

W3's and W4's kept runs hold no tokens. Step 2 counted their calls from what they kept and priced them at
another workflow's mean tokens per call on the same model (volumes.yaml, `tokens_proxy`). Step 3b ran both
through the Collector and kept the gateway's cost lines (costlines.traced_runs), so a workflow's profile now
comes from its runs that kept tokens, and its row says how many of its runs those are. The proxy stays for a
workflow with no such run, and the report computes step 2's month from chapter 15's kept runs alone to set
the two side by side.

Direct costs are the cost lines, summed by workflow and month. The rest is allocated and shown apart:

- The GPUs of chapter 9: two replicas, every hour of the month. The share of their hours the tenants
  used is their busy time, the tokens they sent the restricted alias at chapter 9's measured throughput,
  over the replicas' hours; that part is split among the tenants by their share of the alias's tokens, and
  the idle remainder is the platform team's line (O-D6). Which workflows are tenants is a consistency
  note of the plan, so the split is computed for each reading: chapter 9's (W2 and W3), and the manifests'
  with chapter 10's (W1, W2, W3).
- The platform's fixed costs (volumes.yaml, `platform.fixed`) split by each workflow's share of gateway
  calls (O-D6), and, for comparison, by its share of tokens, which is chapter 2's rule (ch02:144). A line
  with no price is a parameter: listed, never summed.
"""

from __future__ import annotations

import json
import statistics
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import costlines  # noqa: E402
import price  # noqa: E402
import registry  # noqa: E402

VOLUMES = HERE / "volumes.yaml"
WORKFLOWS = ("w1", "w2", "w3", "w4", "w5")  # the skeleton is chapter 5's, run by no one in production
RESTRICTED = costlines.RESTRICTED_ALIAS
READINGS = {
    "chapter 9": ("w2", "w3"),                       # ch09:18, ch09:200: "Two workflows share the replicas"
    "manifests and chapter 10": ("w1", "w2", "w3"),  # each manifest's models; ch10:72, "from month six"
}


def load_volumes(path: Path = VOLUMES) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def usd(value: Decimal | None, places: int = 8) -> float | None:
    return None if value is None else float(round(value, places))


def share(part: Decimal | float, whole: Decimal | float) -> float | None:
    return None if not whole else float(Decimal(str(part)) / Decimal(str(whole)))


def pct(part: Decimal | float | None, whole: Decimal | float) -> float | None:
    return None if part is None or not whole else round(float(Decimal(str(part)) / Decimal(str(whole)) * 100), 6)


@dataclass(frozen=True)
class Profile:
    """One workflow's run, on the reference model: means over its kept runs, or the proxy's."""
    workflow: str
    basis: str                     # "measured", or "proxy: <workflow>'s tokens per call"
    kept_runs: tuple[str, ...]
    runs: int
    calls: float                   # model calls per run
    restricted_calls: float
    input: float                   # tokens per run, every call
    output: float
    restricted_input: float        # tokens per run sent to the restricted alias
    restricted_output: float
    cost: Decimal                  # USD per run at chapter 6's design
    guardrail: Decimal             # the guardrail's estimate per run
    cost_by_kept_run: dict[str, Decimal]
    tokens_by_kept_run: dict[str, float]


def _mean(values: Iterable[float]) -> float:
    values = list(values)
    return statistics.fmean(values) if values else 0.0


def _measured(workflow: str, mine: list[costlines.Run], table: dict[str, Any], basis: str = "measured") -> Profile:
    by_kept: dict[str, list[costlines.Run]] = {}
    for run in mine:
        by_kept.setdefault(run.kept_run, []).append(run)
    tokens = [run.tokens() for run in mine]
    restricted = [run.tokens(RESTRICTED) for run in mine]
    costs = [price.run_cost(table, run) for run in mine]
    guard = [price.run_guardrail(table, run) for run in mine]
    n = Decimal(len(mine))
    return Profile(
        workflow, basis, tuple(by_kept), len(mine), _mean(r.model_calls for r in mine),
        _mean(sum(1 for line in r.lines if line.alias == RESTRICTED) for r in mine),
        _mean(t[0] for t in tokens), _mean(t[1] for t in tokens),
        _mean(t[0] for t in restricted), _mean(t[1] for t in restricted),
        sum(costs, Decimal(0)) / n, sum(guard, Decimal(0)) / n,
        {k: sum((price.run_cost(table, r) for r in rs), Decimal(0)) / len(rs) for k, rs in by_kept.items()},
        {k: _mean(sum(r.tokens()) for r in rs) for k, rs in by_kept.items()},
    )


def _per_call(runs: list[costlines.Run]) -> tuple[float, float]:
    calls = sum(r.model_calls for r in runs)
    tokens = [r.tokens() for r in runs]
    return sum(t[0] for t in tokens) / calls, sum(t[1] for t in tokens) / calls


def _proxied(workflow: str, mine: list[costlines.Run], source: list[costlines.Run], source_name: str,
             table: dict[str, Any]) -> Profile:
    """The workflow's own calls, each at the source workflow's mean tokens per call."""
    tin, tout = _per_call(source)
    calls = _mean(r.model_calls for r in mine)
    rcalls = _mean(sum(1 for line in r.lines if line.alias == RESTRICTED) for r in mine)
    managed = calls - rcalls
    chat = price.deployment(table, "larkspur-chat")
    p_in, p_out = price.per_token(chat["input_per_million"]), price.per_token(chat["output_per_million"])
    cost = Decimal(str(managed)) * (Decimal(str(tin)) * p_in + Decimal(str(tout)) * p_out)
    g = table["guardrail"]
    unit = sum((price.dec(g["per_1000_text_units"][p]) for p in g["policies"]), Decimal(0)) / 1000
    units = price.text_units(table, round(tin)) + price.text_units(table, round(tout))
    kept = tuple(dict.fromkeys(r.kept_run for r in mine))
    return Profile(workflow, f"proxy: {source_name.upper()}'s tokens per call", kept, len(mine), calls, rcalls,
                   calls * tin, calls * tout, rcalls * tin, rcalls * tout, cost,
                   Decimal(str(managed)) * units * unit, {k: cost for k in kept}, {k: calls * (tin + tout) for k in kept})


def profiles(runs: list[costlines.Run], table: dict[str, Any], volumes: dict[str, Any]) -> dict[str, Profile]:
    model = volumes["reference_model"]
    on_model = {w: [r for r in runs if r.workflow == w and r.model == model] for w in costlines.ORDER}
    out = {}
    for w in WORKFLOWS:
        mine = on_model[w]
        if not mine:
            raise ValueError(f"{w} kept no run on {model}")
        measured = [r for r in mine if r.tokens_kept]
        if len(measured) == len(mine):
            out[w] = _measured(w, mine, table)
        elif measured:  # step 3b's runs kept the tokens the earlier runs didn't
            out[w] = _measured(w, measured, table, f"measured on the {len(measured)} of {len(mine)} runs with tokens")
        else:
            source = volumes["tokens_proxy"][w]["from"]
            out[w] = _proxied(w, mine, on_model[source], source, table)
    return out


def runs_per_month(volumes: dict[str, Any], prof: dict[str, Profile]) -> dict[str, float]:
    out = {}
    for w in WORKFLOWS:
        v = volumes["workflows"][w]
        if "tokens" in v:
            out[w] = v["tokens"] / (prof[w].input + prof[w].output)
        elif "parts" in v:
            out[w] = float(sum(part["runs"] for part in v["parts"].values()))
        else:
            out[w] = float(v["runs"])
    return out


def _sources(v: dict[str, Any]) -> list[str]:
    if "parts" in v:
        return [f"{name}: {part['source']}" for name, part in v["parts"].items()]
    return [v["source"]]


def month(runs: list[costlines.Run], table: dict[str, Any], volumes: dict[str, Any],
          ratios: dict[str, float] | None = None) -> dict[str, Any]:
    """Each workflow's month: runs, calls, tokens, direct cost and the guardrail's estimate, against
    per_month_usd. `ratios` (input, output) recount the managed alias's tokens the way Nova Lite counts."""
    prof = profiles(runs, table, volumes)
    per_month = runs_per_month(volumes, prof)
    chat = price.deployment(table, "larkspur-chat")
    p_in, p_out = price.per_token(chat["input_per_million"]), price.per_token(chat["output_per_million"])
    rows = []
    for w in WORKFLOWS:
        p, n = prof[w], Decimal(str(per_month[w]))
        budget = registry.manifest(w)["budget"]
        direct = n * p.cost
        by_kept = {}
        for k, c in p.cost_by_kept_run.items():
            if "tokens" in volumes["workflows"][w]:  # a volume in tokens: the month is tokens x cost per token
                by_kept[k] = Decimal(str(volumes["workflows"][w]["tokens"])) * c / Decimal(str(p.tokens_by_kept_run[k]))
            else:
                by_kept[k] = n * c
        recounted = None
        if ratios:
            managed_in, managed_out = p.input - p.restricted_input, p.output - p.restricted_output
            recounted = n * (Decimal(str(managed_in * ratios["input"])) * p_in
                             + Decimal(str(managed_out * ratios["output"])) * p_out)
        rows.append({
            "workflow": w, "volume": volumes["workflows"][w], "sources": _sources(volumes["workflows"][w]),
            "basis": p.basis, "kept_runs": list(p.kept_runs), "runs_in_profile": p.runs,
            "runs_per_month": round(per_month[w], 2), "calls_per_run": round(p.calls, 4),
            "calls_per_month": round(per_month[w] * p.calls, 2),
            "tokens_per_month": round(per_month[w] * (p.input + p.output)),
            "restricted_tokens_per_month": round(per_month[w] * (p.restricted_input + p.restricted_output)),
            "cost_per_run_usd": usd(p.cost, 10), "direct_usd": usd(direct),
            "per_month_usd": budget["per_month_usd"], "direct_pct_of_month": pct(direct, budget["per_month_usd"]),
            "direct_pct_range_over_kept_runs": [pct(min(by_kept.values()), budget["per_month_usd"]),
                                                pct(max(by_kept.values()), budget["per_month_usd"])],
            "recounted_as_nova_lite_usd": usd(recounted),
            "recounted_pct_of_month": pct(recounted, budget["per_month_usd"]),
            "guardrail_usd": usd(n * p.guardrail), "guardrail_pct_of_month": pct(n * p.guardrail, budget["per_month_usd"]),
            "guardrail_over_tokens": None if not p.cost else round(float(p.guardrail / p.cost), 2),
        })
    return {"reference_model": volumes["reference_model"], "month_hours": volumes["month_hours"], "rows": rows,
            "profiles": {w: {k: v for k, v in asdict(prof[w]).items() if k not in ("cost_by_kept_run", "tokens_by_kept_run")}
                         | {"cost": usd(prof[w].cost, 10), "guardrail": usd(prof[w].guardrail, 10)} for w in WORKFLOWS}}


# --- the allocation (O-D6) --------------------------------------------------------------------------------

def _throughput(volumes: dict[str, Any]) -> dict[str, float]:
    data = registry.read_json(registry.path(volumes["platform"]["gpu"]["throughput"]["file"]))
    return {"prompt_tokens_per_second": data["median_prompt_tok_s"], "output_tokens_per_second": data["median_output_tok_s"]}


def gpu(month_rows: dict[str, Any], table: dict[str, Any], volumes: dict[str, Any]) -> dict[str, Any]:
    g = volumes["platform"]["gpu"]
    entry = price.by_id(table)[g["price"]]
    cost = Decimal(g["replicas"]) * Decimal(g["hours"]) * price.dec(entry["per_hour"])
    rate = _throughput(volumes)
    capacity = g["replicas"] * g["hours"] * 3600
    prof = month_rows["profiles"]
    per_month = {r["workflow"]: r["runs_per_month"] for r in month_rows["rows"]}
    sent = {}
    for w in WORKFLOWS:
        tin = per_month[w] * prof[w]["restricted_input"]
        tout = per_month[w] * prof[w]["restricted_output"]
        busy = tin / rate["prompt_tokens_per_second"] + tout / rate["output_tokens_per_second"]
        sent[w] = {"input_tokens": round(tin), "output_tokens": round(tout), "busy_seconds": round(busy, 3)}
    readings = {}
    for name, tenants in READINGS.items():
        tokens = {w: sent[w]["input_tokens"] + sent[w]["output_tokens"] for w in tenants}
        busy = sum(sent[w]["busy_seconds"] for w in tenants)
        used = cost * Decimal(str(busy)) / Decimal(capacity)
        whole = sum(tokens.values())
        split = {}
        for w in tenants:
            part = used * Decimal(tokens[w]) / Decimal(whole) if whole else Decimal(0)
            without_idle = cost * Decimal(tokens[w]) / Decimal(whole) if whole else Decimal(0)
            budget = registry.manifest(w)["budget"]["per_month_usd"]
            split[w] = {"tokens": tokens[w], "token_share": share(tokens[w], whole), "usd": usd(part),
                        "pct_of_month": pct(part, budget), "without_idle_line_usd": usd(without_idle),
                        "without_idle_line_pct_of_month": pct(without_idle, budget)}
        readings[name] = {"tenants": list(tenants), "busy_seconds": round(busy, 3),
                          "used_share": share(busy, capacity), "used_usd": usd(used),
                          "idle_usd": usd(cost - used), "idle_share": share(cost - used, cost), "split": split}
    return {"replicas": g["replicas"], "hours": g["hours"], "price": g["price"], "per_hour": entry["per_hour"],
            "usd": usd(cost), "throughput": rate, "capacity_seconds": capacity, "sent": sent, "readings": readings}


def fixed(month_rows: dict[str, Any], table: dict[str, Any], volumes: dict[str, Any]) -> dict[str, Any]:
    prices = price.by_id(table)
    hours = Decimal(volumes["month_hours"])
    lines, total, stand_ins = [], Decimal(0), Decimal(0)
    for item in volumes["platform"]["fixed"]:
        entry = prices[item["price"]]
        unit_key = {"hour": "per_hour", "gb_month": "per_gb_month", "month": "per_month"}[item["per"]]
        unit = entry.get(unit_key)
        amount = None
        if unit is not None:
            amount = Decimal(item["quantity"]) * price.dec(unit) * (hours if item["per"] == "hour" else 1)
            total += amount
            if item.get("stand_in"):
                stand_ins += amount
        lines.append({"item": item["item"], "price": item["price"], "quantity": item["quantity"], "per": item["per"],
                      "unit_usd": unit, "usd": usd(amount), "stand_in": bool(item.get("stand_in")),
                      "parameter": unit is None, "source": item["source"],
                      "words": entry.get("vendor_words") or entry.get("reason")})
    rows = {r["workflow"]: r for r in month_rows["rows"]}
    splits = {}
    for basis, key in (("gateway calls", "calls_per_month"), ("tokens", "tokens_per_month")):
        whole = sum(rows[w][key] for w in WORKFLOWS)
        split = {}
        for w in WORKFLOWS:
            part = total * Decimal(str(rows[w][key])) / Decimal(str(whole))
            split[w] = {"share": share(rows[w][key], whole), "usd": usd(part),
                        "pct_of_month": pct(part, rows[w]["per_month_usd"])}
        splits[basis] = split
    return {"lines": lines, "priced_usd": usd(total), "stand_in_usd": usd(stand_ins),
            "parameters": [line["item"] for line in lines if line["parameter"]], "splits": splits}


def allocation(month_rows: dict[str, Any], table: dict[str, Any], volumes: dict[str, Any]) -> dict[str, Any]:
    return {"gpu": gpu(month_rows, table, volumes), "fixed": fixed(month_rows, table, volumes)}


def main(argv: list[str] | None = None) -> int:
    runs = costlines.collect()
    table, volumes = price.load(), load_volumes()
    m = month(runs, table, volumes)
    print(json.dumps({"month": m["rows"], "allocation": allocation(m, table, volumes)}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
