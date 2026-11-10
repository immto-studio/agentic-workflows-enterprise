"""Cost Explorer: whether it answers, and Nova Lite's days against the ledger's cost lines (step 7, item 8).

Cost Explorer can't be enabled by API (fact sheet 8.6); the author opens it once in the console, and if that hasn't
happened the query fails and the reconciliation is skipped (O-D6, amended). When it answers, this asks for the
Bedrock spend by day and usage type over the ledger's Nova Lite days and a day on each side, each request at one US
cent from credits, keeps the Nova Lite usage types, and sets them against the ledger's Nova Lite lines, W1's run of
29 October 2026 on the Canadian profile (results/2026-11-03/costlines.jsonl), priced at the dated table. The filter is the product attribute
`model` set to Nova Lite, as the amended O-D6 asks (the API reference warns that a service's costs can appear under
several service names); if the account refuses that filter, the service's name stands in and the record says so.

Run (from labs/ch16, with the session's environment):
    python cloud/cost_explorer.py --out results/<date>/cloud
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
LAB = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import cloud_session  # noqa: E402

COSTLINES = LAB / "results" / "2026-11-03" / "costlines.jsonl"
PRICES = LAB / "ledger" / "prices.yaml"
PRICE_PER_REQUEST = {"quote": "$0.01 per API Request", "source": "fact sheet 8.8, AWSCostExplorer offer file", "date": "2026-11-03"}


FILTERS = {
    "product attribute model = Nova Lite": {"ProductAttributes": {"Key": "model", "Values": ["Nova Lite"]}},
    "service = Amazon Bedrock": {"Dimensions": {"Key": "SERVICE", "Values": ["Amazon Bedrock"]}},
}


def query(ce: Any, start: date, end: date, filter_expression: dict[str, Any]) -> dict[str, Any]:
    """Cost and usage by day and usage type under one filter; one request, one US cent."""
    return ce.get_cost_and_usage(
        TimePeriod={"Start": start.isoformat(), "End": end.isoformat()}, Granularity="DAILY",
        Metrics=["UnblendedCost", "UsageQuantity"], GroupBy=[{"Type": "DIMENSION", "Key": "USAGE_TYPE"}],
        Filter=filter_expression)


def rows(answer: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for day in answer.get("ResultsByTime", []):
        for group in day.get("Groups", []):
            out.append({"day": day["TimePeriod"]["Start"], "usage_type": group["Keys"][0],
                        "cost_usd": float(group["Metrics"]["UnblendedCost"]["Amount"]),
                        "usage": float(group["Metrics"]["UsageQuantity"]["Amount"]),
                        "unit": group["Metrics"]["UsageQuantity"]["Unit"]})
    return out


def ledger_nova_lite(costlines: Path = COSTLINES, prices: Path = PRICES) -> dict[str, Any]:
    """The ledger's Nova Lite lines by day: tokens in and out, and the cost at the dated table's Canadian price."""
    table = yaml.safe_load(prices.read_text(encoding="utf-8"))
    deployment = next(d for d in table["deployments"] if d["id"] == "nova-lite-ca")
    by_day: dict[str, dict[str, float]] = defaultdict(lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0})
    for line in costlines.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if item.get("model_tag") != "nova-lite":
            continue
        day = item["kept_run"].split()[-1]
        by_day[day]["calls"] += 1
        by_day[day]["input_tokens"] += item.get("input_tokens") or 0
        by_day[day]["output_tokens"] += item.get("output_tokens") or 0
    for day in by_day.values():
        day["cost_usd"] = round(day["input_tokens"] / 1e6 * deployment["input_per_million"]
                                + day["output_tokens"] / 1e6 * deployment["output_per_million"], 6)
    return {"price": {"id": deployment["id"], "input_per_million": deployment["input_per_million"],
                      "output_per_million": deployment["output_per_million"], "date": str(deployment["date"])},
            "days": dict(by_day)}


def tokens(row: dict[str, Any]) -> float:
    """Cost Explorer's quantity as tokens: the Bedrock usage types are metered in thousands."""
    return row["usage"] * (1000 if row.get("unit") == "1K tokens" else 1)


def reconcile(ce_rows: list[dict[str, Any]], ledger: dict[str, Any]) -> list[dict[str, Any]]:
    """Each day either side has Nova Lite on: the bill's tokens and cost beside the ledger's. The bill's days are
    UTC days; the ledger's day is the kept run's date in Toronto, so a run made in the evening sits one day later
    on the bill (`align` sets the two against each other)."""
    nova = [r for r in ce_rows if "novalite" in r["usage_type"].lower().replace("-", "")]
    days = sorted({r["day"] for r in nova} | set(ledger["days"]))
    out = []
    for day in days:
        mine = [r for r in nova if r["day"] == day]
        bill_in = sum(tokens(r) for r in mine if "input" in r["usage_type"].lower())
        bill_out = sum(tokens(r) for r in mine if "output" in r["usage_type"].lower())
        bill_cost = sum(r["cost_usd"] for r in mine)
        led = ledger["days"].get(day)
        out.append({"day": day, "bill_usage_types": sorted({r["usage_type"] for r in mine}),
                    "bill_input_tokens": round(bill_in), "bill_output_tokens": round(bill_out), "bill_cost_usd": round(bill_cost, 6),
                    "ledger_calls": led["calls"] if led else 0,
                    "ledger_input_tokens": led["input_tokens"] if led else 0, "ledger_output_tokens": led["output_tokens"] if led else 0,
                    "ledger_cost_usd": led["cost_usd"] if led else 0.0})
    return out


