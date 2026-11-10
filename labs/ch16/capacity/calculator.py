"""When does committed capacity cost less than paying per token?

Chapter 16, step 5 (companion #14, O-D9), in the manner of chapter 9's crossover (`labs/ch09/cost/crossover.py`).
Committed capacity is bought in units, each carrying so many tokens a minute, and paid for every hour of its
term whether or not anyone calls it. On-demand capacity is paid per token. A workflow sizes the commitment for
its busy hour and uses it, on average, for its duty cycle, so the question has two numbers:

    utilization u  = the share of the bought capacity the workflow's tokens fill over the term
                   = duty cycle / k, where k is how far the busy hour's mix can grow before a unit is full
    break-even u*  = the commitment's hourly price / the on-demand price of a full hour of the same capacity

and the commitment costs less exactly when u > u*. The busy hour, its token mix and its duty cycle come from
`busy_hour.yaml` and the ledger; the prices from the dated table (`ledger/prices.yaml`, section `committed`); the
unit, the minimum and the burndown from `units.yaml`, each with the fact sheet's words.

Three numbers make the answer honest when an input is missing:

- u* needs the on-demand rate of the same model in the same place. The table has it only for Nova Lite, and
  only in us-east-2, which stands in for us-east-1. For the other three, `--on-demand-input` and
  `--on-demand-output` take it, and without them the calculator says what it lacks.
- 1 - u is the discount below the on-demand rate that the commitment's full-use rate would need for this
  workflow to break even. It needs no on-demand rate at all.
- `busy_hours_to_break_even` is the commitment's hour over the on-demand price of the workflow's busy hour: how
  many busy hours of tokens it must carry every hour to pay off. It needs no unit size, so it answers for Nova
  Lite's model units, whose tokens a minute the fact sheet doesn't give.

The book prints the ratios (style guide 12.4); the prices stay in the table and in `calculator.json`.

Run:  python capacity/calculator.py --workflow w2
      python capacity/calculator.py --workflow w3 --product azure-ptu-gpt-5.5-regional-canadaeast
      python capacity/calculator.py --report results/<date>/capacity      # every line for W2 and W3
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
LAB = HERE.parent
LEDGER = LAB / "ledger"
BUDGET = LAB / "budget"
COMPANION = LAB.parents[1]
for folder in (LEDGER, BUDGET):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

UNITS = HERE / "units.yaml"
BUSY = HERE / "busy_hour.yaml"
MILLION = Decimal(1_000_000)
SIXTY = Decimal(60)


def dec(value: Any) -> Decimal:
    return Decimal(str(value))


def ceil_dec(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_CEILING))


def ratio(value: Decimal | None, places: int = 6) -> float | None:
    """A ratio for the record: six significant digits, as a float."""
    if value is None:
        return None
    if value == 0:
        return 0.0
    return float(f"{value:.{places}g}")


# --- the inputs -------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Profile:
    """A workflow's busy hour: tokens a minute in and out on the managed model, and its duty cycle."""

    workflow: str
    name: str
    busy_hour_runs: float
    runs_per_month: float
    input_per_run: Decimal
    output_per_run: Decimal
    duty_cycle: Decimal
    per_month_usd: Decimal
    direct_month_usd: Decimal | None
    self_hosted_input_per_run: Decimal = Decimal(0)
    self_hosted_output_per_run: Decimal = Decimal(0)

    @property
    def busy_input_tpm(self) -> Decimal:
        return dec(self.busy_hour_runs) * self.input_per_run / SIXTY

    @property
    def busy_output_tpm(self) -> Decimal:
        return dec(self.busy_hour_runs) * self.output_per_run / SIXTY


