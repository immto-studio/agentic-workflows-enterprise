"""The fixture night: the detectors run over the fakes for one workspace, as the harness of step 4 will run
them over the readers.

Chapter 14, W5-D11 and W5-D13. `gather` reads what the night needs for one workspace straight from the
fake modules (the state, the six describes, the tag mapping for each required key, the seven-day CPU
series per instance, the cost export of the last complete month, the standard, the approved exceptions),
`findings_from` runs the comparison, the four detectors, the suppression, and the attribution over it,
and `findings_for` does both. The tests and validate.py's command use them; the harness replaces `gather`
with its tool calls and keeps `findings_from`, whose inputs are exactly the readers' return shapes.

`with_strings_replaced` is for the structural-layer test (W5-D12): the same inputs with the planted
texts replaced by neutral ones, the lookup included, so the two runs can be compared.
"""

from __future__ import annotations

import copy
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SERVERS = HERE.parent / "servers"
for folder in (HERE, SERVERS):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import cloud_fake  # noqa: E402
import cost_fake  # noqa: E402
import policy_fake  # noqa: E402
import state_fake  # noqa: E402
from attribution import attribute_all  # noqa: E402
from common import NIGHT  # noqa: E402
from drift import compare, live_items, scope_of  # noqa: E402
from findings import Finding, sort_findings  # noqa: E402
from waste import IDLE_WINDOW_DAYS, detect_waste, managed_by_id, suppress  # noqa: E402

__all__ = ["PAIRS", "Inputs", "billing_period_before", "gather", "findings_from", "findings_for", "with_strings_replaced"]

# workspace -> the account behind it (catalog/workspace-map.yaml lists both; the pairing is the lab's)
PAIRS: dict[str, str] = {"network-live": "lm-network-prod", "claims-api-prod": "lm-claims-prod", "sandbox-quill": "lm-sandbox"}


@dataclass(frozen=True)
class Inputs:
    workspace: str
    account: str
    state: dict[str, Any]
    inventory: dict[str, dict[str, Any]]
    tags: list[dict[str, Any]]
    cpu: dict[str, dict[str, Any]]
    export: dict[str, Any]
    standard: dict[str, Any]
    exceptions: dict[str, Any]
    lookup: Callable[..., dict[str, Any]]


def billing_period_before(night: datetime) -> str:
    """The last complete billing month before the night: the one the saving estimate reads."""
    return (night.date().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")


def gather(workspace: str, night: datetime = NIGHT) -> Inputs:
    account, region = PAIRS[workspace], cloud_fake.REGION
    inventory = {kind: cloud_fake.describe_resources(account, region, kind) for kind in cloud_fake.KINDS}
    standard = policy_fake.get_tagging_standard()
    return Inputs(
        workspace=workspace, account=account, state=state_fake.get_state(workspace), inventory=inventory,
        tags=[cloud_fake.get_resources_by_tag(account, region, key) for key in standard["required_tags"]],
        cpu={i["InstanceId"]: cloud_fake.get_cpu_utilization(account, region, i["InstanceId"], IDLE_WINDOW_DAYS)
             for i in live_items(inventory, "instances")},
        export=cost_fake.read_cost_export(account, billing_period_before(night)), standard=standard,
        exceptions=policy_fake.list_policy_exceptions("approved"), lookup=cloud_fake.lookup_events)


def findings_from(inputs: Inputs, night: datetime = NIGHT) -> list[Finding]:
    """The night's findings for one workspace: drift, waste, the exceptions applied, each attributed."""
    scope = scope_of(inputs.state, inputs.inventory)
    found = compare(inputs.state, inputs.inventory, inputs.tags)
    found += detect_waste(scope, inputs.inventory, inputs.tags, inputs.standard, inputs.cpu, inputs.export, night,
                          managed_by_id(inputs.state))
    found = suppress(found, inputs.exceptions, night)
    return sort_findings(attribute_all(found, inputs.lookup))


def findings_for(workspace: str, night: datetime = NIGHT) -> list[Finding]:
    return findings_from(gather(workspace, night), night)


def _replaced(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, str):
        for old, new in replacements.items():
            value = value.replace(old, new)
        return value
    if isinstance(value, dict):
        return {k: _replaced(v, replacements) for k, v in value.items()}
    if isinstance(value, list):
        return [_replaced(v, replacements) for v in value]
    return value


def with_strings_replaced(inputs: Inputs, replacements: dict[str, str]) -> Inputs:
    """A deep copy of the inputs with every occurrence of each key replaced by its value, in the reader
    results and in what the lookup returns."""
    lookup = inputs.lookup

    def replaced_lookup(**kwargs: Any) -> dict[str, Any]:
        return _replaced(lookup(**kwargs), replacements)

    return replace(inputs, state=_replaced(copy.deepcopy(inputs.state), replacements),
                   inventory=_replaced(copy.deepcopy(inputs.inventory), replacements),
                   tags=_replaced(copy.deepcopy(inputs.tags), replacements), cpu=_replaced(copy.deepcopy(inputs.cpu), replacements),
                   export=_replaced(copy.deepcopy(inputs.export), replacements), lookup=replaced_lookup)
