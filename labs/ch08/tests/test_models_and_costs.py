"""The model register and the cost sheet: the pinned model is one a new subscription can still deploy,
processed in Canada and away from retirement, and the cost sheet prices it where it runs.

Chapter 8. The retirement test reads today's date on purpose: it starts failing 90 days before the
pinned model retires, which is when the register says to move the alias.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

import hcl2
import yaml

LAB = Path(__file__).resolve().parent.parent
REGISTER = yaml.safe_load((LAB / "models.yaml").read_text(encoding="utf-8"))
SHEET = yaml.safe_load((LAB / "cost" / "cost-sheet.yaml").read_text(encoding="utf-8"))
STAGES = ("Preview", "GA", "Legacy", "Deprecated", "Retired")  # Foundry Models lifecycle and support policy


def unquote(value: Any) -> Any:
    """python-hcl2 keeps HCL's quotes and adds bookkeeping keys; drop both."""
    if isinstance(value, dict):
        return {unquote(k): unquote(v) for k, v in value.items() if k not in ("__is_block__", "__comments__")}
    if isinstance(value, str) and len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    return value


def default(name: str) -> Any:
    """A variable's default in terraform/variables.tf."""
    with (LAB / "terraform" / "variables.tf").open(encoding="utf-8") as handle:
        variables = {k: v for block in hcl2.load(handle)["variable"] for k, v in unquote(block).items()}
    return variables[name]["default"]


def pinned() -> tuple[str, dict[str, Any]]:
    marked = [(name, entry) for name, entry in REGISTER.items() if entry["pinned"] is True]
    assert len(marked) == 1, f"one model is pinned, not {[name for name, _ in marked]}"
    return marked[0]


def test_every_model_in_the_register_has_its_stage_retirement_replacement_and_page_dates() -> None:
    for name, entry in REGISTER.items():
        assert isinstance(entry["pinned"], bool) and entry["stage"] in STAGES, name
        assert entry["deployment"] == "Standard" and entry["processed_in_canada"] is True, name
        assert isinstance(entry["retires"], datetime.date) and entry["replacement"] and entry["new_deployments"], name
        assert set(entry["page_dates"]) == {"region_availability", "retirement_schedule", "lifecycle_policy"}, name
        assert all(isinstance(day, datetime.date) for day in entry["page_dates"].values()), name


def test_the_pinned_model_is_the_one_terraform_deploys_in_canada() -> None:
    name, entry = pinned()
    assert default("chat_model") == {"name": name, "version": entry["version"]}
    assert entry["region"] == default("model_location") == "canadaeast"


def test_a_new_subscription_can_still_deploy_the_pinned_model() -> None:
    """GA or Legacy. A Deprecated model is "No longer available to new customers", and whether a
    customer is new is decided per subscription, so a fresh sandbox can't deploy it at all."""
    name, entry = pinned()
    assert entry["stage"] in ("GA", "Legacy"), f"{name} {entry['version']} is {entry['stage']}: pin another model"


def test_the_pinned_model_does_not_retire_within_90_days() -> None:
    name, entry = pinned()
    days = (entry["retires"] - datetime.date.today()).days
    assert days > 90, f"{name} retires on {entry['retires']}: move the alias before pinning again"


def test_the_cost_sheet_is_dated_and_prices_the_pinned_model_where_it_runs() -> None:
    assert SHEET["fetched"] == datetime.date(2026, 10, 29) and SHEET["currency"] == "USD"
    agents, tokens = SHEET["hosted_agents"], SHEET["chat_tokens"]
    assert agents["region"].replace("-", "") == default("location")  # the pricing page writes canada-central
    assert agents["vcpu_per_hour"] > 0 and agents["memory_per_gib_hour"] > 0 and "per hour" in agents["billing"]
    name, entry = pinned()
    assert (tokens["model"], tokens["version"], tokens["deployment"]) == (name, entry["version"], "Standard")
    assert tokens["region"].replace("-", "") == entry["region"]
    assert set(tokens["per_million_tokens"]) == {"input", "cached_input", "output"}
