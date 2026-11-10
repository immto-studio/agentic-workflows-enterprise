"""Chapter 8's sandbox, after `terraform apply` here: write lab.tfvars, build the image in the lab's
registry, read the state of what the lab made.

  python sandbox.py tfvars        ../terraform/lab.tfvars for a run in the sandbox subscription (book
                                  D-037), with the stand-ins' identifiers; the budget's month is this one
  python sandbox.py image         the sandbox root into ../image/private-ca.pem, then an ACR Tasks build
                                  of the harness image for linux/amd64 in the lab's registry (no Docker
                                  here), and the pushed digest into image-uri.txt
  python sandbox.py check --out ../results/<date>/first-apply.json
                                  read-only: both accounts, the project, its connections and
                                  capability hosts, the deployment, the registry, the private
                                  endpoints, the policy assignments, the budget
  python sandbox.py leftovers     what the lab or the sandbox left, by name, soft-deleted accounts
                                  included

Credentials: the ARM_* variables in the environment or in the file --azure-env names (chapter 8's
service principal). Prints statuses only: no secret, no subscription ID.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
LAB = HERE.parent
LABS = LAB.parent
DOCKERFILE = LAB / "image" / "Dockerfile"
IMAGE_URI = HERE / "image-uri.txt"  # git-ignored
TFVARS = LAB / "terraform" / "lab.tfvars"  # git-ignored
ARM = "https://management.azure.com"
GUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def clean(text: str) -> str:
    return GUID.sub("<id>", text)


def env_from(path: str | None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k.startswith("ARM_")}
    if path:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.startswith("ARM_") and "=" in line:
                k, v = line.split("=", 1)
                env.setdefault(k, v.strip())
    missing = [k for k in ("ARM_CLIENT_ID", "ARM_CLIENT_SECRET", "ARM_TENANT_ID", "ARM_SUBSCRIPTION_ID") if k not in env]
    if missing:
        raise SystemExit(f"missing {', '.join(missing)}: set them or give --azure-env")
    return env


def http(method: str, url: str, token: str | None = None, body=None, form: dict | None = None,
         raw: bytes | None = None, content_type: str | None = None, extra: dict | None = None):
    data, headers = None, dict(extra or {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
    if form is not None:
        data, headers["Content-Type"] = urllib.parse.urlencode(form).encode(), "application/x-www-form-urlencoded"
    if raw is not None:
        data = raw
        if content_type:
            headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = response.read()
            return response.status, (json.loads(payload) if payload and response.headers.get_content_type() == "application/json" else payload), dict(response.headers)
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        try:
            return exc.code, json.loads(payload) if payload else {}, dict(exc.headers)
        except Exception:
            return exc.code, payload, dict(exc.headers)


class Arm:
    def __init__(self, env: dict[str, str], scope: str = ARM + "/.default") -> None:
        self.env, self.sub = env, env["ARM_SUBSCRIPTION_ID"]
        status, reply, _ = http("POST", f"https://login.microsoftonline.com/{env['ARM_TENANT_ID']}/oauth2/v2.0/token",
                                form={"grant_type": "client_credentials", "client_id": env["ARM_CLIENT_ID"],
                                      "client_secret": env["ARM_CLIENT_SECRET"], "scope": scope})
        if status != 200:
            raise SystemExit(f"token: HTTP {status}")
        self.token = reply["access_token"]

    def get(self, path: str, api: str):
        status, reply, _ = http("GET", f"{ARM}{path}?api-version={api}", self.token)
        return reply if status == 200 else {"error": status, "code": (reply or {}).get("error", {}).get("code") if isinstance(reply, dict) else None}

    def post(self, path: str, api: str, body=None):
        return http("POST", f"{ARM}{path}?api-version={api}", self.token, body=body)


def outputs(folder: Path) -> dict:
    run = subprocess.run(["terraform", "output", "-json"], cwd=folder, capture_output=True, text=True, check=True)
    return {name: value["value"] for name, value in json.loads(run.stdout).items()}


# --- tfvars --------------------------------------------------------------------------------------

def tfvars(args: argparse.Namespace) -> int:
    env = env_from(args.azure_env)
    lab = outputs(HERE)["lab"]
    first = dt.date.today().replace(day=1)
    values = {
        "subscription_id": env["ARM_SUBSCRIPTION_ID"],
        "name_suffix": "sbx01",
        "monthly_budget": 20,
        "budget_start": f"{first.isoformat()}T00:00:00Z",
        "budget_alert_emails": [args.budget_email],
        "agent_subnet_id": lab["agent_subnet_id"],
        "private_endpoint_subnet_id": lab["private_endpoint_subnet_id"],
        "private_dns_zone_ids": lab["private_dns_zone_ids"],
        "registry_dns_zone_id": lab["registry_dns_zone_id"],
        "gateway_principal_id": lab["gateway_principal_id"],
    }
    lines = ["# Written by sandbox/sandbox.py for a sandbox run (book D-037). Git-ignored."]
    lines += [f"{name} = {json.dumps(value)}" for name, value in values.items()]
    TFVARS.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"lab.tfvars: {len(values)} values, budget month {first.isoformat()}")
    return 0


# --- the image, built by ACR Tasks ---------------------------------------------------------------

def context_files() -> list[Path]:
    """The Dockerfile and every source its COPY instructions name, relative to labs/."""
    text = DOCKERFILE.read_text(encoding="utf-8").replace("\\\n", " ")
    files = [DOCKERFILE.relative_to(LABS)]
    for line in text.splitlines():
        words = line.split()
        if words and words[0] == "COPY":
            files += [Path(word) for word in words[1:-1] if not word.startswith("--")]
    return files


def image(args: argparse.Namespace) -> int:
    env = env_from(args.azure_env)
    arm = Arm(env)
    root_pem = outputs(HERE)["root_ca_pem"]
    (LAB / "image" / "private-ca.pem").write_text(root_pem, encoding="utf-8")
    registry_id = None
    lab_out = outputs(LAB / "terraform")
    registry_id = lab_out.get("registry_id")
    if not registry_id:
        raise SystemExit("the lab has no registry_id output yet; apply the lab first")
    registry_name = registry_id.rsplit("/", 1)[-1]

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for relative in context_files():
            path = LABS / relative
            if not path.is_file():
                raise SystemExit(f"the build context lacks {relative.as_posix()}")
            archive.add(path, relative.as_posix())
    print(f"context: {len(context_files())} files, {len(buffer.getvalue()) // 1024} KB")

    # ACR Tasks: an upload URL for the context, then a quick build for linux/amd64.
    status, upload, _ = arm.post(f"{registry_id}/listBuildSourceUploadUrl", "2019-06-01-preview")
    if status != 200:
        print("listBuildSourceUploadUrl: HTTP", status, clean(json.dumps(upload))[:300])
        return 1
    status, _, _ = http("PUT", upload["uploadUrl"], raw=buffer.getvalue(),
                        content_type="application/octet-stream", extra={"x-ms-blob-type": "BlockBlob"})
    if status not in (200, 201):
        print("context upload: HTTP", status)
        return 1
    tag = f"build-{int(time.time())}"
    run_request = {
        "type": "DockerBuildRequest",
        "imageNames": [f"harness:{tag}"],
        "isPushEnabled": True,
        "sourceLocation": upload["relativePath"],
        "dockerFilePath": "ch08/image/Dockerfile",
        "platform": {"os": "Linux", "architecture": "amd64"},
        "agentConfiguration": {"cpu": 2},
        "timeout": 1800,
    }
    status, run, _ = arm.post(f"{registry_id}/scheduleRun", "2019-06-01-preview", run_request)
    if status not in (200, 201, 202):
        print("scheduleRun: HTTP", status, clean(json.dumps(run))[:400])
        return 1
    run_id = run["name"]
    state = run["properties"].get("status")
    while state in ("Queued", "Started", "Running"):
        time.sleep(15)
        state = arm.get(f"{registry_id}/runs/{run_id}", "2019-06-01-preview").get("properties", {}).get("status")
        print("run:", state)
    if state != "Succeeded":
        status, log, _ = arm.post(f"{registry_id}/runs/{run_id}/listLogSasUrl", "2019-06-01-preview")
        if status == 200:
            _, text, _ = http("GET", log["logLink"])
            tail = text.decode("utf-8", "replace") if isinstance(text, bytes) else str(text)
            print(clean(tail)[-2500:])
        return 1
    # The digest, from the registry's data plane with an ACR refresh token for the service principal.
    status, exchange, _ = http("POST", f"https://{registry_name}.azurecr.io/oauth2/exchange",
                               form={"grant_type": "access_token", "service": f"{registry_name}.azurecr.io",
                                     "access_token": arm.token})
    if status != 200:
        print("registry exchange: HTTP", status, "(the registry is private; the digest is read from the run instead)")
        detail = arm.get(f"{registry_id}/runs/{run_id}", "2019-06-01-preview")
        digests = [o.get("digest") for o in detail.get("properties", {}).get("outputImages", []) if o.get("digest")]
        if not digests:
            return 1
        digest = digests[0]
    else:
        status, token, _ = http("POST", f"https://{registry_name}.azurecr.io/oauth2/token",
                                form={"grant_type": "refresh_token", "service": f"{registry_name}.azurecr.io",
                                      "scope": "repository:harness:pull", "refresh_token": exchange["refresh_token"]})
        request = urllib.request.Request(f"https://{registry_name}.azurecr.io/v2/harness/manifests/{tag}",
                                         headers={"Authorization": f"Bearer {token['access_token']}",
                                                  "Accept": "application/vnd.docker.distribution.manifest.v2+json, application/vnd.oci.image.manifest.v1+json"})
        with urllib.request.urlopen(request, timeout=60) as response:
            digest = response.headers["Docker-Content-Digest"]
    IMAGE_URI.write_text(f"{registry_name}.azurecr.io/harness@{digest}\n", encoding="utf-8")
    print(f"image: harness:{tag}, {digest[:19]}...")
    return 0


# --- check ---------------------------------------------------------------------------------------

def redact(value):
    return json.loads(GUID.sub("<id>", json.dumps(value, default=str)))


def check(args: argparse.Namespace) -> int:
    env = env_from(args.azure_env)
    arm = Arm(env)
    sub = arm.sub
    lab = outputs(LAB / "terraform")
    rg = f"/subscriptions/{sub}/resourceGroups/rg-ops-assistant"
    record = {"checked": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    accounts = arm.get(f"{rg}/providers/Microsoft.CognitiveServices/accounts", "2025-06-01")
    record["accounts"] = [{"name": a["name"], "location": a["location"], "state": a["properties"].get("provisioningState"),
                           "publicNetworkAccess": a["properties"].get("publicNetworkAccess"),
                           "networkInjections": a["properties"].get("networkInjections"),
                           "allowProjectManagement": a["properties"].get("allowProjectManagement"),
                           "disableLocalAuth": a["properties"].get("disableLocalAuth")}
                          for a in accounts.get("value", [])] if "error" not in accounts else accounts
    project_id = lab.get("project_id", "")
    if project_id:
        project = arm.get(project_id, "2025-06-01")
        record["project"] = {k: project.get("properties", {}).get(k) for k in ("provisioningState", "endpoints")} | \
                            {"identity": (project.get("identity") or {}).get("type")} if "error" not in project else project
        conns = arm.get(f"{project_id}/connections", "2025-06-01")
        record["project_connections"] = [c["name"] for c in conns.get("value", [])] if "error" not in conns else conns
        caps = arm.get(f"{project_id}/capabilityHosts", "2025-06-01")
        record["project_capability_hosts"] = [c["name"] for c in caps.get("value", [])] if "error" not in caps else caps
        account_id = project_id.rsplit("/projects/", 1)[0]
        acaps = arm.get(f"{account_id}/capabilityHosts", "2025-06-01")
        record["account_capability_hosts"] = [c["name"] for c in acaps.get("value", [])] if "error" not in acaps else acaps
    deployments = []
    for a in (accounts.get("value", []) if "error" not in accounts else []):
        d = arm.get(f"{a['id']}/deployments", "2025-06-01")
        for dep in d.get("value", []):
            deployments.append({"account": a["name"], "name": dep["name"], "sku": dep.get("sku"),
                                "state": dep["properties"].get("provisioningState"),
                                "model": dep["properties"].get("model", {}).get("name")})
    record["deployments"] = deployments
    registries = arm.get(f"{rg}/providers/Microsoft.ContainerRegistry/registries", "2025-04-01")
    record["registries"] = [{"name": r["name"], "sku": r["sku"]["name"], "state": r["properties"].get("provisioningState"),
                             "roleAssignmentMode": r["properties"].get("roleAssignmentMode"),
                             "armTokenPolicy": (r["properties"].get("policies") or {}).get("azureADAuthenticationAsArmPolicy")}
                            for r in registries.get("value", [])] if "error" not in registries else registries
    endpoints = arm.get(f"{rg}/providers/Microsoft.Network/privateEndpoints", "2024-05-01")
    record["private_endpoints"] = [{"name": e["name"], "state": e["properties"].get("provisioningState"),
                                    "connection": [c["properties"].get("privateLinkServiceConnectionState", {}).get("status")
                                                   for c in e["properties"].get("privateLinkServiceConnections", [])]}
                                   for e in endpoints.get("value", [])] if "error" not in endpoints else endpoints
    assignments = arm.get(f"{rg}/providers/Microsoft.Authorization/policyAssignments", "2024-04-01")
    record["policy_assignments"] = [a["name"] for a in assignments.get("value", [])] if "error" not in assignments else assignments
    budgets = arm.get(f"{rg}/providers/Microsoft.Consumption/budgets", "2024-08-01")
    record["budgets"] = [{"name": b["name"], "amount": b["properties"].get("amount"),
                          "notifications": sorted((b["properties"].get("notifications") or {}).keys())}
                         for b in budgets.get("value", [])] if "error" not in budgets else budgets
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(redact(record), indent=1) + "\n", encoding="utf-8")
    print(json.dumps(redact({k: record.get(k) for k in ("accounts", "project", "project_connections",
                                                         "project_capability_hosts", "deployments")}))[:1500])
    return 0


# --- leftovers -----------------------------------------------------------------------------------

def leftovers(args: argparse.Namespace) -> int:
    env = env_from(args.azure_env)
    arm = Arm(env)
    sub = arm.sub
    groups = arm.get(f"/subscriptions/{sub}/resourcegroups", "2021-04-01")
    print("resource groups:", [g["name"] for g in groups.get("value", [])])
    deleted = arm.get(f"/subscriptions/{sub}/providers/Microsoft.CognitiveServices/deletedAccounts", "2025-06-01")
    print("soft-deleted cognitive accounts:", [d["name"] for d in deleted.get("value", [])] if "error" not in deleted else deleted)
    roles = arm.get(f"/subscriptions/{sub}/providers/Microsoft.Authorization/roleAssignments", "2022-04-01")
    scoped = [a["properties"]["scope"].rsplit("/", 1)[-1] for a in roles.get("value", [])
              if "/resourceGroups/" in a["properties"]["scope"]]
    print("role assignments below the subscription:", scoped)
    defs = arm.get(f"/subscriptions/{sub}/providers/Microsoft.Authorization/policyDefinitions", "2024-04-01")
    custom = [d["name"] for d in defs.get("value", []) if d.get("properties", {}).get("policyType") == "Custom"]
    print("custom policy definitions:", custom)
    budgets = arm.get(f"/subscriptions/{sub}/providers/Microsoft.Consumption/budgets", "2024-08-01")
    print("subscription budgets:", [b["name"] for b in budgets.get("value", [])] if "error" not in budgets else budgets)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--azure-env", help="a file with ARM_*= lines")
    commands = parser.add_subparsers(dest="command", required=True)
    t = commands.add_parser("tfvars")
    t.add_argument("--budget-email", required=True, help="Azure refuses a budget without a notification")
    t.set_defaults(run=tfvars)
    commands.add_parser("image").set_defaults(run=image)
    c = commands.add_parser("check")
    c.add_argument("--out", type=Path, required=True)
    c.set_defaults(run=check)
    commands.add_parser("leftovers").set_defaults(run=leftovers)
    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
