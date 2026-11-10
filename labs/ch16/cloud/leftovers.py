"""What step 7's session left in the account: read-only, by the session's tags and names, one line per kind.

Chapter 6's sandbox/leftovers.py checks chapter 6's kinds; this one checks step 7's, after `terraform destroy`:
the network tagged purpose=ch16-cloud-session and whatever still sits in it, instances and volumes with the tag,
Elastic IPs, Instance Connect endpoints, the two IAM roles and their inline policies, the log groups, Bedrock's
invocation logging, Transaction Search's four settings (the destination, the indexing rule, the resource policy,
the span groups), budgets and SNS topics named ch16-cloud. The author's read-only sweep, kept outside this
repository, runs after it for everything that bills. Prints no account ID, key, or address.

  python cloud/leftovers.py [--region us-east-2] [--json results/<date>/cloud/leftovers.json]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import cloud_session  # noqa: E402

PURPOSE = "ch16-cloud-session"
NAME = "ch16-cloud"
ROLES = ("w3-incident-get-pod-status", f"{NAME}-invocation-logging")
LOG_GROUPS = ("/aws/bedrock/model-invocations-ch16", "aws/spans", "/aws/application-signals/data")


def ask(call: Callable[[], Any]) -> Any:
    try:
        return call()
    except Exception as exc:  # a refusal is worth reporting, not a crash
        return f"{type(exc).__name__}: {cloud_session.redact_text(str(exc))[:120]}"


def sweep(s: Any) -> dict[str, Any]:
    ec2, iam, logs, xray = s.client("ec2"), s.client("iam"), s.client("logs"), s.client("xray")
    tagged = [{"Name": "tag:purpose", "Values": [PURPOSE]}]
    found: dict[str, Any] = {}
    found["instances_not_terminated"] = ask(lambda: [i["State"]["Name"] for r in ec2.describe_instances(
        Filters=tagged + [{"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped", "shutting-down"]}])["Reservations"]
        for i in r["Instances"]])
    found["volumes"] = ask(lambda: len(ec2.describe_volumes(Filters=tagged)["Volumes"]))
    found["elastic_ips_allocated"] = ask(lambda: len(ec2.describe_addresses()["Addresses"]))  # the VM's own address is not one
    vpcs = ask(lambda: ec2.describe_vpcs(Filters=tagged)["Vpcs"])
    vpc_ids = [v["VpcId"] for v in vpcs] if isinstance(vpcs, list) else []
    found["vpcs"] = len(vpc_ids) if isinstance(vpcs, list) else vpcs
    if vpc_ids:
        flt = [{"Name": "vpc-id", "Values": vpc_ids}]
        found["subnets"] = len(ec2.describe_subnets(Filters=flt)["Subnets"])
        found["security_groups"] = sorted(g["GroupName"] for g in ec2.describe_security_groups(Filters=flt)["SecurityGroups"]
                                          if g["GroupName"] != "default")
        found["internet_gateways"] = len(ec2.describe_internet_gateways(Filters=[{"Name": "attachment.vpc-id", "Values": vpc_ids}])["InternetGateways"])
        found["network_interfaces"] = sorted({e.get("InterfaceType", "") + ":" + e.get("Description", "")[:40]
                                              for e in ec2.describe_network_interfaces(Filters=flt)["NetworkInterfaces"]})
    found["instance_connect_endpoints"] = ask(lambda: [e["State"] for e in ec2.describe_instance_connect_endpoints()["InstanceConnectEndpoints"]])
    roles = {}
    for name in ROLES:
        try:
            iam.get_role(RoleName=name)
            roles[name] = {"exists": True, "inline_policies": ask(lambda name=name: iam.list_role_policies(RoleName=name)["PolicyNames"])}
        except iam.exceptions.NoSuchEntityException:
            roles[name] = {"exists": False}
        except Exception as exc:
            roles[name] = f"{type(exc).__name__}"
    found["iam_roles"] = roles
    groups = ask(lambda: {g["logGroupName"]: g.get("storedBytes") for g in logs.describe_log_groups()["logGroups"]})
    found["log_groups"] = {name: groups.get(name, "absent") for name in LOG_GROUPS} if isinstance(groups, dict) else groups
    found["other_log_groups"] = sorted(set(groups) - set(LOG_GROUPS)) if isinstance(groups, dict) else groups
    found["invocation_logging"] = ask(lambda: bool(s.client("bedrock").get_model_invocation_logging_configuration().get("loggingConfig")))
    destination = ask(lambda: xray.get_trace_segment_destination())
    found["xray_destination"] = {k: destination.get(k) for k in ("Destination", "Status")} if isinstance(destination, dict) else destination
    found["xray_indexing_percent"] = ask(lambda: [(r.get("Name"), (r.get("Rule") or {}).get("Probabilistic", {}).get("DesiredSamplingPercentage"))
                                                  for r in xray.get_indexing_rules().get("IndexingRules", [])])
    found["logs_resource_policies"] = ask(lambda: [p["policyName"] for p in logs.describe_resource_policies().get("resourcePolicies", [])])
    found["budgets"] = ask(lambda: [b["BudgetName"] for b in s.client("budgets", region_name="us-east-1").describe_budgets(
        AccountId=s.client("sts").get_caller_identity()["Account"]).get("Budgets", []) if b["BudgetName"].startswith(NAME)])
    found["sns_topics"] = ask(lambda: [t["TopicArn"].rsplit(":", 1)[1] for t in s.client("sns").list_topics()["Topics"]
                                       if t["TopicArn"].rsplit(":", 1)[1].startswith(NAME)])
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--region", default=cloud_session.REGION)
    parser.add_argument("--json", type=Path, help="also write the findings here, redacted")
    args = parser.parse_args(argv)
    cloud_session.require_environment()
    found = sweep(cloud_session.session(args.region))
    for kind, value in found.items():
        print(f"{kind}: {cloud_session.redact_text(str(value))}")
    if args.json:
        cloud_session.write_json(args.json, {"at": cloud_session.utc(), "region": args.region, **found})
    return 0


if __name__ == "__main__":
    sys.exit(main())
