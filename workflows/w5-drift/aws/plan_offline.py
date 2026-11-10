"""Validate and plan W5's identities without a request to AWS (W5-D1).

Copies aws/, catalog/, and manifest/ into a work folder, adds an override file that gives the default
provider and each workload account's provider placeholder credentials and the skip flags (and no
assume_role block), then runs `terraform init -backend=false` from a plugin directory, `terraform validate`,
and `terraform plan -refresh=false` with placeholder account numbers for the ops account and the three
workload accounts, a placeholder organization ID, and a placeholder ARN for the state bucket's key. Writes
the plan's text and a summary of the resources, the policies, the trusts, the Pod Identity bindings, and
the outputs the plan knows, the bucket's deny among them, to aws/results/<date>/ (or --out).

  python aws/plan_offline.py [--plugin-dir DIR] [--out aws/results/2026-11-10]

The plugin directory defaults to TF_PLUGIN_CACHE_DIR, whose layout is a filesystem mirror's, so a cache
that holds hashicorp/aws 6.71.0 serves init offline; without one, init asks the registry. The results carry
no path of this machine: the plan names none, and the writer refuses to keep a file that would.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
W5 = HERE.parent
ACCOUNT = "111122223333"  # a placeholder number for the ops account; the plan never reaches AWS
# The workspace map's accounts -> placeholder numbers, the ones the fakes answer with (servers/cloud_fake.py).
WORKLOAD_ACCOUNTS = {
    "lm-network-prod": "411122223333",
    "lm-claims-prod": "422233334444",
    "lm-sandbox": "433344445555",
}
ORGANIZATION_ID = "o-a1b2c3d4e5"  # a placeholder organization ID
STATE_KEY_ARN = f"arn:aws:kms:ca-central-1:{ACCOUNT}:key/1234abcd-12ab-34cd-56ef-1234567890ab"  # a placeholder key
# A drive path (C:\ or C:/, not a URL's "s://"), a home or temporary folder, or Windows' AppData.
LOCAL_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/](?!/)|/(?:home|Users|tmp)/|AppData", re.IGNORECASE)

PROVIDER = """provider "aws" {{{alias}
  access_key                  = "AKIAIOSFODNN7EXAMPLE"
  secret_key                  = "placeholder-secret-for-an-offline-plan"
  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
}}
"""


def alias(account: str) -> str:
    """The provider alias and module name accounts.tf gives an account of the map."""
    return account.replace("-", "_")


def override() -> str:
    """The default provider and one provider per workload account, each with placeholder credentials and the
    skip flags, and none with an assume_role block: a real apply gives each that account's credentials."""
    aliases = [""] + [f'\n  alias                       = "{alias(account)}"' for account in WORKLOAD_ACCOUNTS]
    return "\n".join(PROVIDER.format(alias=a) for a in aliases)


def terraform(work: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "TF_IN_AUTOMATION": "1", "AWS_SHARED_CREDENTIALS_FILE": str(work / "none"),
           "AWS_CONFIG_FILE": str(work / "none"), "AWS_PROFILE": ""}
    env.pop("AWS_ACCESS_KEY_ID", None)
    env.pop("AWS_SECRET_ACCESS_KEY", None)
    env.pop("AWS_SESSION_TOKEN", None)
    if any(a.startswith("-plugin-dir=") for a in args):
        env.pop("TF_PLUGIN_CACHE_DIR", None)  # init refuses to copy a plugin directory onto itself
    return subprocess.run(["terraform", *args], cwd=work, capture_output=True, text=True, timeout=900, env=env)


def plan(work: Path, plugin_dir: Path | None, mutate: Callable[[Path], None] | None = None) -> dict:
    """Validate and plan in `work`; returns the summary (and raises with terraform's output on failure).
    `mutate(work)` runs after the copy, before init: a test edits the copied catalog or map to see the plan
    refuse."""
    for folder in ("aws", "catalog", "manifest"):
        shutil.copytree(W5 / folder, work / folder, ignore=shutil.ignore_patterns("results", "__pycache__", ".terraform*"))
    if mutate:
        mutate(work)
    aws = work / "aws"
    (aws / "offline_override.tf").write_text(override(), encoding="utf-8")
    init_args = ["init", "-backend=false", "-input=false", "-no-color"]
    if plugin_dir:
        init_args.append(f"-plugin-dir={plugin_dir}")
    plan_args = ["plan", "-refresh=false", "-input=false", "-no-color", f"-var=account_id={ACCOUNT}",
                 f"-var=workload_account_ids={json.dumps(WORKLOAD_ACCOUNTS, separators=(',', ':'))}",
                 f"-var=organization_id={ORGANIZATION_ID}", f"-var=state_kms_key_arn={STATE_KEY_ARN}",
                 "-out=plan.out"]
    for step in (init_args, ["validate", "-no-color"], plan_args):
        result = terraform(aws, *step)
        if result.returncode != 0:
            raise RuntimeError(f"terraform {step[0]} failed:\n{result.stdout}\n{result.stderr}")
        if step[0] == "plan":
            plan_text = result.stdout
    shown = terraform(aws, "show", "-json", "plan.out")
    if shown.returncode != 0:
        raise RuntimeError(f"terraform show failed:\n{shown.stderr}")
    return summarize(json.loads(shown.stdout), plan_text)


