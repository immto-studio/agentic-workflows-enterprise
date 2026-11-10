"""The identity half of the kill switch: a deny-all policy on a workflow's harness role and tool roles.

Chapter 16, step 4 (companion #14, O-D7), for step 7 to time on real credentials. Chapter 6 gives the
switch its AWS form: "a policy that denies everything to the harness's role and to every tool role of the
workflow" (ch06:298). `pull` puts one inline policy, `larkspur-kill-switch`, on each of those roles, with two
statements:

- `KillSwitchDenyAll` denies every action on every resource, with no condition. IAM evaluates a role's
  policies on every request, so it refuses the sessions already issued and any issued later.
- `KillSwitchRevokeIssued` denies every action to a session whose `aws:TokenIssueTime` is before the pull plus
  30 seconds, the shape of AWS's own revoke (`AWSRevokeOlderSessions`, "approximately 30 seconds into the
  future", fact sheet 8.3). Under the first statement it adds nothing; it is the documented way to cut off
  credentials already issued, and it is the statement a release keeps.

`release` takes the deny-all away and leaves the revoke statement with its cut-off moved to the moment of the
release, so a credential issued before the release, during the incident included, never works again, and a
session issued after it works. Once the longest session issued before the release has expired (chapter 6's
harness role allows an hour), `release --purge` removes the policy; until then it denies nothing new.

The roles are chapter 6's: `<workflow>-harness`, and `<workflow>-<tool>` for each tool in the manifest
(`labs/ch06/terraform`, `modules/manifest_roles`). Before it writes, the script reads each role and refuses
one whose `workflow` tag names another workflow, so a typo can't switch off someone else's identity. A role
that doesn't exist is reported and skipped.

Run (step 7, with the session's credentials):
    python budget/identity.py pull --manifest ../ch05/manifest/w3-incident.yaml
    python budget/identity.py release --manifest ../ch05/manifest/w3-incident.yaml [--purge]
    python budget/identity.py pull --manifest ... --dry-run     # the roles and the document; no AWS call
This step runs only --dry-run and the tests, which use botocore's Stubber and make no AWS call.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

POLICY_NAME = "larkspur-kill-switch"
REVOKE_MARGIN = timedelta(seconds=30)
ROLE_NAME_MAX = 64


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def role_names(manifest: Mapping[str, Any]) -> list[str]:
    """Chapter 6's role names for the workflow: the harness's, then one per tool, as the module names them."""
    workflow = manifest["workflow"]
    tools = [f"{workflow}-{tool.replace('_', '-')}"[:ROLE_NAME_MAX] for tool in manifest["tools"]]
    return [f"{workflow}-harness", *tools]


def revoke_statement(cutoff: datetime) -> dict[str, Any]:
    return {"Sid": "KillSwitchRevokeIssued", "Effect": "Deny", "Action": "*", "Resource": "*",
            "Condition": {"DateLessThan": {"aws:TokenIssueTime": iso(cutoff)}}}


def pull_document(pulled_at: datetime) -> dict[str, Any]:
    return {"Version": "2012-10-17", "Statement": [
        {"Sid": "KillSwitchDenyAll", "Effect": "Deny", "Action": "*", "Resource": "*"},
        revoke_statement(pulled_at + REVOKE_MARGIN)]}


def release_document(released_at: datetime) -> dict[str, Any]:
    return {"Version": "2012-10-17", "Statement": [revoke_statement(released_at)]}


@dataclass(frozen=True)
class Result:
    role: str
    action: str           # put, deleted, skipped, absent
    why: str = ""
    at: str = ""          # when IAM answered, for step 7's timing


def _now() -> datetime:
    return datetime.now(timezone.utc)


def check_role(iam: Any, name: str, workflow: str) -> str | None:
    """Why the script must not touch this role, or None."""
    try:
        role = iam.get_role(RoleName=name)["Role"]
    except iam.exceptions.NoSuchEntityException:
        return "no such role"
    tags = {t["Key"]: t["Value"] for t in role.get("Tags") or []}
    if tags.get("workflow") != workflow:
        return f"its workflow tag is {tags.get('workflow')!r}, not {workflow!r}"
    return None


def pull(iam: Any, roles: list[str], workflow: str, now: datetime | None = None) -> list[Result]:
    now = now or _now()
    document = json.dumps(pull_document(now))
    results = []
    for name in roles:
        problem = check_role(iam, name, workflow)
        if problem:
            results.append(Result(name, "skipped", problem))
            continue
        iam.put_role_policy(RoleName=name, PolicyName=POLICY_NAME, PolicyDocument=document)
        results.append(Result(name, "put", "deny-all and revoke", iso(_now())))
    return results


def release(iam: Any, roles: list[str], workflow: str, now: datetime | None = None,
            purge: bool = False) -> list[Result]:
    now = now or _now()
    document = json.dumps(release_document(now))
    results = []
    for name in roles:
        problem = check_role(iam, name, workflow)
        if problem:
            results.append(Result(name, "skipped", problem))
            continue
        if purge:
            try:
                iam.delete_role_policy(RoleName=name, PolicyName=POLICY_NAME)
            except iam.exceptions.NoSuchEntityException:
                results.append(Result(name, "absent", "no kill-switch policy to remove"))
                continue
            results.append(Result(name, "deleted", "policy removed", iso(_now())))
        else:
            iam.put_role_policy(RoleName=name, PolicyName=POLICY_NAME, PolicyDocument=document)
            results.append(Result(name, "put", f"revoke only, sessions issued before {iso(now)}", iso(_now())))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("action", choices=("pull", "release"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--role", action="append", default=None,
                        help="a role name to use instead of chapter 6's names; repeat for several")
    parser.add_argument("--purge", action="store_true", help="release: remove the policy, revoke statement too")
    parser.add_argument("--dry-run", action="store_true", help="print the roles and the document; call nothing")
    parser.add_argument("--profile", default=None)
    args = parser.parse_args(argv)
    manifest = yaml.safe_load(args.manifest.read_text(encoding="utf-8"))
    workflow, roles = manifest["workflow"], args.role or role_names(manifest)
    now = _now()
    if args.dry_run:
        document = (pull_document(now) if args.action == "pull"
                    else None if args.purge else release_document(now))
        print(json.dumps({"workflow": workflow, "roles": roles, "policy": POLICY_NAME, "document": document},
                         indent=1))
        return 0
    import boto3

    iam = boto3.Session(profile_name=args.profile).client("iam")
    results = (pull(iam, roles, workflow, now) if args.action == "pull"
               else release(iam, roles, workflow, now, purge=args.purge))
    print(json.dumps({"workflow": workflow, "action": args.action, "requested_at": iso(now),
                      "results": [asdict(r) for r in results]}, indent=1))
    return 0 if all(r.action in ("put", "deleted", "absent") for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
