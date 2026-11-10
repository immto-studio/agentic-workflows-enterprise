"""Who made the change: a finding attributed from CloudTrail's event history, through the cloud reader's lookup.

Chapter 14, W5-D5. `attribute` takes a finding and the cloud reader's `lookup_events` (a callable with the
tool's own arguments, so the harness passes the server's tool and the tests the fake), asks by
`ResourceName` with the resource's id first, then by `EventName` for the event names that explain the
finding where the resource lookup matched nothing (C.2: one attribute per call, ninety days), and picks
the latest event that explains it: `AuthorizeSecurityGroupIngress` for a rule added to a group,
`CreateRoute` for a route (matched on the route's destination in the request), `ModifyInstanceAttribute`
for a type change, `TerminateInstances` or `DeleteVolume` for a resource that is gone, the creation event
for an unmanaged or an unattached resource. The chapter's first finding comes out attributed to the
Jenkins job's IAM user, `jenkins-deploy-prod`, with its user agent.

What is recorded is what the trail holds: the event's name, id, and time, the username, the principal's
ARN and type, the source address, and the user agent parsed out of `CloudTrailEvent`. A user agent is
whatever string the caller's client sent (W5-D12): it is carried as data in the attribution and read by
nothing here, which the structural-layer test shows with the planted one.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from findings import Finding  # noqa: E402

__all__ = ["CREATES", "DELETES", "CHANGES", "LOOKUP_DAYS", "explaining_events", "lookup_ids", "attribute",
           "attribute_all"]

LOOKUP_DAYS = 90  # the event history's depth (cloud_fake.MAX_LOOKUP_DAYS); older changes are a trail's

CREATES: dict[str, tuple[str, ...]] = {
    "aws_instance": ("RunInstances",),
    "aws_ebs_volume": ("CreateVolume",),
    "aws_ebs_snapshot": ("CreateSnapshot", "CopySnapshot"),
    "aws_security_group": ("CreateSecurityGroup",),
    "aws_route_table": ("CreateRouteTable",),
    "aws_route": ("CreateRoute",),
    "aws_lb": ("CreateLoadBalancer",),
}
DELETES: dict[str, tuple[str, ...]] = {
    "aws_instance": ("TerminateInstances",),
    "aws_ebs_volume": ("DeleteVolume",),
    "aws_ebs_snapshot": ("DeleteSnapshot",),
    "aws_security_group": ("DeleteSecurityGroup",),
    "aws_route_table": ("DeleteRouteTable",),
    "aws_route": ("DeleteRoute",),
    "aws_lb": ("DeleteLoadBalancer",),
}
CHANGES: dict[tuple[str, str], tuple[str, ...]] = {
    ("aws_instance", "instance_type"): ("ModifyInstanceAttribute",),
    ("aws_instance", "ami"): (),
    ("aws_instance", "tags"): ("CreateTags", "DeleteTags"),
    ("aws_security_group", "ingress"): ("AuthorizeSecurityGroupIngress", "RevokeSecurityGroupIngress",
                                        "ModifySecurityGroupRules"),
    ("aws_security_group", "egress"): ("AuthorizeSecurityGroupEgress", "RevokeSecurityGroupEgress",
                                       "ModifySecurityGroupRules"),
    ("aws_route", "target"): ("ReplaceRoute",),
    ("aws_ebs_volume", "size"): ("ModifyVolume",),
    ("aws_ebs_volume", "type"): ("ModifyVolume",),
    ("aws_ebs_volume", "attachment"): ("AttachVolume", "DetachVolume"),
    ("aws_lb", "scheme"): (),
    ("aws_lb", "type"): (),
}


def explaining_events(finding: Finding) -> tuple[str, ...]:
    """The event names that would explain a finding of this kind on this type, most specific first."""
    kind, type_ = finding.kind, finding.resource_type
    if kind == "unmanaged":
        return CREATES.get(type_, ())
    if kind == "missing":
        return DELETES.get(type_, ())
    if kind == "changed":
        names: list[str] = []
        for attribute in finding.evidence.get("attributes", {}):
            names.extend(n for n in CHANGES.get((type_, attribute), ()) if n not in names)
        return tuple(names)
    if kind == "untagged":
        return ("CreateTags", "DeleteTags", *CREATES.get(type_, ()))
    if kind == "unattached_volume":
        return ("DetachVolume", "CreateVolume")
    if kind == "old_snapshot":
        return CREATES["aws_ebs_snapshot"]
    if kind == "graviton_candidate":
        return ("RunInstances", "ModifyInstanceAttribute")
    return ()  # idle: no event explains a quiet instance


def lookup_ids(finding: Finding) -> list[str]:
    """What to ask the trail for by ResourceName: the route table for a route, the resource otherwise."""
    if finding.resource_type == "aws_route":
        return [finding.evidence["route_table_id"]]
    return [finding.resource_id]


def _record(event: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(event.get("CloudTrailEvent") or "{}")
    except json.JSONDecodeError:
        return {}


def _explains(finding: Finding, names: tuple[str, ...], event: dict[str, Any], record: dict[str, Any]) -> bool:
    if event.get("EventName") not in names or str(event.get("ReadOnly", "false")) == "true":
        return False
    if finding.resource_type == "aws_route":  # the table's events; the route is told by its destination
        request = record.get("requestParameters") or {}
        destination = request.get("destinationCidrBlock") or request.get("destinationIpv6CidrBlock")
        return destination == finding.evidence.get("destination")
    return True


def _mentions(record: dict[str, Any], ids: list[str]) -> bool:
    text = json.dumps(record.get("requestParameters") or {})
    return any(rid in text for rid in ids)


def _attribution(event: dict[str, Any], record: dict[str, Any], lookup: dict[str, str]) -> dict[str, Any]:
    identity = record.get("userIdentity") or {}
    return {
        "event_name": event.get("EventName"),
        "event_id": event.get("EventId"),
        "event_time": event.get("EventTime"),
        "username": event.get("Username") or identity.get("userName"),
        "principal_arn": identity.get("arn"),
        "identity_type": identity.get("type"),
        "source_ip": record.get("sourceIPAddress"),
        "user_agent": record.get("userAgent"),  # the client's own string: data, read by nothing (W5-D12)
        "lookup": lookup,
    }


def attribute(finding: Finding, lookup: Callable[..., dict[str, Any]], days: int = LOOKUP_DAYS) -> Finding:
    """The finding with its `attribution` set from the latest explaining event, or None when no event
    within the window explains it. `lookup` has the cloud reader's lookup_events signature:
    (account, region, attribute_key, attribute_value, days) -> EventPage."""
    names = explaining_events(finding)
    if not names:
        return replace(finding, attribution=None)
    ids = lookup_ids(finding)
    candidates: list[tuple[dict[str, Any], dict[str, Any], dict[str, str]]] = []
    for rid in ids:
        page = lookup(account=finding.account, region=finding.region, attribute_key="ResourceName",
                      attribute_value=rid, days=days)
        for event in page["response"].get("Events", []):
            record = _record(event)
            if _explains(finding, names, event, record):
                candidates.append((event, record, dict(page["lookup"])))
        if candidates:
            break
    if not candidates:  # an event CloudTrail did not index by the resource: by its name, then by what it names
        for name in names:
            page = lookup(account=finding.account, region=finding.region, attribute_key="EventName",
                          attribute_value=name, days=days)
            for event in page["response"].get("Events", []):
                record = _record(event)
                if _explains(finding, names, event, record) and _mentions(record, ids):
                    candidates.append((event, record, dict(page["lookup"])))
    if not candidates:
        return replace(finding, attribution=None)
    event, record, used = max(candidates, key=lambda c: (c[0].get("EventTime") or "", c[0].get("EventId") or ""))
    return replace(finding, attribution=_attribution(event, record, used))


def attribute_all(findings: list[Finding], lookup: Callable[..., dict[str, Any]], days: int = LOOKUP_DAYS) -> list[Finding]:
    return [attribute(finding, lookup, days) for finding in findings]