def load_profiles(busy_path: Path = BUSY, ledger_json: Path | None = None) -> dict[str, Profile]:
    """W2's and W3's busy hours, from busy_hour.yaml and the ledger's month."""
    spec = yaml.safe_load(busy_path.read_text(encoding="utf-8"))
    ledger = json.loads((ledger_json or LAB / spec["ledger"]).read_text(encoding="utf-8"))
    rows = {row["workflow"]: row for row in ledger["month"]["rows"]}
    profiles = {}
    hours = dec(spec["month_hours"])
    for key, w in spec["workflows"].items():
        p = ledger["month"]["profiles"][key]
        row = rows[key]
        managed_in = dec(p["input"]) - dec(p.get("restricted_input") or 0)
        managed_out = dec(p["output"]) - dec(p.get("restricted_output") or 0)
        runs = dec(row["runs_per_month"])
        busy = dec(w["busy_hour_runs"])
        profiles[key] = Profile(
            workflow=w["workflow"], name=key, busy_hour_runs=float(busy), runs_per_month=float(runs),
            input_per_run=managed_in, output_per_run=managed_out, duty_cycle=runs / (hours * busy),
            per_month_usd=dec(row["per_month_usd"]), direct_month_usd=dec(row["direct_usd"]),
            self_hosted_input_per_run=dec(p.get("restricted_input") or 0),
            self_hosted_output_per_run=dec(p.get("restricted_output") or 0))
    return profiles


def load_units(path: Path = UNITS) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def term_price(entry: dict[str, Any], term: dict[str, Any]) -> Decimal:
    """The term's price for one unit for one hour."""
    field = term.get("field", "per_hour")
    value: Any = entry
    for key in (field if isinstance(field, list) else [field]):
        value = value[key]
    return dec(value) / dec(term.get("hours", 1))


# --- one line --------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Line:
    workflow: str
    product: str
    term: str
    endpoint: str | None
    busy_input_tpm: float
    busy_output_tpm: float
    duty_cycle: float
    units_the_busy_hour_needs: float | None   # before the minimum; None when a unit's size isn't known
    units_bought: float
    unit_kind: str
    hourly_usd: float                         # the commitment, every hour of the term
    month_usd: float
    month_over_per_month_usd: float           # the commitment's month as a multiple of the manifest's budget
    month_over_direct_month: float | None     # ... and of what the workflow's tokens cost a month today (ledger)
    busy_hour_fills: float | None             # the share of the bought capacity the busy hour fills
    utilization: float | None                 # u: the share the workflow fills over the term
    discount_needed: float | None             # 1 - u
    on_demand: str | None                     # the comparator's id in the table, or "given"
    on_demand_stand_in: str | None
    on_demand_input_per_million: float | None
    on_demand_output_per_million: float | None
    break_even_utilization: float | None      # u*
    busy_hours_to_break_even: float | None    # the commitment's hour over the on-demand price of a busy hour
    on_demand_over_committed: float | None    # over the term; above 1 the commitment costs less
    full_use_per_million_usd: float | None    # the commitment's price per million tokens of this mix at full use
    lacks: str | None                         # what the calculator needed and the table doesn't hold


def capacity(product: dict[str, Any], profile: Profile) -> tuple[float | None, float, Decimal | None]:
    """(units the busy hour needs, units bought, k): k is how far the busy mix can grow before a unit is full."""
    unit, minimum = product["unit"], product["minimum"]
    busy_in, busy_out = profile.busy_input_tpm, profile.busy_output_tpm
    kind = unit["kind"]
    if kind == "reserved_tpm":
        size = dec(unit["tokens_per_minute"])
        need_in, need_out = ceil_dec(busy_in / size), ceil_dec(busy_out / size)
        units_in = max(need_in, ceil_dec(dec(minimum["input_tpm"]) / size))
        units_out = max(need_out, ceil_dec(dec(minimum["output_tpm"]) / size))
        limits = [units_in * size / busy_in] if busy_in else []
        limits += [units_out * size / busy_out] if busy_out else []
        return float(need_in + need_out), float(units_in + units_out), min(limits)
    if kind in ("normalized_tpm", "burndown_tps"):
        per_minute = dec(unit["tokens_per_minute"]) if kind == "normalized_tpm" else dec(unit["tokens_per_second"]) * SIXTY
        weighted = busy_in + dec(unit["output_weight"]) * busy_out
        need = ceil_dec(weighted / per_minute)
        units = max(need, int(minimum["units"]))
        step = int(minimum.get("increment", 1))
        units = ceil_dec(dec(units) / dec(step)) * step
        return float(need), float(units), dec(units) * per_minute / weighted
    if kind == "model_unit":
        return None, float(minimum["units"]), None
    raise ValueError(f"unknown unit kind {kind!r}")


