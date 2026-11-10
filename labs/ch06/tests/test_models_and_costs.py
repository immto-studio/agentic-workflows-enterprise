"""The model register and the dated cost sheet: the pinned model keeps Confidential data in Canada,
the gateway calls the model the register pins, and the sheet's sums are the sums of its rates.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

LAB = Path(__file__).resolve().parent.parent
CANADA = {"ca-central-1", "ca-west-1"}
TODAY = date(2026, 10, 29)  # the day the register was read; the 180-day check counts from the run


def load(name: str) -> dict[str, Any]:
    return yaml.safe_load((LAB / name).read_text(encoding="utf-8"))


MODELS = load("models.yaml")
COSTS = load("cost/cost-sheet.yaml")
GATEWAY = {entry["model_name"]: entry for entry in load("gateway/litellm.aws.yaml")["model_list"]}


def test_one_model_is_pinned_and_it_is_active_and_served_in_canada_only() -> None:
    pinned = [model_id for model_id, model in MODELS.items() if model["pinned"]]
    assert pinned == ["amazon.nova-lite-v1:0"]
    model = MODELS[pinned[0]]
    assert model["processed_in_canada"] and set(model["serves_from"]) <= CANADA
    assert model["lifecycle"] == "Active"
    assert model["eol"] is None or model["eol"] > max(date.today(), TODAY) + timedelta(days=180)


def test_a_model_that_can_be_served_outside_canada_is_never_marked_canadian() -> None:
    for model_id, model in MODELS.items():
        assert model["processed_in_canada"] == (set(model["serves_from"]) <= CANADA), model_id
        if model["lifecycle"] == "Legacy":
            assert model["eol"] and not model["pinned"], model_id  # new customers can't adopt a Legacy model


def test_the_gateway_calls_the_pinned_model_through_its_canada_profile_and_prices_it_as_the_sheet_does() -> None:
    entry = GATEWAY["larkspur-chat"]
    assert entry["litellm_params"]["model"] == "bedrock/converse/ca.amazon.nova-lite-v1:0"
    assert entry["model_info"]["serves_from"] == MODELS["amazon.nova-lite-v1:0"]["serves_from"]
    for alias, region in (("larkspur-chat", "ca-central-1"), ("larkspur-chat-fallback", "us-east-2")):
        rates = COSTS["bedrock"]["nova_lite"][region]
        params = GATEWAY[alias]["litellm_params"]
        assert params["aws_region_name"] == region
        assert round(params["input_cost_per_token"] * 1e6, 6) == rates["input_per_million"]
        assert round(params["output_cost_per_token"] * 1e6, 6) == rates["output_per_million"]


def test_the_sheet_is_dated_and_names_an_offer_for_every_block() -> None:
    assert COSTS["fetched"] == TODAY and COSTS["currency"] == "USD"
    for block in ("agentcore", "bedrock", "s3_vectors", "vpc_endpoints", "opensearch_serverless"):
        assert re.search(r", published 2026-\d\d-\d\d$", COSTS[block]["offer"]), block


def test_a_legacy_notice_on_the_pinned_model_needs_the_weekly_fallback_call() -> None:
    for model_id, model in MODELS.items():
        if model.get("pinned"):
            assert "legacy_from" in model and "extended_access_from" in model, model_id
            if model["legacy_from"]:
                assert model["fallback_weekly_call"] is True, model_id


def test_the_idle_month_is_the_endpoints_and_matches_the_terraform() -> None:
    idle = COSTS["idle_month"]
    network = (LAB / "terraform" / "network.tf").read_text(encoding="utf-8")
    block = re.search(r"interface_endpoints = \{(.*?)\n  \}", network, re.S)
    assert block and len(re.findall(r'^\s+"[a-z.-]+"\s+=', block.group(1), re.M)) == idle["interface_endpoints"]["count"]
    endpoints = idle["interface_endpoints"]
    usd = endpoints["count"] * endpoints["zones"] * COSTS["vpc_endpoints"]["interface_endpoint_hour"] * idle["hours"]
    assert round(usd, 2) == endpoints["usd"]
    keys = idle["kms_keys"]
    assert keys["count"] * COSTS["kms"]["customer_managed_key_version_month"] == keys["usd"]
    assert len(re.findall(r'^resource "aws_kms_key"', (LAB / "terraform" / "kms.tf").read_text(encoding="utf-8"), re.M)) == keys["count"]
    assert round(endpoints["usd"] + keys["usd"], 2) == idle["usd"]
    assert round(idle["usd"] / 150, 2) == idle["share_of_budget"]


def test_the_opensearch_serverless_trap_is_the_rate_times_the_floor() -> None:
    trap, rate = COSTS["opensearch_serverless_trap"], COSTS["opensearch_serverless"]["search_ocu_hour"]
    assert round(trap["classic_minimum_ocus"] * rate * 730, 2) == trap["classic_idle_month_usd"]
    assert round(rate * 730, 2) == trap["classic_dev_test_idle_month_usd"]
    assert round(trap["classic_idle_month_usd"] / 150, 2) == trap["classic_idle_month_as_budgets"]
    assert trap["nextgen_idle_month_usd"] == 0.0
