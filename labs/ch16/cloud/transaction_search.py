"""Transaction Search, on and off, in a step of its own (step 7, item 2; fact sheet 8.2; O-D3, amended).

Transaction Search is an account-wide setting: it moves every span X-Ray ingests into CloudWatch Logs, into the
`aws/spans` group, and indexes a share of them as trace summaries. AWS's page turns it on in three calls, and
this module makes the same three: a resource policy that lets X-Ray write to the two log groups, the trace
segment destination set to CloudWatchLogs, and the Default indexing rule read and, when it isn't the documented
1 percent, set to it. `off` reverses them: the destination back to XRay, the policy deleted, the two groups
deleted, and the indexing rule set back to what it was. Both record what AWS answered and when, and `status`
reads the four settings leftovers.py checks.

Run (from labs/ch16, with the session's environment):
    python cloud/transaction_search.py status|on|off --out results/<date>/cloud
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import cloud_session  # noqa: E402

POLICY_NAME = "TransactionSearchAccess"
SPANS_GROUP = "aws/spans"
SIGNALS_GROUP = "/aws/application-signals/data"
DEFAULT_PERCENT = 1.0
# What AWS says it costs while on, for the summary (fact sheet 8.2 and 8.8, read 2026-11-03).
PRICES = {
    "ingestion": {"quote": "$0.35 per GB of Application Signals data ingested for the first 10TB - US East (Ohio)",
                  "source": "fact sheet 8.8, AmazonCloudWatch offer file for us-east-2", "date": "2026-11-03"},
    "indexing": {"quote": "$0.00000075 per spans indexed for USE2-XRay-Spans-Indexed in US East (Ohio)",
                 "free_share": "By default you will also index 1% of ingested spans for free as trace summary",
                 "source": "fact sheet 8.8 and 8.2", "date": "2026-11-03"},
}


def policy_document(account_id: str, region: str) -> dict[str, Any]:
    """The resource policy of AWS's page, for the two groups Transaction Search writes."""
    return {"Version": "2012-10-17", "Statement": [{
        "Sid": "TransactionSearchXRayAccess", "Effect": "Allow",
        "Principal": {"Service": "xray.amazonaws.com"}, "Action": "logs:PutLogEvents",
        "Resource": [f"arn:aws:logs:{region}:{account_id}:log-group:{SPANS_GROUP}:*",
                     f"arn:aws:logs:{region}:{account_id}:log-group:{SIGNALS_GROUP}:*"],
        "Condition": {"ArnLike": {"aws:SourceArn": f"arn:aws:xray:{region}:{account_id}:*"},
                      "StringEquals": {"aws:SourceAccount": account_id}}}]}


def indexing_percent(rules: list[dict[str, Any]]) -> float | None:
    for rule in rules:
        if rule.get("Name") == "Default":
            return (rule.get("Rule") or {}).get("Probabilistic", {}).get("DesiredSamplingPercentage")
    return None


def status(s: Any) -> dict[str, Any]:
    """The four settings: the destination, the indexing rule, the resource policy, and the two groups."""
    xray, logs = s.client("xray"), s.client("logs")
    destination = xray.get_trace_segment_destination()
    rules = xray.get_indexing_rules().get("IndexingRules", [])
    policies = [p["policyName"] for p in logs.describe_resource_policies().get("resourcePolicies", [])]
    groups = {}
    for name in (SPANS_GROUP, SIGNALS_GROUP):
        found = [g for g in logs.describe_log_groups(logGroupNamePrefix=name).get("logGroups", [])
                 if g["logGroupName"] == name]
        groups[name] = {"exists": bool(found), "stored_bytes": found[0].get("storedBytes") if found else None}
    return {"at": cloud_session.utc(), "destination": destination.get("Destination"),
            "destination_status": destination.get("Status"), "indexing_percent": indexing_percent(rules),
            "indexing_rules": [{"name": r.get("Name"), "rule": r.get("Rule")} for r in rules],
            "resource_policy_present": POLICY_NAME in policies, "resource_policies": policies, "log_groups": groups}


POLL_EVERY = 5.0  # seconds between readings of the destination's status; the tests set it to 0


def wait_for_destination(xray: Any, wanted: str, clock: cloud_session.Clock, limit: float = 180.0,
                         every: float | None = None) -> dict[str, Any]:
    """Until the destination reads `wanted` and ACTIVE, or the limit; each reading is kept."""
    every = POLL_EVERY if every is None else every
    readings = []
    while True:
        answer = xray.get_trace_segment_destination()
        readings.append({"seconds": clock.seconds(), "destination": answer.get("Destination"),
                         "status": answer.get("Status")})
        if answer.get("Destination") == wanted and answer.get("Status") == "ACTIVE":
            return {"reached": True, "seconds": clock.seconds(), "readings": readings}
        if clock.seconds() > limit:
            return {"reached": False, "seconds": clock.seconds(), "readings": readings}
        time.sleep(every)


