"""The drift comparison: the masked state of one workspace against the live inventory of its account.

Chapter 14, W5-D5. `compare` is a pure function over what the state reader and the cloud reader returned
(the `terraform show -json` representation, masked; the describe calls' responses; GetResources'
mapping) and gives three kinds of finding, decided by code and never by a model:

- `unmanaged`: a live resource with no state entry of its type and id, unless a tag names a manager other
  than Terraform (the Karpenter nodes of ADR-0052 carry `karpenter.sh/nodepool`; MANAGER_TAGS is the
  list), or it is managed through its parent (a volume that is a state instance's root or block device,
  a snapshot of a managed volume), or AWS made it with the VPC (the `default` security group, the main
  route table). A route in a managed route table that the state's routes do not hold is its own finding,
  keyed by the route's id: the postmortem's shape, the route an apply would remove.
- `changed`: a state resource whose live description differs on a mapped attribute (ATTRIBUTES, per
  type), with both values in the evidence. Security-group rules are compared as sets of (protocol, from,
  to, source); routes as (destination, target), each route its own finding; a volume's attachment as
  the set of (instance, device) its `aws_volume_attachment` resources make. A masked state value
  (`[masked hmac-sha256:...]`) is compared as an opaque string against the live value's own marker, made
  under the same key as the reader's, so a sensitive attribute is compared and neither value leaves (W5-D4).
- `missing`: a state entry of a type the inventory describes with no live resource of its id. Types the
  inventory does not describe (a VPC, an RDS instance, a Lambda) are not compared at all.

Tags are compared without `Name`, the console's label, and without AWS's own `aws:` keys, which the
provider keeps out of `tags` too; the tagging standard's keys are what the comparison sees.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
from collections.abc import Iterable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, NamedTuple

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from findings import MASK_PREFIX, Finding, Scope, finding_key, is_masked, sort_findings  # noqa: E402
from render import template_for  # noqa: E402

__all__ = ["ATTRIBUTES", "MANAGER_TAGS", "IGNORED_TAG_KEYS", "KIND_TYPES", "ManagedResource", "compare",
           "index_state", "index_tags", "live_items", "scope_of", "mask_live", "tags_of", "is_excluded"]

# Tag keys that name a manager other than Terraform: a resource carrying one is somebody else's and is not
# unmanaged drift. The list is configuration (compare's `exclusions`); these are the defaults, each a key the
# named tool writes itself.
MANAGER_TAGS: tuple[str, ...] = (
    "karpenter.sh/nodepool",            # Karpenter's nodes and their root volumes (ADR-0052)
    "karpenter.sh/nodeclaim",
    "eks:nodegroup-name",               # EKS managed node groups
    "aws:autoscaling:groupName",        # Auto Scaling groups
    "aws:cloudformation:stack-id",      # CloudFormation stacks
    "aws:backup:source-resource",       # AWS Backup's recovery points
    "aws:dlm:lifecycle-policy-id",      # Data Lifecycle Manager's snapshots
)
IGNORED_TAG_KEYS: tuple[str, ...] = ("Name",)  # the console's label; the standard does not require it
IGNORED_TAG_PREFIXES: tuple[str, ...] = ("aws:",)  # AWS's own keys, never in a `tags` argument

# The per-type attribute map: what `changed` compares. Routes are compared per route, not as one attribute.
ATTRIBUTES: dict[str, tuple[str, ...]] = {
    "aws_instance": ("instance_type", "ami", "tags"),
    "aws_security_group": ("ingress", "egress"),
    "aws_route_table": ("routes",),
    "aws_ebs_volume": ("size", "type", "attachment"),
    "aws_lb": ("scheme", "type"),
    "aws_ebs_snapshot": (),  # presence only: a snapshot's attributes do not change after it is taken
}
# The describe kinds (cloud_fake.KINDS) and the Terraform type each describes.
KIND_TYPES: dict[str, str] = {
    "instances": "aws_instance", "volumes": "aws_ebs_volume", "snapshots": "aws_ebs_snapshot",
    "security_groups": "aws_security_group", "route_tables": "aws_route_table", "load_balancers": "aws_lb",
}
_ID_FIELDS: dict[str, str] = {
    "instances": "InstanceId", "volumes": "VolumeId", "snapshots": "SnapshotId", "security_groups": "GroupId",
    "route_tables": "RouteTableId", "load_balancers": "LoadBalancerArn",
}
# The route target fields, in the state's names and the describe call's.
_STATE_TARGETS = ("transit_gateway_id", "nat_gateway_id", "gateway_id", "vpc_peering_connection_id",
                  "network_interface_id", "egress_only_gateway_id", "local_gateway_id", "carrier_gateway_id",
                  "vpc_endpoint_id", "core_network_arn")
_LIVE_TARGETS = ("TransitGatewayId", "NatGatewayId", "GatewayId", "VpcPeeringConnectionId", "NetworkInterfaceId",
                 "EgressOnlyInternetGatewayId", "LocalGatewayId", "CarrierGatewayId", "InstanceId", "CoreNetworkArn")
_LOCAL_ROUTE_ORIGINS = ("CreateRouteTable", "EnableVgwRoutePropagation")  # AWS's own routes, never in `route`


class ManagedResource(NamedTuple):
    address: str
    type: str
    values: dict[str, Any]


# --- indexing what the readers returned ---------------------------------------------------------------

def _unwrap_state(state: dict[str, Any]) -> dict[str, Any]:
    """The reader's StateView or the bare masked representation: the representation either way."""
    return state["state"] if "state" in state and "values" not in state else state