def align(ce_rows: list[dict[str, Any]], ledger: dict[str, Any], bill_day: str, ledger_day: str,
          prefix: str = "CAN1") -> dict[str, Any]:
    """The bill's day against the ledger's day for one Region's usage types: tokens, cost, and the ratios."""
    mine = [r for r in ce_rows if r["day"] == bill_day and r["usage_type"].startswith(prefix) and "novalite" in r["usage_type"].lower()]
    bill_in = round(sum(tokens(r) for r in mine if "input" in r["usage_type"].lower()))
    bill_out = round(sum(tokens(r) for r in mine if "output" in r["usage_type"].lower()))
    led = ledger["days"].get(ledger_day) or {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    price = ledger["price"]
    bill_at_list = round(bill_in / 1e6 * price["input_per_million"] + bill_out / 1e6 * price["output_per_million"], 6)
    return {"bill_day_utc": bill_day, "ledger_day_toronto": ledger_day, "usage_types": sorted(r["usage_type"] for r in mine),
            "bill_input_tokens": bill_in, "bill_output_tokens": bill_out, "bill_cost_usd": round(sum(r["cost_usd"] for r in mine), 6),
            "bill_at_the_tables_price_usd": bill_at_list,
            "ledger_calls": led["calls"], "ledger_input_tokens": led["input_tokens"], "ledger_output_tokens": led["output_tokens"],
            "ledger_cost_usd": led["cost_usd"],
            "input_ratio_bill_over_ledger": round(bill_in / led["input_tokens"], 3) if led["input_tokens"] else None,
            "output_ratio_bill_over_ledger": round(bill_out / led["output_tokens"], 3) if led["output_tokens"] else None,
            "cost_ratio_at_list_price": round(bill_at_list / led["cost_usd"], 3) if led["cost_usd"] else None}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--margin", type=int, default=1,
                        help="days on each side of the ledger's Nova Lite days (default 1: the bill's days are UTC days)")
    parser.add_argument("--out", type=Path, default=cloud_session.results_dir())
    args = parser.parse_args(argv)
    cloud_session.require_environment()
    s = cloud_session.session()
    ledger = ledger_nova_lite()
    ledger_days = sorted(date.fromisoformat(day) for day in ledger["days"])
    start = ledger_days[0] - timedelta(days=args.margin)
    end = ledger_days[-1] + timedelta(days=args.margin + 1)  # the API's End is exclusive
    record: dict[str, Any] = {"at": cloud_session.utc(), "window": {"start": start.isoformat(), "end": end.isoformat()},
                              "requests": 0, "price_per_request": PRICE_PER_REQUEST, "ledger": ledger}
    ce = s.client("ce", region_name="us-east-1")
    record["attempts"] = []
    for name, expression in FILTERS.items():
        record["requests"] += 1
        try:
            answer = query(ce, start, end, expression)
        except Exception as exc:
            record["attempts"].append({"filter": name, "ok": False, **cloud_session.aws_error(exc)})
            if (cloud_session.aws_error(exc).get("code") or "") not in ("ValidationException", "InvalidParameterValue"):
                break  # Cost Explorer itself refused or isn't enabled; another filter won't change that
            continue
        record["attempts"].append({"filter": name, "ok": True})
        record["filter"] = name
        record["answers"] = True
        record["rows"] = rows(answer)
        record["usage_types"] = sorted({r["usage_type"] for r in record["rows"]})
        record["cost_usd_in_window"] = round(sum(r["cost_usd"] for r in record["rows"]), 6)
        record["reconciliation"] = reconcile(record["rows"], record["ledger"])
        # The ledger's day is the kept run's date in Toronto; the bill's days are UTC days, so a run made in the
        # evening sits on the next day in the bill. The ledger's last day against the day after it.
        last = ledger_days[-1]
        record["aligned"] = align(record["rows"], ledger, (last + timedelta(days=1)).isoformat(), last.isoformat())
        record["skipped"] = False
        break
    else:
        record["answers"] = False
        record["skipped"] = True
    if not record.get("answers"):
        record["answers"] = False
        record["skipped"] = True
        record["why"] = record["attempts"][-1] if record["attempts"] else None
    record["estimated_cost_usd"] = round(record["requests"] * 0.01, 2)
    cloud_session.write_json(args.out / "cost-explorer.json", record)
    print(f"cost explorer answers={record['answers']} skipped={record['skipped']} "
          f"{record.get('why', {}).get('code', '')} rows={len(record.get('rows', []))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