def on(s: Any) -> dict[str, Any]:
    xray, logs, sts = s.client("xray"), s.client("logs"), s.client("sts")
    account_id, region = sts.get_caller_identity()["Account"], s.region_name
    record: dict[str, Any] = {"before": status(s), "clock": cloud_session.CLOCK}
    clock = cloud_session.Clock()
    record["started"] = clock.started
    import json

    logs.put_resource_policy(policyName=POLICY_NAME, policyDocument=json.dumps(policy_document(account_id, region)))
    record["resource_policy"] = {"put": True, "name": POLICY_NAME, "seconds": clock.seconds()}
    try:
        answer = xray.update_trace_segment_destination(Destination="CloudWatchLogs")
        record["update_destination"] = {"destination": answer.get("Destination"), "status": answer.get("Status"),
                                        "seconds": clock.seconds()}
    except Exception as exc:  # the account's answer is the finding
        record["update_destination"] = cloud_session.aws_error(exc) | {"seconds": clock.seconds()}
        record["after"] = status(s)
        return record
    record["active"] = wait_for_destination(xray, "CloudWatchLogs", clock)
    percent = indexing_percent(xray.get_indexing_rules().get("IndexingRules", []))
    record["indexing_percent_after_switch"] = percent
    if percent != DEFAULT_PERCENT:
        answer = xray.update_indexing_rule(Name="Default", Rule={"Probabilistic": {"DesiredSamplingPercentage": DEFAULT_PERCENT}})
        record["update_indexing_rule"] = {"set_to": DEFAULT_PERCENT, "answer": answer.get("IndexingRule"),
                                          "seconds": clock.seconds()}
    record["after"] = status(s)
    record["ended_seconds"] = clock.seconds()
    return record


def off(s: Any, restore_percent: float | None) -> dict[str, Any]:
    xray, logs = s.client("xray"), s.client("logs")
    record: dict[str, Any] = {"before": status(s), "clock": cloud_session.CLOCK}
    clock = cloud_session.Clock()
    record["started"] = clock.started
    try:
        answer = xray.update_trace_segment_destination(Destination="XRay")
        record["update_destination"] = {"destination": answer.get("Destination"), "status": answer.get("Status"),
                                        "seconds": clock.seconds()}
    except Exception as exc:
        record["update_destination"] = cloud_session.aws_error(exc) | {"seconds": clock.seconds()}
    record["xray_again"] = wait_for_destination(xray, "XRay", clock)
    try:
        logs.delete_resource_policy(policyName=POLICY_NAME)
        record["resource_policy"] = {"deleted": True, "seconds": clock.seconds()}
    except Exception as exc:
        record["resource_policy"] = cloud_session.aws_error(exc)
    record["log_groups"] = {}
    for name in (SPANS_GROUP, SIGNALS_GROUP):
        try:
            logs.delete_log_group(logGroupName=name)
            record["log_groups"][name] = {"deleted": True, "seconds": clock.seconds()}
        except logs.exceptions.ResourceNotFoundException:
            record["log_groups"][name] = {"deleted": False, "why": "no such group"}
        except Exception as exc:
            record["log_groups"][name] = cloud_session.aws_error(exc)
    current = indexing_percent(xray.get_indexing_rules().get("IndexingRules", []))
    if restore_percent is not None and current != restore_percent:
        try:
            answer = xray.update_indexing_rule(Name="Default", Rule={"Probabilistic": {"DesiredSamplingPercentage": restore_percent}})
            record["update_indexing_rule"] = {"set_to": restore_percent, "answer": answer.get("IndexingRule"),
                                              "seconds": clock.seconds()}
        except Exception as exc:
            record["update_indexing_rule"] = cloud_session.aws_error(exc)
    record["after"] = status(s)
    record["ended_seconds"] = clock.seconds()
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("action", choices=("status", "on", "off"))
    parser.add_argument("--out", type=Path, default=cloud_session.results_dir())
    args = parser.parse_args(argv)
    cloud_session.require_environment()
    s = cloud_session.session()
    path = args.out / "transaction-search.json"
    if args.action == "status":
        record = status(s)
        cloud_session.merge_json(path, f"status_{record['at'][:19].replace(':', '')}", record)
    elif args.action == "on":
        record = on(s)
        record["prices_while_on"] = PRICES
        cloud_session.merge_json(path, "on", record)
    else:
        before = cloud_session.read_json(path).get("on", {}).get("before", {}) if path.exists() else {}
        record = off(s, before.get("indexing_percent"))
        cloud_session.merge_json(path, "off", record)
    print(f"transaction search {args.action}: destination {record.get('after', record).get('destination')}, "
          f"status {record.get('after', record).get('destination_status')}, "
          f"indexing {record.get('after', record).get('indexing_percent')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