def summarize(data: dict, plan_text: str) -> dict:
    """What the plan would create, by type and by address, and what each identity would hold: the policies'
    statements, each role's trust, its session length and whether a boundary is set, each Pod Identity
    binding with its target role, and the outputs the plan already knows (the bucket's deny among them)."""
    changes = data.get("resource_changes", [])
    by_type: dict[str, int] = {}
    addresses: list[str] = []
    policies, trusts, roles, bindings = {}, {}, {}, {}
    for change in changes:
        if "create" not in change["change"]["actions"]:
            continue
        by_type[change["type"]] = by_type.get(change["type"], 0) + 1
        addresses.append(change["address"])
        after = change["change"]["after"] or {}
        unknown = change["change"].get("after_unknown") or {}
        if change["type"] == "aws_iam_policy":
            policies[change["address"]] = json.loads(after["policy"])["Statement"]
        elif change["type"] == "aws_iam_role":  # who may assume each role: the trust is the identity's edge
            trusts[change["address"]] = json.loads(after["assume_role_policy"])["Statement"]
            roles[change["address"]] = {"name": after["name"], "max_session_duration": after["max_session_duration"],
                                        "permissions_boundary": "known after apply" if unknown.get("permissions_boundary")
                                        else after.get("permissions_boundary")}
        elif change["type"] == "aws_eks_pod_identity_association":
            bindings[change["address"]] = {"cluster": after["cluster_name"], "namespace": after["namespace"],
                                           "service_account": after["service_account"],
                                           "target_role_arn": after.get("target_role_arn"),
                                           "disable_session_tags": after.get("disable_session_tags")}
    outputs = {name: out["after"] for name, out in data.get("output_changes", {}).items() if out.get("after_unknown") is False}
    if "state_bucket_deny_policy" in outputs:
        outputs["state_bucket_deny_policy"] = json.loads(outputs["state_bucket_deny_policy"])["Statement"]
    return {"measured": time.strftime("%Y-%m-%d"), "account_id": ACCOUNT, "workload_account_ids": WORKLOAD_ACCOUNTS,
            "organization_id": ORGANIZATION_ID, "state_kms_key_arn": STATE_KEY_ARN,
            "resources_to_add": sum(by_type.values()), "by_type": dict(sorted(by_type.items())),
            "addresses": sorted(addresses), "policies": policies, "trusts": trusts, "roles": roles,
            "pod_identity": bindings, "outputs": outputs, "plan_text": plan_text}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    cache = os.environ.get("TF_PLUGIN_CACHE_DIR")
    parser.add_argument("--plugin-dir", type=Path, default=Path(cache) if cache else None)
    parser.add_argument("--out", type=Path, default=HERE / "results" / time.strftime("%Y-%m-%d"))
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="w5-aws-plan-") as tmp:
        summary = plan(Path(tmp), args.plugin_dir)
    text = summary.pop("plan_text")
    header = (f"# terraform plan -refresh=false with placeholder credentials, the ops account {ACCOUNT}, the workload "
              f"accounts {', '.join(WORKLOAD_ACCOUNTS.values())}, a placeholder organization ID, and a placeholder "
              f"key ARN ({summary['measured']})\n"
              "# No request reached AWS: skip_credentials_validation, skip_requesting_account_id and no refresh.\n")
    files = {"terraform-plan.txt": header + text, "plan-summary.json": json.dumps(summary, indent=2) + "\n"}
    for name, content in files.items():
        found = LOCAL_PATH.search(content)
        if found:
            raise RuntimeError(f"{name} would carry a path of this machine near {content[max(found.start() - 40, 0):found.end() + 40]!r}")
    args.out.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (args.out / name).write_text(content, encoding="utf-8", newline="\n")
    print(f"{summary['resources_to_add']} resources to add; written to {args.out}")
    for kind, count in summary["by_type"].items():
        print(f"  {count:2d}  {kind}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
