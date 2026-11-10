"""The dated table: a source, a date and a page on every entry; the values the cost sheets hold; the quotes
the fact sheet gives; a reason or the vendor's words for every price that is null."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Any

import yaml

import price
import registry

NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
PRICE_KEYS = ("input_per_million", "output_per_million", "cache_read_per_million", "cached_input_per_million",
              "per_hour", "per_month", "per_gb_month", "per_gb", "per_gb_hour", "per_span", "per_request",
              "per_million_ecpus", "input_per_1k_tpm_hour", "output_per_1k_tpm_hour", "per_month_reserved",
              "per_year_reserved", "per_1000_text_units")


def leaves(value: Any) -> list[Any]:
    if isinstance(value, dict):
        return [leaf for v in value.values() for leaf in leaves(v)]
    return [value]


def numbers(quotes: Any) -> set[Decimal]:
    texts = quotes if isinstance(quotes, list) else [quotes]
    return {Decimal(m.replace(",", "")) for text in texts for m in NUMBER.findall(text)}


def test_every_entry_has_a_source_a_date_and_a_page(table) -> None:
    entries = price.entries(table)
    assert len(entries) == len({e["id"] for e in entries}) == 49
    for e in entries:
        assert e.get("source") and e.get("page"), e["id"]
        assert isinstance(e.get("date"), date), e["id"]
        assert date(2026, 10, 28) <= e["date"] <= date(2026, 11, 3), e["id"]
        assert any(k in e for k in PRICE_KEYS), e["id"]


def test_the_values_copied_from_a_cost_sheet_are_the_sheets(table) -> None:
    copied = [e for e in price.entries(table) if "sheet" in e]
    assert len(copied) == 11
    for e in copied:
        sheet = yaml.safe_load(registry.path(e["source"]).read_text(encoding="utf-8"))
        for field, where in e["sheet"].items():
            value = sheet
            for key in where:
                value = value[key]
            mine = e["per_1000_text_units"][field] if "per_1000_text_units" in e else e[field]
            assert Decimal(str(value)) == Decimal(str(mine)), (e["id"], field)


def test_the_prices_from_the_fact_sheet_carry_their_quote(table) -> None:
    quoted = [e for e in price.entries(table) if e["source"].startswith("fact sheet")]
    assert len(quoted) == 33
    for e in quoted:
        assert e.get("quote"), e["id"]
        found = numbers(e["quote"])
        for key in PRICE_KEYS:
            for value in leaves(e.get(key)):
                if value is not None:
                    assert Decimal(str(value)) in found, (e["id"], key, value)


def test_the_canadian_and_us_rates_were_confirmed_on_3_november(table) -> None:
    for d in table["deployments"]:
        if "confirmed" not in d:
            continue
        found = numbers(d["confirmed"]["quote"])
        assert d["confirmed"]["date"] == date(2026, 11, 3)
        assert Decimal(str(d["input_per_million"])) / 1000 in found, d["id"]
    ca = price.by_id(table)["nova-lite-ca"]
    assert Decimal(str(ca["output_per_million"])) / 1000 in numbers(ca["confirmed"]["quote"])


def test_a_null_price_says_why(table) -> None:
    nulls = []
    for e in price.entries(table):
        values = [v for key in PRICE_KEYS for v in leaves(e.get(key)) if key in e]
        if any(v is None for v in values):
            nulls.append(e["id"])
            assert e.get("reason") or e.get("vendor_words"), e["id"]
    assert set(nulls) == {"gemini-3.5-flash-montreal", "aws-g6e.2xlarge-l40s-cac1", "psc-endpoint-google",
                          "private-endpoints-azure", "litellm-enterprise", "langfuse-enterprise"}
    entries = price.by_id(table)
    assert entries["litellm-enterprise"]["vendor_words"] == "Pricing depends on your deployment size. Get in touch to scope it."
    assert entries["langfuse-enterprise"]["vendor_words"] == "Custom Pricing"


def test_chapter_6s_design_prices_every_alias_a_kept_run_asked_for(runs, table) -> None:
    asked = {line.alias for run in runs for line in run.lines}
    assert asked <= set(table["design"])
    for alias, deployment in table["design"].items():
        d = price.by_id(table)[deployment]
        assert d["alias"] == alias and d["input_per_million"] is not None
    assert price.deployment(table, "larkspur-chat-restricted")["input_per_million"] == 0
    assert table["fallbacks"] == {"larkspur-chat": "larkspur-chat-fallback"}


def test_the_canadian_profile_costs_about_7_percent_more_than_us_east_2(table) -> None:
    """ch06:162: called in ca-central-1, Nova Lite costs about 7 percent more than in us-east-2."""
    ca, us = price.deployment(table, "larkspur-chat"), price.deployment(table, "larkspur-chat-fallback")
    for key in ("input_per_million", "output_per_million"):
        ratio = Decimal(str(ca[key])) / Decimal(str(us[key]))
        assert round(ratio, 3) == Decimal("1.067")