def hourly_price(product: dict[str, Any], entry: dict[str, Any], term: dict[str, Any], profile: Profile,
                 units: float) -> Decimal:
    if product["unit"]["kind"] == "reserved_tpm":
        size = dec(product["unit"]["tokens_per_minute"])
        minimum = product["minimum"]
        units_in = max(ceil_dec(profile.busy_input_tpm / size), ceil_dec(dec(minimum["input_tpm"]) / size))
        units_out = max(ceil_dec(profile.busy_output_tpm / size), ceil_dec(dec(minimum["output_tpm"]) / size))
        return units_in * dec(entry["input_per_1k_tpm_hour"]) + units_out * dec(entry["output_per_1k_tpm_hour"])
    return dec(units) * term_price(entry, term)


def on_demand_rates(product: dict[str, Any], table: dict[str, Any], given: tuple[float, float] | None
                    ) -> tuple[str | None, Decimal | None, Decimal | None, str | None]:
    """(comparator, input per token, output per token, why none) for the product."""
    if given is not None:
        return "given", dec(given[0]) / MILLION, dec(given[1]) / MILLION, None
    comparator = product.get("on_demand")
    if not comparator:
        return None, None, None, product.get("on_demand_reason")
    import price

    entry = price.by_id(table)[comparator]
    return comparator, dec(entry["input_per_million"]) / MILLION, dec(entry["output_per_million"]) / MILLION, None


def compute(product: dict[str, Any], term: dict[str, Any], profile: Profile, table: dict[str, Any],
            month_hours: Decimal, given: tuple[float, float] | None = None) -> Line:
    import price

    entry = price.by_id(table)[term["price"]]
    need, units, k = capacity(product, profile)
    hourly = hourly_price(product, entry, term, profile, units)
    month = hourly * month_hours
    d = profile.duty_cycle
    u = d / k if k else None
    comparator, p_in, p_out, why = on_demand_rates(product, table, given)
    busy_tokens = profile.busy_input_tpm + profile.busy_output_tpm
    od_busy_hour = None if p_in is None else SIXTY * (profile.busy_input_tpm * p_in + profile.busy_output_tpm * p_out)
    break_even = hourly / (k * od_busy_hour) if (k and od_busy_hour) else None
    multiple = hourly / od_busy_hour if od_busy_hour else None
    cost_ratio = d * od_busy_hour / hourly if od_busy_hour else None
    full_use = hourly / (SIXTY * k * busy_tokens) * MILLION if (k and busy_tokens) else None
    lacks = None
    if p_in is None:
        lacks = f"the on-demand rate ({why})"
    elif k is None:
        lacks = "the tokens a minute one unit carries, which the fact sheet doesn't give"
    stand_in = product.get("on_demand_stand_in") if comparator not in (None, "given") else None
    return Line(
        workflow=profile.workflow, product=product["id"], term=term["term"], endpoint=term.get("endpoint"),
        busy_input_tpm=ratio(profile.busy_input_tpm), busy_output_tpm=ratio(profile.busy_output_tpm),
        duty_cycle=ratio(d), units_the_busy_hour_needs=need, units_bought=units, unit_kind=product["unit"]["kind"],
        hourly_usd=ratio(hourly, 8), month_usd=ratio(month, 8),
        month_over_per_month_usd=ratio(month / profile.per_month_usd),
        month_over_direct_month=ratio(month / profile.direct_month_usd) if profile.direct_month_usd else None,
        busy_hour_fills=ratio(1 / k) if k else None, utilization=ratio(u), discount_needed=ratio(1 - u) if u else None,
        on_demand=comparator, on_demand_stand_in=stand_in,
        on_demand_input_per_million=ratio(p_in * MILLION) if p_in is not None else None,
        on_demand_output_per_million=ratio(p_out * MILLION) if p_out is not None else None,
        break_even_utilization=ratio(break_even), busy_hours_to_break_even=ratio(multiple),
        on_demand_over_committed=ratio(cost_ratio), full_use_per_million_usd=ratio(full_use, 8), lacks=lacks)


