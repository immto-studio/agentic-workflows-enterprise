"""What a chapter 6 sandbox run left in the account: read-only, by the names and tags the lab and the
sandbox use. Prints one line per kind; no account ID.

  python leftovers.py [--region us-east-2]

KMS keys pending deletion are listed apart: AWS keeps a deleted key for its waiting period.
"""

from __future__ import annotations

import argparse
import re
import sys
from typing import Any, Callable

WORKFLOW = "w3-incident"
SANDBOX = "ch06-sandbox"


def ask(call: Callable[[], Any]) -> Any:
    try:
        return call()
    except Exception as exc:  # a refusal is worth reporting, not a crash
        return f"{type(exc).__name__}: {str(exc)[:120]}"


def main(argv: list[str] | None = None) -> int:
    import boto3

    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--region", default="us-east-2")
    args = parser.parse_args(argv)
    s = boto3.Session(region_name=args.region)
    ec2, eks, iam = s.client("ec2"), s.client("eks"), s.client("iam")
    control, agent, bedrock = s.client("bedrock-agentcore-control"), s.client("bedrock-agent"), s.client("bedrock")
    mine = (WORKFLOW, SANDBOX, WORKFLOW.replace("-", "_"))

    def named(values: list[str]) -> list[str]:
        return sorted(v for v in values if any(v.startswith(p) for p in mine))

    found: dict[str, Any] = {}
    vpcs = ask(lambda: ec2.describe_vpcs(Filters=[{"Name": "tag:purpose", "Values": ["ch06-lab-sandbox"]}])["Vpcs"])
    vpc_ids = [v["VpcId"] for v in vpcs] if isinstance(vpcs, list) else []
    found["vpcs"] = len(vpc_ids) if isinstance(vpcs, list) else vpcs
    if vpc_ids:
        flt = [{"Name": "vpc-id", "Values": vpc_ids}]
        found["subnets"] = len(ec2.describe_subnets(Filters=flt)["Subnets"])
        groups = ec2.describe_security_groups(Filters=flt)["SecurityGroups"]
        found["security_groups"] = sorted(g["GroupName"] for g in groups if g["GroupName"] != "default")
        enis = ec2.describe_network_interfaces(Filters=flt)["NetworkInterfaces"]
        found["network_interfaces"] = sorted({e.get("InterfaceType", "") + ":" + e.get("Description", "")[:40]
                                              for e in enis})
        found["vpc_endpoints"] = len(ec2.describe_vpc_endpoints(Filters=flt)["VpcEndpoints"])
    found["eks_clusters"] = ask(lambda: named(eks.list_clusters()["clusters"]))
    found["agent_runtimes"] = ask(lambda: named([r["agentRuntimeName"] for r in control.list_agent_runtimes()["agentRuntimes"]]))
    found["gateways"] = ask(lambda: named([g["name"] for g in control.list_gateways()["items"]]))
    found["knowledge_bases"] = ask(lambda: named([k["name"] for k in agent.list_knowledge_bases()["knowledgeBaseSummaries"]]))
    found["guardrails"] = ask(lambda: named([g["name"] for g in bedrock.list_guardrails()["guardrails"]]))
    found["invocation_logging"] = ask(lambda: bool(bedrock.get_model_invocation_logging_configuration().get("loggingConfig")))
    found["s3_buckets"] = ask(lambda: named([b["Name"] for b in s.client("s3").list_buckets()["Buckets"]]))
    found["vector_buckets"] = ask(lambda: named([b["vectorBucketName"] for b in s.client("s3vectors").list_vector_buckets()["vectorBuckets"]]))
    found["ecr_repositories"] = ask(lambda: named([r["repositoryName"] for r in s.client("ecr").describe_repositories()["repositories"]]))
    found["codebuild_projects"] = ask(lambda: named(s.client("codebuild").list_projects()["projects"]))
    found["secrets"] = ask(lambda: named([x["Name"] for x in s.client("secretsmanager").list_secrets()["SecretList"]]))
    found["log_groups"] = ask(lambda: sorted(g["logGroupName"] for g in s.client("logs").describe_log_groups()["logGroups"]
                                             if any(m in g["logGroupName"] for m in ("bedrock", "codebuild/ch06"))))
    found["iam_roles"] = ask(lambda: named([r["RoleName"] for p in iam.get_paginator("list_roles").paginate() for r in p["Roles"]]))
    found["iam_policies"] = ask(lambda: named([p["PolicyName"] for page in iam.get_paginator("list_policies").paginate(Scope="Local")
                                               for p in page["Policies"]]))
    found["budgets"] = ask(lambda: named([b["BudgetName"] for b in s.client("budgets", region_name="us-east-1").describe_budgets(
        AccountId=s.client("sts").get_caller_identity()["Account"]).get("Budgets", [])]))
    kms = s.client("kms")
    pending = []
    for key in ask(lambda: kms.list_keys()["Keys"]) or []:
        meta = ask(lambda key=key: kms.describe_key(KeyId=key["KeyId"])["KeyMetadata"])
        if isinstance(meta, dict) and meta.get("KeyManager") == "CUSTOMER" and any(w in meta.get("Description", "") for w in mine):
            pending.append(f"{meta['KeyState']}")
    found["kms_keys"] = pending
    for kind, value in found.items():
        print(f"{kind}: {re.sub(r'[0-9]{12}', '<account>', str(value))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