def _walk(module: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for resource in module.get("resources", []):
        if resource.get("mode") == "data":  # dropped by the reader; dropped again here for a bare state
            continue
        yield resource
    for child in module.get("child_modules", []):
        yield from _walk(child)


def index_state(state: dict[str, Any]) -> dict[tuple[str, str], ManagedResource]:
    """Every managed resource of the state by (type, id), root module and child modules alike."""
    out: dict[tuple[str, str], ManagedResource] = {}
    for resource in _walk(_unwrap_state(state).get("values", {}).get("root_module", {})):
        values = resource.get("values") or {}
        rid = values.get("id")
        if isinstance(rid, str) and rid:
            out[(resource["type"], rid)] = ManagedResource(resource["address"], resource["type"], values)
    return out


def _inventory_map(inventory: Any) -> dict[str, dict[str, Any]]:
    """kind -> the describe call's result, from a dict or a list of DescribeResult."""
    if isinstance(inventory, dict) and all(isinstance(v, dict) and "kind" in v for v in inventory.values()):
        return {v["kind"]: v for v in inventory.values()}
    if isinstance(inventory, dict):
        return {k: v for k, v in inventory.items() if k in KIND_TYPES}
    return {item["kind"]: item for item in inventory}


def live_items(inventory: Any, kind: str) -> list[dict[str, Any]]:
    """The described objects of one kind, instances flattened out of their reservations."""
    result = _inventory_map(inventory).get(kind)
    if result is None:
        return []
    top = next(iter(result["response"].values()), [])
    if kind == "instances":
        return [i for r in top for i in r.get("Instances", [])]
    return list(top)


def scope_of(state: dict[str, Any], inventory: Any) -> Scope:
    """The workspace from the state view and the account and Region from the inventory."""
    first = next(iter(_inventory_map(inventory).values()))
    workspace = state.get("workspace") if "workspace" in state else ""
    return Scope(workspace=workspace or "", account=first["account"], account_id=first["account_id"],
                 region=first["region"])


def index_tags(*mappings: dict[str, Any]) -> dict[str, dict[str, str]]:
    """GetResources' answers folded into one map by ARN and by the ARN's last path segment (the id), so a
    describe item and a tagging entry meet on the id. The describes' own Tags take precedence in tags_of."""
    out: dict[str, dict[str, str]] = {}
    for mapping in mappings:
        for entry in mapping.get("response", {}).get("ResourceTagMappingList", []):
            tags = {t["Key"]: t["Value"] for t in entry.get("Tags", [])}
            arn = entry["ResourceARN"]
            out.setdefault(arn, {}).update(tags)
            out.setdefault(arn.rsplit("/", 1)[-1], {}).update(tags)
    return out


def tags_of(item: dict[str, Any], kind: str, tags_index: dict[str, dict[str, str]]) -> dict[str, str]:
    """A described object's tags: from its own Tags where the describe call carries them (instances,
    volumes, snapshots, groups, tables), else from the tagging API (load balancers)."""
    if "Tags" in item:
        return {t["Key"]: t["Value"] for t in item["Tags"]}
    rid = item[_ID_FIELDS[kind]]
    return dict(tags_index.get(rid) or tags_index.get(rid.rsplit("/", 1)[-1]) or {})


def is_excluded(tags: dict[str, str], exclusions: Sequence[str]) -> str | None:
    """The manager tag that excludes a resource from `unmanaged`, or None."""
    return next((key for key in exclusions if key in tags), None)


# The masking key, as servers/common.py reads it: W5_MASK_KEY, or the lab's fixed default. The detectors hold it
# for one comparison, a masked state value against a live value's marker; no finding, log, or body carries it.
MASK_KEY_ENV = "W5_MASK_KEY"
LAB_MASK_KEY = "larkspur-w5-lab-mask-key, fixed for the lab and not a secret"


def mask_live(value: Any) -> str:
    """The marker a live value would carry if the state reader had masked it: the same HMAC-SHA256 under the
    same key as servers/common.mask_value, repeated here so the detectors import no server. The test pins
    the two, under the default key and under one from the environment."""
    raw = value if isinstance(value, str) else json.dumps(value, sort_keys=True, separators=(",", ":"),
                                                          ensure_ascii=False)
    key = (os.environ.get(MASK_KEY_ENV, "").strip() or LAB_MASK_KEY).encode("utf-8")
    return MASK_PREFIX + hmac.new(key, raw.encode("utf-8"), hashlib.sha256).hexdigest()[:8] + "]"


# --- the attribute views ---------------------------------------------------------------------------------

def _clean_tags(tags: dict[str, Any]) -> dict[str, str]:
    return {k: str(v) for k, v in sorted(tags.items())
            if k not in IGNORED_TAG_KEYS and not k.startswith(IGNORED_TAG_PREFIXES)}


def _state_rules(rules: list[dict[str, Any]]) -> list[list[Any]]:
    out = []
    for rule in rules or []:
        protocol = str(rule.get("protocol", "-1"))
        frm, to = (0, 0) if protocol == "-1" else (rule.get("from_port", 0), rule.get("to_port", 0))
        sources = [*rule.get("cidr_blocks", []), *rule.get("ipv6_cidr_blocks", []), *rule.get("security_groups", []),
                   *rule.get("prefix_list_ids", []), *(["self"] if rule.get("self") else [])]
        out.extend([protocol, frm, to, source] for source in sources)
    return sorted(out, key=json.dumps)


def _live_rules(permissions: list[dict[str, Any]]) -> tuple[list[list[Any]], dict[str, str]]:
    out, descriptions = [], {}
    for rule in permissions or []:
        protocol = str(rule.get("IpProtocol", "-1"))
        frm, to = (0, 0) if protocol == "-1" else (rule.get("FromPort", 0), rule.get("ToPort", 0))
        sources: list[tuple[str, str]] = []
        sources += [(r["CidrIp"], r.get("Description", "")) for r in rule.get("IpRanges", [])]
        sources += [(r["CidrIpv6"], r.get("Description", "")) for r in rule.get("Ipv6Ranges", [])]
        sources += [(r["GroupId"], r.get("Description", "")) for r in rule.get("UserIdGroupPairs", []) if "GroupId" in r]
        sources += [(r["PrefixListId"], r.get("Description", "")) for r in rule.get("PrefixListIds", [])]
        for source, description in sources:
            entry = [protocol, frm, to, source]
            out.append(entry)
            if description:
                descriptions[json.dumps(entry)] = description
    return sorted(out, key=json.dumps), descriptions


def _state_routes(table: ManagedResource) -> dict[str, str]:
    """destination -> target for a route table's inline routes."""
    out = {}
    for route in table.values.get("route") or []:
        destination = route.get("cidr_block") or route.get("ipv6_cidr_block") or route.get("destination_prefix_list_id")
        target = next((route[f] for f in _STATE_TARGETS if route.get(f)), "")
        if destination:
            out[destination] = target
    return out


def _live_routes(item: dict[str, Any]) -> dict[str, dict[str, str]]:
    """destination -> {target, origin, state} for the routes a person or Terraform made; AWS's local and
    propagated routes are not in a `route` block and are skipped."""
    out = {}
    for route in item.get("Routes", []):
        if route.get("Origin") in _LOCAL_ROUTE_ORIGINS:
            continue
        destination = (route.get("DestinationCidrBlock") or route.get("DestinationIpv6CidrBlock")
                       or route.get("DestinationPrefixListId"))
        target = next((route[f] for f in _LIVE_TARGETS if route.get(f)), "")
        if destination:
            out[destination] = {"target": target, "origin": route.get("Origin", ""), "state": route.get("State", "")}
    return out


def _attachments_in_state(volume_id: str, managed: dict[tuple[str, str], ManagedResource]) -> list[list[str]]:
    return sorted([r.values.get("instance_id", ""), r.values.get("device_name", "")]
                  for (type_, _), r in managed.items()
                  if type_ == "aws_volume_attachment" and r.values.get("volume_id") == volume_id)


def _state_value(resource: ManagedResource, attribute: str, managed: dict[tuple[str, str], ManagedResource]) -> Any:
    values = resource.values
    if attribute == "tags":
        return _clean_tags(values.get("tags") or {})
    if attribute in ("ingress", "egress"):
        return _state_rules(values.get(attribute) or [])
    if attribute == "attachment":
        return _attachments_in_state(values["id"], managed)
    if attribute == "scheme":
        return "internal" if values.get("internal") else "internet-facing"
    if attribute == "type" and resource.type == "aws_lb":
        return values.get("load_balancer_type")
    return values.get(attribute)


def _live_value(item: dict[str, Any], type_: str, attribute: str) -> Any:
    if type_ == "aws_instance":
        return {"instance_type": item.get("InstanceType"), "ami": item.get("ImageId"),
                "tags": _clean_tags({t["Key"]: t["Value"] for t in item.get("Tags", [])})}[attribute]
    if type_ == "aws_security_group":
        return _live_rules(item.get("IpPermissions" if attribute == "ingress" else "IpPermissionsEgress", []))[0]
    if type_ == "aws_ebs_volume":
        if attribute == "attachment":
            return sorted([a.get("InstanceId", ""), a.get("Device", "")] for a in item.get("Attachments", []))
        return {"size": item.get("Size"), "type": item.get("VolumeType")}[attribute]
    if type_ == "aws_lb":
        return {"scheme": item.get("Scheme"), "type": item.get("Type")}[attribute]
    raise KeyError(f"no live view of {type_}.{attribute}")


def _differs(state_value: Any, live_value: Any) -> tuple[bool, Any, Any]:
    """Whether the two differ, and the two values as the evidence may carry them: a masked state value is
    compared with the live value's marker, and the live value itself goes nowhere."""
    if is_masked(state_value):
        live_marker = mask_live(live_value)
        return state_value != live_marker, state_value, live_marker
    return state_value != live_value, state_value, live_value


# --- the comparison ---------------------------------------------------------------------------------------

def _route_finding(scope: Scope, kind: str, table: ManagedResource, destination: str, evidence: dict[str, Any]) -> Finding:
    route_id = f"{table.values['id']}_{destination}"
    finding = Finding(key=finding_key(scope, kind, None, route_id), kind=kind, workspace=scope.workspace,
                      account=scope.account, region=scope.region, resource_type="aws_route", address=None,
                      resource_id=route_id,
                      evidence={"route_table_id": table.values["id"], "route_table_address": table.address,
                                "destination": destination, **evidence})
    return _with_template(finding)


def _with_template(finding: Finding) -> Finding:
    return replace(finding, template=template_for(finding))


# What the next Terraform plan proposes for a finding, in the words a reviewer reads in a plan. Until step 5c these
# said "the next apply": the models repeated it, and the prose seam refuses a reply with that word (README, step 5c).
PLAN_UNMANAGED_ROUTE = "the next plan proposes removing this route: it is not in the route table's code"
PLAN_MISSING_ROUTE = "the next plan proposes re-creating this route from the code"
PLAN_MISSING = "the next plan proposes re-creating this resource from the code unless its block is removed"


def _routes(scope: Scope, table: ManagedResource, item: dict[str, Any]) -> list[Finding]:
    """Each route that is live and not in the state, in the state and not live, or pointed elsewhere."""
    out: list[Finding] = []
    in_state, live = _state_routes(table), _live_routes(item)
    for destination, route in live.items():
        if destination not in in_state:
            out.append(_route_finding(scope, "unmanaged", table, destination,
                                      {"target": route["target"], "origin": route["origin"], "state": route["state"],
                                       "plan": PLAN_UNMANAGED_ROUTE}))
        elif in_state[destination] != route["target"]:
            out.append(_route_finding(scope, "changed", table, destination,
                                      {"attributes": {"target": {"state": in_state[destination], "live": route["target"]}}}))
    for destination, target in in_state.items():
        if destination not in live:
            out.append(_route_finding(scope, "missing", table, destination,
                                      {"target": target, "plan": PLAN_MISSING_ROUTE}))
    return out


def _changed(scope: Scope, resource: ManagedResource, item: dict[str, Any],
             managed: dict[tuple[str, str], ManagedResource]) -> Finding | None:
    attributes: dict[str, Any] = {}
    for attribute in ATTRIBUTES.get(resource.type, ()):
        if attribute == "routes":
            continue
        differs, state_value, live_value = _differs(_state_value(resource, attribute, managed),
                                                    _live_value(item, resource.type, attribute))
        if not differs:
            continue
        entry: dict[str, Any] = {"state": state_value, "live": live_value}
        if attribute in ("ingress", "egress") and not is_masked(state_value):
            _, descriptions = _live_rules(item.get("IpPermissions" if attribute == "ingress" else "IpPermissionsEgress", []))
            entry["added"] = [r for r in live_value if r not in state_value]
            entry["removed"] = [r for r in state_value if r not in live_value]
            entry["descriptions"] = {json.dumps(r): descriptions[json.dumps(r)] for r in entry["added"]
                                     if json.dumps(r) in descriptions}  # author text, carried as data
        attributes[attribute] = entry
    if not attributes:
        return None
    finding = Finding(key=finding_key(scope, "changed", resource.address, resource.values["id"]), kind="changed",
                      workspace=scope.workspace, account=scope.account, region=scope.region, resource_type=resource.type,
                      address=resource.address, resource_id=resource.values["id"], evidence={"attributes": attributes})
    return _with_template(finding)


def _device_volumes(managed: dict[tuple[str, str], ManagedResource]) -> set[str]:
    """Volumes the state manages as a part of an instance: its root and extra block devices."""
    out: set[str] = set()
    for (type_, _), resource in managed.items():
        if type_ != "aws_instance":
            continue
        for field in ("root_block_device", "ebs_block_device"):
            for device in resource.values.get(field) or []:
                if device.get("volume_id"):
                    out.add(device["volume_id"])
    return out


def _unmanaged(scope: Scope, kind: str, item: dict[str, Any], tags: dict[str, str], detail: dict[str, Any]) -> Finding:
    rid = item[_ID_FIELDS[kind]]
    finding = Finding(key=finding_key(scope, "unmanaged", None, rid), kind="unmanaged", workspace=scope.workspace,
                      account=scope.account, region=scope.region, resource_type=KIND_TYPES[kind], address=None,
                      resource_id=rid, evidence={"tags": tags, **detail})
    return _with_template(finding)


def _live_detail(kind: str, item: dict[str, Any]) -> dict[str, Any]:
    """The live attributes an import's resource block needs, by kind."""
    if kind == "instances":
        return {"instance_type": item.get("InstanceType"), "ami": item.get("ImageId"), "subnet_id": item.get("SubnetId"),
                "availability_zone": item.get("Placement", {}).get("AvailabilityZone"),
                "security_group_ids": [g["GroupId"] for g in item.get("SecurityGroups", [])],
                "launched": item.get("LaunchTime")}
    if kind == "volumes":
        return {"availability_zone": item.get("AvailabilityZone"), "size": item.get("Size"), "type": item.get("VolumeType"),
                "iops": item.get("Iops"), "encrypted": item.get("Encrypted"), "created": item.get("CreateTime"),
                "attachments": sorted([a.get("InstanceId", ""), a.get("Device", "")] for a in item.get("Attachments", []))}
    if kind == "snapshots":
        return {"volume_id": item.get("VolumeId"), "started": item.get("StartTime"), "volume_size": item.get("VolumeSize"),
                "description": item.get("Description", "")}
    if kind == "security_groups":
        rules, _ = _live_rules(item.get("IpPermissions", []))
        egress, _ = _live_rules(item.get("IpPermissionsEgress", []))
        return {"name": item.get("GroupName"), "description": item.get("Description", ""), "vpc_id": item.get("VpcId"),
                "ingress": rules, "egress": egress}
    if kind == "route_tables":
        return {"vpc_id": item.get("VpcId"), "routes": _live_routes(item),
                "main": any(a.get("Main") for a in item.get("Associations", []))}
    if kind == "load_balancers":
        return {"name": item.get("LoadBalancerName"), "scheme": item.get("Scheme"), "type": item.get("Type"),
                "vpc_id": item.get("VpcId"), "subnets": [z.get("SubnetId") for z in item.get("AvailabilityZones", [])],
                "security_group_ids": list(item.get("SecurityGroups", []))}
    return {}


def _missing(scope: Scope, resource: ManagedResource) -> Finding:
    finding = Finding(key=finding_key(scope, "missing", resource.address, resource.values["id"]), kind="missing",
                      workspace=scope.workspace, account=scope.account, region=scope.region, resource_type=resource.type,
                      address=resource.address, resource_id=resource.values["id"],
                      evidence={"state": {k: v for k, v in resource.values.items() if k in ("size", "type", "instance_type",
                                                                                          "availability_zone", "name")},
                                "plan": PLAN_MISSING})
    return _with_template(finding)


def compare(state: dict[str, Any], inventory: Any, tags_by_resource: Any = None,
            exclusions: Sequence[str] = MANAGER_TAGS) -> list[Finding]:
    """The drift of one workspace against its account: unmanaged, changed, and missing, sorted.

    `state` is the state reader's view (or the bare masked representation), `inventory` the six describe
    results keyed by kind (or a list of them), `tags_by_resource` GetResources' mapping(s) for the account,
    `exclusions` the tag keys that name another manager."""
    scope = scope_of(state, inventory)
    managed = index_state(state)
    tags_index = index_tags(*([tags_by_resource] if isinstance(tags_by_resource, dict) else tags_by_resource or []))
    device_volumes = _device_volumes(managed)
    managed_volumes = {rid for (type_, rid) in managed if type_ == "aws_ebs_volume"} | device_volumes
    out: list[Finding] = []
    seen: set[tuple[str, str]] = set()

    for kind, type_ in KIND_TYPES.items():
        for item in live_items(inventory, kind):
            rid = item[_ID_FIELDS[kind]]
            resource = managed.get((type_, rid))
            tags = tags_of(item, kind, tags_index)
            if resource is not None:
                seen.add((type_, rid))
                if type_ == "aws_route_table":
                    out.extend(_routes(scope, resource, item))
                changed = _changed(scope, resource, item, managed)
                if changed is not None:
                    out.append(changed)
                continue
            # Not in the state: somebody else's, a part of a managed resource, AWS's own, or unmanaged.
            manager = is_excluded(tags, exclusions)
            if manager is not None:
                continue
            if kind == "volumes" and rid in device_volumes:
                continue
            if kind == "snapshots" and item.get("VolumeId") in managed_volumes:
                continue
            if kind == "security_groups" and item.get("GroupName") == "default":
                continue
            if kind == "route_tables" and any(a.get("Main") for a in item.get("Associations", [])):
                continue
            out.append(_unmanaged(scope, kind, item, tags, _live_detail(kind, item)))

    described = set(KIND_TYPES.values())
    for (type_, rid), resource in managed.items():
        if type_ in described and (type_, rid) not in seen:
            out.append(_missing(scope, resource))
    return sort_findings(out)
