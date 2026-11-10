"""Pricing at chapter 6's design, a fallback at its own Region's price, the guardrail's estimate apart, and
the table as LiteLLM's custom prices, with LiteLLM 1.106.6 checked in this process and nothing sent."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from conftest import line

import price
import registry


def test_a_line_is_priced_at_the_deployment_its_alias_names(table) -> None:
    assert price.line_cost(table, line()) == Decimal("0.0000896")  # 1,000 x 0.064 + 100 x 0.256, per million


def test_a_fallback_is_priced_at_its_own_regions_price(table) -> None:
    served = line(fallback=True, served_alias="larkspur-chat-fallback")
    unnamed = line(fallback=True)  # a fallback line that doesn't say which alias served it: the chain's next
    assert price.line_cost(table, served) == price.line_cost(table, unnamed) == Decimal("0.000084")
    assert price.serving_alias(table, unnamed) == "larkspur-chat-fallback"


def test_the_restricted_alias_costs_nothing_per_token(table) -> None:
    restricted = line(alias="larkspur-chat-restricted", served_alias="larkspur-chat-restricted", data_class="restricted")
    assert price.line_cost(table, restricted) == 0
    assert price.guardrail_estimate(table, restricted) == 0  # no guardrail on the self-hosted alias


def test_a_run_without_tokens_has_no_cost_never_zero(runs, table) -> None:
    import costlines

    for run in runs:
        cost = price.run_cost(table, run)
        if run.workflow in ("w3", "w4") and not costlines.is_traced(run):  # chapter 15's runs of W3 and W4 kept no tokens
            assert cost is None and price.run_guardrail(table, run) is None
        else:
            assert cost == sum((price.line_cost(table, line) for line in run.lines), Decimal(0))


def test_the_ledger_prices_w1s_nova_lite_calls_as_the_gateway_did(runs, table) -> None:
    """The Nova Lite run's gateway priced its calls with chapter 6's custom prices; the ledger agrees."""
    kept = next(k for k in registry.kept_runs("w1") if k.model == "nova-lite")
    data = registry.read_json(registry.path(kept.main))
    mine = {r.case: r for r in runs if r.workflow == "w1" and r.model == "nova-lite"}
    compared = 0
    for record in data["results"]:
        run = mine[f"{record['id']}/{record['persona']}"]
        for line_, usage in zip(run.lines, record["model_calls"]):
            if usage["cost_usd"] is None:  # the restricted alias, served by gpt-oss-20b at zero
                assert line_.alias == "larkspur-chat-restricted"
                continue
            assert float(price.line_cost(table, line_)) == pytest.approx(usage["cost_usd"], rel=1e-12, abs=1e-15)
            compared += 1
    assert compared == 48


def test_the_guardrail_estimate_counts_text_units_both_ways(table) -> None:
    # 1,000 tokens in is 4,000 characters, four text units; 100 out is 400 characters, one; content and
    # sensitive information together are 0.25 per 1,000 units.
    assert price.guardrail_estimate(table, line()) == Decimal("0.00125")
    assert price.guardrail_estimate(table, line(input_tokens=None)) is None


def test_the_custom_price_yaml_is_the_tables(table) -> None:
    committed = price.LITELLM_YAML.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert committed == price.litellm_yaml(table)
    lists = price.litellm_model_lists(table)
    assert set(lists) == {"aws", "azure"}
    aws = {e["model_name"]: e for e in lists["aws"]}
    assert aws["larkspur-chat"]["litellm_params"]["input_cost_per_token"] == 6.4e-08
    assert aws["larkspur-chat-restricted"]["litellm_params"]["input_cost_per_token"] == 0


@pytest.fixture(scope="module")
def checked(table) -> list[dict]:
    return price.check_litellm(table)


def test_litellm_charges_the_custom_price_on_every_deployment(checked) -> None:
    priced = [r for r in checked if r["deployment"] != "(by name only)"]
    assert {r["deployment"] for r in priced} == {"nova-lite-ca", "nova-lite-us", "vllm-gpt-oss-20b",
                                                 "titan-embed-v2-ca", "gpt-4o-canada-east"}
    for r in priced:
        assert r["response_cost_usd"] == pytest.approx(r["expected_usd"], rel=1e-9, abs=1e-15), r
        if r["completion_cost_usd"] is not None:
            assert r["completion_cost_usd"] == pytest.approx(r["expected_usd"], rel=1e-9, abs=1e-15), r
    canada = next(r for r in priced if r["deployment"] == "nova-lite-ca")
    assert canada["expected_usd"] == pytest.approx(0.0000896) and canada["input_tokens"] == 1000


def test_a_zero_price_skips_every_budget_check_and_leaves_the_rate(checked) -> None:
    skipped = {r["alias"] for r in checked if r["budget_checks_skipped"]}
    assert skipped == {"larkspur-chat-restricted"}
    listing = [w for w in ("w1", "w2", "w3", "w4", "w5") if "larkspur-chat-restricted" in registry.manifest(w)["models"]]
    assert listing == ["w1", "w2", "w3"]
    for w in listing:
        assert registry.manifest(w)["budget"]["requests_per_minute"] > 0


def test_the_canadian_deployment_by_name_alone_prices_at_zero(checked) -> None:
    by_name = next(r for r in checked if r["deployment"] == "(by name only)")
    assert by_name["completion_cost_usd"] == 0.0
    json.dumps(checked)  # the report embeds the rows as JSON


def test_the_check_refuses_without_the_local_map(table, monkeypatch) -> None:
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "False")
    with pytest.raises(RuntimeError, match="LITELLM_LOCAL_MODEL_COST_MAP"):
        price.check_litellm(table)
