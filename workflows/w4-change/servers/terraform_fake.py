"""The Terraform-plan fake: the resource changes a change would make, with destroys and replaces marked.

Chapter 13, W4-D5. When a change touches Terraform, the analyst reads the plan's resource changes as
evidence (the shape follows Terraform's JSON plan: each resource change has an address, a type, and an
`actions` list such as `create`, `update`, `delete`, or `delete` then `create` for a replace). A destroy
or a replace is a fact the evidence pack carries for the board; the plan is attached, never applied
(W4 is rung 2). Changes with no Terraform have no plan.
"""

from __future__ import annotations

from typing import TypedDict


class ResourceChange(TypedDict):
    address: str
    type: str
    actions: list[str]


class Plan(TypedDict):
    change_ref: str
    resource_changes: list[ResourceChange]
    has_destroy: bool
    has_replace: bool


_PLANS: dict[str, list[ResourceChange]] = {
    "fraud-scoring#120": [
        ResourceChange(address="aws_sagemaker_endpoint.fraud", type="aws_sagemaker_endpoint",
                       actions=["delete", "create"]),  # a replace: the endpoint is recreated
        ResourceChange(address="aws_iam_role_policy.fraud_invoke", type="aws_iam_role_policy",
                       actions=["update"]),
    ],
    "claims-api#500": [
        ResourceChange(address="aws_dynamodb_table.billing_ledger", type="aws_dynamodb_table",
                       actions=["delete"]),  # a destroy in the payments slice
    ],
    "quote-engine#88": [
        ResourceChange(address="aws_dynamodb_table.quote_rates", type="aws_dynamodb_table",
                       actions=["delete"]),  # a destroy: the rate store is torn down
    ],
}


def plan(change_ref: str) -> Plan | None:
    """The Terraform plan for a change, or None when the change touches no Terraform."""
    changes = _PLANS.get(change_ref)
    if not changes:
        return None
    return Plan(change_ref=change_ref, resource_changes=changes,
                has_destroy=any("delete" in c["actions"] and "create" not in c["actions"] for c in changes),
                has_replace=any("delete" in c["actions"] and "create" in c["actions"] for c in changes))
