"""Validate and plan W3 write identities without a request to AWS (W2-D1).

Copies aws/, catalog/, and manifest/ into a work folder, adds an override file that gives the provider
placeholder credentials and the skip flags, then runs `terraform init -backend=false` from a plugin
directory, `terraform validate`, and `terraform plan -refresh=false` with a placeholder account
number. Writes the plan's text and a summary of the resources to aws/results/<date>/ (or --out).

  python aws/plan_offline.py [--plugin-dir DIR] [--out aws/results/2026-11-10]

The plugin directory defaults to TF_PLUGIN_CACHE_DIR, whose layout is a filesystem mirror's, so a
cache that holds hashicorp/aws 6.71.0 serves init offline; without one, init asks the registry.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
W3 = HERE.parent
ACCOUNT = "111122223333"  # a placeholder account number; the plan never reaches AWS

OVERRIDE = """provider "aws" {
  access_key                  = "AKIAIOSFODNN7EXAMPLE"
  secret_key                  = "placeholder-secret-for-an-offline-plan"
  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
}
"""


def terraform(work: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "TF_IN_AUTOMATION": "1", "AWS_SHARED_CREDENTIALS_FILE": str(work / "none"),
           "AWS_CONFIG_FILE": str(work / "none"), "AWS_PROFILE": ""}
    env.pop("AWS_ACCESS_KEY_ID", None)
    env.pop("AWS_SECRET_ACCESS_KEY", None)
    if any(a.startswith("-plugin-dir=") for a in args):
        env.pop("TF_PLUGIN_CACHE_DIR", None)  # init refuses to copy a plugin directory onto itself
    return subprocess.run(["terraform", *args], cwd=work, capture_output=True, text=True, timeout=900, env=env)


def plan(work: Path, plugin_dir: Path | None) -> dict:
    """Validate and plan in `work`; returns the summary (and raises with terraform's output on failure)."""
    for folder in ("aws", "catalog", "manifest"):
        shutil.copytree(W3 / folder, work / folder, ignore=shutil.ignore_patterns("results", "__pycache__", ".terraform*"))
    aws = work / "aws"
    (aws / "offline_override.tf").write_text(OVERRIDE, encoding="utf-8")
    init_args = ["init", "-backend=false", "-input=false", "-no-color"]
    if plugin_dir:
        init_args.append(f"-plugin-dir={plugin_dir}")
    for step in (init_args, ["validate", "-no-color"],
                 ["plan", "-refresh=false", "-input=false", "-no-color", f"-var=account_id={ACCOUNT}", "-out=plan.out"]):
        result = terraform(aws, *step)
        if result.returncode != 0:
            raise RuntimeError(f"terraform {step[0]} failed:\n{result.stdout}\n{result.stderr}")
        if step[0] == "plan":
            plan_text = result.stdout
    shown = terraform(aws, "show", "-json", "plan.out")
    if shown.returncode != 0:
        raise RuntimeError(f"terraform show failed:\n{shown.stderr}")
    data = json.loads(shown.stdout)
    changes = data.get("resource_changes", [])
    by_type: dict[str, int] = {}
    for change in changes:
        if "create" in change["change"]["actions"]:
            by_type[change["type"]] = by_type.get(change["type"], 0) + 1
    policies = {}
    for change in changes:
        if change["type"] == "aws_iam_policy":
            doc = json.loads(change["change"]["after"]["policy"])
            policies[change["address"]] = doc["Statement"]
    return {"measured": time.strftime("%Y-%m-%d"), "account_id": ACCOUNT, "resources_to_add": sum(by_type.values()),
            "by_type": dict(sorted(by_type.items())), "policies": policies, "plan_text": plan_text}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    cache = os.environ.get("TF_PLUGIN_CACHE_DIR")
    parser.add_argument("--plugin-dir", type=Path, default=Path(cache) if cache else None)
    parser.add_argument("--out", type=Path, default=HERE / "results" / time.strftime("%Y-%m-%d"))
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="w3-aws-plan-") as tmp:
        summary = plan(Path(tmp), args.plugin_dir)
    args.out.mkdir(parents=True, exist_ok=True)
    text = summary.pop("plan_text")
    header = (f"# terraform plan -refresh=false with placeholder credentials and account {ACCOUNT} ({summary['measured']})\n"
              "# No request reached AWS: skip_credentials_validation, skip_requesting_account_id and no refresh.\n")
    (args.out / "terraform-plan.txt").write_text(header + text, encoding="utf-8", newline="\n")
    (args.out / "plan-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"{summary['resources_to_add']} resources to add; written to {args.out}")
    for kind, count in summary["by_type"].items():
        print(f"  {count:2d}  {kind}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