def lines_for(profile: Profile, units: dict[str, Any], table: dict[str, Any], product_id: str | None = None,
              given: tuple[float, float] | None = None) -> list[Line]:
    out = []
    for product in units["products"]:
        if product_id and product["id"] != product_id:
            continue
        for term in product["terms"]:
            out.append(compute(product, term, profile, table, dec(units["month_hours"]), given))
    return out


# --- the self-hosted path ----------------------------------------------------------------------------------

def self_hosted(profile: Profile, busy_path: Path = BUSY) -> dict[str, Any]:
    """The busy hour's Restricted calls set against chapter 9's measured single-stream speeds, reused, not remeasured."""
    spec = yaml.safe_load(busy_path.read_text(encoding="utf-8"))["self_hosted"]
    measured = json.loads((COMPANION / spec["file"]).read_text(encoding="utf-8"))
    prompt_tps = dec(measured[spec["prompt_tokens_per_second"]])
    output_tps = dec(measured[spec["output_tokens_per_second"]])
    runs = dec(profile.busy_hour_runs)
    seconds = runs * (profile.self_hosted_input_per_run / prompt_tps + profile.self_hosted_output_per_run / output_tps)
    replicas = dec(spec["replicas"])
    return {"workflow": profile.workflow, "busy_hour_runs": profile.busy_hour_runs,
            "input_tokens": ratio(runs * profile.self_hosted_input_per_run),
            "output_tokens": ratio(runs * profile.self_hosted_output_per_run),
            "measured": {"file": spec["file"], "prompt_tokens_per_second": float(prompt_tps),
                         "output_tokens_per_second": float(output_tps)},
            "replica_seconds": ratio(seconds), "share_of_one_replica_hour": ratio(seconds / Decimal(3600)),
            "share_of_the_floor": ratio(seconds / (Decimal(3600) * replicas)), "replicas": int(replicas)}


# --- the report --------------------------------------------------------------------------------------------

def report(units_path: Path = UNITS, busy_path: Path = BUSY) -> dict[str, Any]:
    import price

    table = price.load()
    units = load_units(units_path)
    profiles = load_profiles(busy_path)
    out: dict[str, Any] = {"profiles": {}, "lines": [], "self_hosted": [], "products": []}
    for key, profile in profiles.items():
        out["profiles"][key] = {
            "workflow": profile.workflow, "busy_hour_runs": profile.busy_hour_runs,
            "runs_per_month": profile.runs_per_month,
            "input_per_run": ratio(profile.input_per_run), "output_per_run": ratio(profile.output_per_run),
            "busy_input_tpm": ratio(profile.busy_input_tpm), "busy_output_tpm": ratio(profile.busy_output_tpm),
            "duty_cycle": ratio(profile.duty_cycle), "per_month_usd": float(profile.per_month_usd),
            "direct_month_usd": ratio(profile.direct_month_usd)}
        out["lines"] += [asdict(line) for line in lines_for(profile, units, table)]
        out["self_hosted"].append(self_hosted(profile, busy_path))
    for product in units["products"]:
        out["products"].append({k: product.get(k) for k in ("id", "cloud", "what", "serves", "data_classes",
                                                               "unit", "minimum", "on_demand", "on_demand_reason",
                                                               "on_demand_stand_in")})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--workflow", choices=("w2", "w3"))
    parser.add_argument("--product", help="one product's id from units.yaml")
    parser.add_argument("--on-demand-input", type=float, help="the on-demand rate, USD per million input tokens")
    parser.add_argument("--on-demand-output", type=float, help="... and per million output tokens")
    parser.add_argument("--report", type=Path, help="write calculator.json for W2 and W3 into this folder")
    args = parser.parse_args(argv)
    if args.report:
        import record

        record.write_json(args.report / "calculator.json", report())
        print(f"wrote {args.report / 'calculator.json'}")
        return 0
    if not args.workflow:
        parser.error("--workflow or --report")
    if (args.on_demand_input is None) != (args.on_demand_output is None):
        parser.error("--on-demand-input and --on-demand-output go together")
    import price

    given = (args.on_demand_input, args.on_demand_output) if args.on_demand_input is not None else None
    profile = load_profiles()[args.workflow]
    lines = lines_for(profile, load_units(), price.load(), args.product, given)
    print(json.dumps([asdict(line) for line in lines], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
