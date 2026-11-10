"""Chapter 6's sandbox, after `terraform apply` here: build the harness image, then write lab.tfvars.

  python sandbox.py image    the sandbox root into ../image/private-ca.pem, the build context to S3
                             with the image's lock written from the stand-ins' tool definitions, a
                             CodeBuild run, and the pushed image's digest into image-uri.txt
  python sandbox.py tfvars [--entra-apps FILE]
                             ../terraform/lab.tfvars for a run on synthetic data in the sandbox's
                             Region (book D-036), with the stand-ins' identifiers; with --entra-apps,
                             the author's four registrations (book #69) instead of placeholders
  python sandbox.py signing-cert --entra-apps FILE
                             step 6 of the lab's README: an X.509 certificate from the lab's signing
                             key (kms:GetPublicKey, signed by kms:Sign), uploaded to the tool
                             gateway's app, its thumbprint written into FILE
  python sandbox.py register-ca
                             after the lab's apply, the sandbox root on every target of the tool
                             gateway (step 7 of the lab's README)

Credentials come from the environment (AWS_PROFILE and the shared files). `tfvars` takes the Entra
tenant from ARM_TENANT_ID in the environment or in the file --azure-env names, or from --entra-apps;
without --entra-apps the runtime's, the bot's and the tool gateway's client IDs are placeholders,
since the sandbox registers no app in Entra. Prints statuses only: no account ID, no secret.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
LAB = HERE.parent
LABS = LAB.parent
DOCKERFILE = LAB / "image" / "Dockerfile"
IMAGE_URI = HERE / "image-uri.txt"  # git-ignored: it names the account
TFVARS = LAB / "terraform" / "lab.tfvars"  # git-ignored
STAND_IN_TOOLS = HERE / "mcp_stand_in" / "tools.json"
LOCK_IN_IMAGE = Path("ch05/mcp-server/tools.lock.json")  # what the Dockerfile copies; the sandbox's lock replaces it
SIGNING_CERT = HERE / "tool-gateway-cert.pem"  # public; *.pem is git-ignored all the same

# A copy of the harness's lock functions (labs/ch05/harness/client.py), as the harness itself copies
# the server's: the lock is trusted by its bytes, not by shared code.
LOCKED_FIELDS = ("name", "title", "description", "inputSchema", "outputSchema", "annotations", "execution")


def definition_hash(definition: dict[str, Any]) -> str:
    canonical = {key: definition[key] for key in LOCKED_FIELDS if definition.get(key) is not None}
    text = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stand_in_lock() -> bytes:
    """The image's lock for the sandbox: the four tools the stand-ins serve, hashed as the harness hashes.

    The README's pipeline writes this from the gateway's list after the targets synchronize; the
    sandbox writes it from the definitions the stand-ins serve, so the harness's check of the gateway's
    list is a check of what the gateway relays."""
    tools = json.loads(STAND_IN_TOOLS.read_text(encoding="utf-8"))["tools"]
    data = {
        "comment": "The sandbox's lock: the four tools of the incident manifest as the MCP stand-ins define "
                   "them (sandbox/mcp_stand_in/tools.json), hashed as labs/ch05/harness/client.py hashes.",
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "tools": {name: {"sha256": definition_hash(d), "definition": d} for name, d in sorted(tools.items())},
    }
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def outputs() -> dict:
    run = subprocess.run(["terraform", "output", "-json"], cwd=HERE, capture_output=True, text=True, check=True)
    return {name: value["value"] for name, value in json.loads(run.stdout).items()}


def region_of(repository_url: str) -> str:
    match = re.match(r"^\d{12}\.dkr\.ecr\.([a-z0-9-]+)\.amazonaws\.com/", repository_url)
    if not match:
        raise SystemExit("can't read the Region from the repository URL")
    return match.group(1)


def context_files() -> list[Path]:
    """The Dockerfile and every source its COPY instructions name, relative to labs/."""
    text = DOCKERFILE.read_text(encoding="utf-8").replace("\\\n", " ")
    files = [DOCKERFILE.relative_to(LABS)]
    for line in text.splitlines():
        words = line.split()
        if words and words[0] == "COPY":
            files += [Path(word) for word in words[1:-1] if not word.startswith("--")]
    return files


def image(_: argparse.Namespace) -> int:
    import boto3  # here, so the tests can read context_files without it

    out = outputs()
    lab = out["lab"]
    region = region_of(lab["repository_url"])
    session = boto3.Session(region_name=region)
    (LAB / "image" / "private-ca.pem").write_text(out["root_ca_pem"], encoding="utf-8")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for relative in context_files():
            path = LABS / relative
            if not path.is_file():
                raise SystemExit(f"the build context lacks {relative.as_posix()}")
            if relative == LOCK_IN_IMAGE:
                archive.writestr(relative.as_posix(), stand_in_lock())
                continue
            archive.write(path, relative.as_posix())
    session.client("s3").put_object(Bucket=lab["build_bucket"], Key="context.zip", Body=buffer.getvalue())
    print(f"context: {len(context_files())} files, {len(buffer.getvalue()) // 1024} KB, the sandbox's four-tool lock")

    codebuild = session.client("codebuild")
    build = codebuild.start_build(projectName=lab["build_project"])["build"]
    phase = None
    while build["buildStatus"] == "IN_PROGRESS":
        time.sleep(15)
        build = codebuild.batch_get_builds(ids=[build["id"]])["builds"][0]
        if build.get("currentPhase") != phase:
            phase = build.get("currentPhase")
            print("phase:", phase)
    print("build:", build["buildStatus"])
    if build["buildStatus"] != "SUCCEEDED":
        logs = build.get("logs", {})
        if logs.get("groupName") and logs.get("streamName"):
            events = session.client("logs").get_log_events(
                logGroupName=logs["groupName"], logStreamName=logs["streamName"], limit=40)["events"]
            for event in events:
                print("  ", re.sub(r"\b\d{12}\b", "<account>", event["message"].rstrip()))
        return 1

    tag = f"build-{build['buildNumber']}"
    repository = lab["repository_url"].split("/", 1)[1]
    detail = session.client("ecr").describe_images(repositoryName=repository, imageIds=[{"imageTag": tag}])
    digest = detail["imageDetails"][0]["imageDigest"]
    IMAGE_URI.write_text(f"{lab['repository_url']}@{digest}\n", encoding="utf-8")
    print(f"image: {tag}, {digest[:19]}...")
    return 0


def tenant(path: str | None) -> str:
    value = os.environ.get("ARM_TENANT_ID")
    if not value and path:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.startswith("ARM_TENANT_ID="):
                value = line.split("=", 1)[1].strip()
    if not value:
        raise SystemExit("no Entra tenant: set ARM_TENANT_ID or give --azure-env")
    return value


def entra_apps(path: str | None) -> dict[str, str]:
    """The author's registrations (book #69), by the lab's variable names; empty without a file."""
    if not path:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    keys = ("entra_tenant_id", "entra_runtime_client_id", "entra_bot_client_id", "entra_tool_gateway_client_id",
            "entra_tool_gateway_cert_thumbprint", "mcp_servers_scope")
    missing = [k for k in keys if not data.get(k)]
    if missing:
        raise SystemExit(f"{path} lacks {', '.join(missing)}")
    return {k: data[k] for k in keys}


def tfvars(args: argparse.Namespace) -> int:
    import boto3

    lab = outputs()["lab"]
    region = region_of(lab["repository_url"])
    account = boto3.Session(region_name=region).client("sts").get_caller_identity()["Account"]
    placeholder = {name: str(uuid.uuid5(uuid.NAMESPACE_URL, f"https://larkspur.example/sandbox/{name}"))
                   for name in ("runtime", "bot", "tool-gateway")}
    apps = entra_apps(args.entra_apps)
    if apps.get("entra_tool_gateway_cert_thumbprint", "").startswith("<"):
        apps["entra_tool_gateway_cert_thumbprint"] = "sandbox-no-certificate-yet"  # until signing-cert runs
    values = {
        "region": region,
        "synthetic_data": True,
        "account_id": account,
        "force_destroy_stores": True,
        "vpc_id": lab["vpc_id"],
        "vpc_cidr": lab["vpc_cidr"],
        "subnet_ids": lab["subnet_ids"],
        "route_table_ids": lab["route_table_ids"],
        "image_uri": IMAGE_URI.read_text(encoding="utf-8").strip(),
        "ecr_repository_arn": lab["ecr_repository_arn"],
        "entra_tenant_id": apps.get("entra_tenant_id") or tenant(args.azure_env),
        "entra_runtime_client_id": apps.get("entra_runtime_client_id", placeholder["runtime"]),
        "entra_bot_client_id": apps.get("entra_bot_client_id", placeholder["bot"]),
        "entra_tool_gateway_client_id": apps.get("entra_tool_gateway_client_id", placeholder["tool-gateway"]),
        "entra_tool_gateway_cert_thumbprint": apps.get("entra_tool_gateway_cert_thumbprint", "sandbox-no-entra-app"),
        "mcp_servers_scope": apps.get("mcp_servers_scope", "api://larkspur-mcp-servers-sandbox/.default"),
        "private_ca_s3_uri": lab["private_ca_s3_uri"],
        "model_gateway_url": "https://llm-gateway.sandbox.larkspur.example/v1",
        "model_gateway_role_arn": lab["model_gateway_role_arn"],
        "gateway_key_secret_arn": lab["gateway_key_secret_arn"],
        "otel_collector_endpoint": "https://otel-collector.sandbox.larkspur.example:4318",
        "model_gateway_security_group_id": lab["model_gateway_security_group_id"],
        "collector_security_group_id": lab["collector_security_group_id"],
        "mcp_servers_security_group_id": lab["mcp_servers_security_group_id"],
        "k8s_mcp_endpoint": "https://k8s-mcp.sandbox.larkspur.example/mcp",
        "knowledge_mcp_endpoint": "https://knowledge-mcp.sandbox.larkspur.example/mcp",
        "tool_server_role_arns": lab["tool_server_role_arns"],
        "eks_cluster_name": lab["eks_cluster_name"],
    }
    # JSON values are HCL expressions too, so json.dumps writes every value.
    lines = ["# Written by sandbox/sandbox.py for a run on synthetic data (book D-036). Git-ignored."]
    lines += [f"{name} = {json.dumps(value)}" for name, value in values.items()]
    TFVARS.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"lab.tfvars: {len(values)} values, region {region}, synthetic data, "
          f"{'the author\'s registrations' if apps else 'placeholder apps'}")
    return 0


def signing_cert(args: argparse.Namespace) -> int:
    """Step 6 of the lab's README. The private key never leaves KMS: the certificate's signature is one
    kms:Sign over the DER of its TBS part, and the thumbprint AgentCore puts in the JWT header
    (x5t#S256) is the SHA-256 of the DER."""
    import boto3
    from asn1crypto import algos, keys, x509
    from cryptography import x509 as cx509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    import entra

    lab = outputs()["lab"]
    region = region_of(lab["repository_url"])
    run = subprocess.run(["terraform", "output", "-raw", "tool_gateway_signing_key_arn"], cwd=LAB / "terraform",
                         capture_output=True, text=True, check=True)
    key_arn = run.stdout.strip()
    kms = boto3.Session(region_name=region).client("kms")
    public = kms.get_public_key(KeyId=key_arn)
    if public["KeySpec"] != "RSA_2048" or "RSASSA_PKCS1_V1_5_SHA_256" not in public["SigningAlgorithms"]:
        raise SystemExit(f"the signing key is {public['KeySpec']} with {public['SigningAlgorithms']}")
    name = x509.Name.build({"common_name": "larkspur-sandbox-tool-gateway", "organization_name": "Larkspur Mutual (fictional)"})
    now = datetime.now(timezone.utc).replace(microsecond=0)
    algorithm = algos.SignedDigestAlgorithm({"algorithm": "sha256_rsa"})
    tbs = x509.TbsCertificate({
        "version": "v3",
        "serial_number": int.from_bytes(os.urandom(16), "big") >> 1,
        "signature": algorithm,
        "issuer": name,
        "validity": x509.Validity({"not_before": x509.Time({"utc_time": now - timedelta(minutes=5)}),
                                   "not_after": x509.Time({"utc_time": now + timedelta(days=2)})}),
        "subject": name,
        "subject_public_key_info": keys.PublicKeyInfo.load(public["PublicKey"]),
        "extensions": [
            x509.Extension({"extn_id": "basic_constraints", "critical": True, "extn_value": x509.BasicConstraints({"ca": False})}),
            x509.Extension({"extn_id": "key_usage", "critical": True, "extn_value": x509.KeyUsage({"digital_signature"})}),
        ],
    })
    signature = kms.sign(KeyId=key_arn, Message=tbs.dump(), MessageType="RAW",
                         SigningAlgorithm="RSASSA_PKCS1_V1_5_SHA_256")["Signature"]
    der = x509.Certificate({"tbs_certificate": tbs, "signature_algorithm": algorithm, "signature_value": signature}).dump()
    certificate = cx509.load_der_x509_certificate(der)
    certificate.public_key().verify(certificate.signature, certificate.tbs_certificate_bytes, padding.PKCS1v15(), hashes.SHA256())
    pem = "-----BEGIN CERTIFICATE-----\n" + "\n".join(
        base64.b64encode(der).decode("ascii")[i:i + 64] for i in range(0, len(base64.b64encode(der)), 64)) + "\n-----END CERTIFICATE-----\n"
    SIGNING_CERT.write_text(pem, encoding="utf-8")
    prints = entra.thumbprints(der)
    apps = json.loads(Path(args.entra_apps).read_text(encoding="utf-8"))
    uploaded = entra.set_certificate(apps["tool_gateway_object_id"], der, "sandbox signing key, in KMS (book #69)")
    apps["entra_tool_gateway_cert_thumbprint"] = prints["x5t#S256"]
    apps["tool_gateway_cert_not_after"] = certificate.not_valid_after_utc.isoformat()
    Path(args.entra_apps).write_text(json.dumps(apps, indent=2) + "\n", encoding="utf-8")
    print(f"certificate: {certificate.subject.rfc4514_string()}, valid to {certificate.not_valid_after_utc:%Y-%m-%d %H:%M} UTC, "
          f"signed in KMS, verified against the key's public half")
    print(f"x5t#S256: {prints['x5t#S256']}  (into {Path(args.entra_apps).name} and lab.tfvars)")
    print(f"uploaded to {uploaded['app']}: {uploaded['keys']}")
    return 0


def register_ca(_: argparse.Namespace) -> int:
    """Step 7 of the lab's README: the root CA on every target of the tool gateway, which the
    provider has no field for. UpdateGatewayTarget replaces the target, so the call repeats it."""
    import boto3
    from botocore.exceptions import ClientError

    lab = outputs()["lab"]
    control = boto3.Session(region_name=region_of(lab["repository_url"])).client("bedrock-agentcore-control")
    run = subprocess.run(["terraform", "output", "-raw", "tool_gateway_url"], cwd=LAB / "terraform",
                         capture_output=True, text=True, check=True)
    gateway = run.stdout.strip().split("//", 1)[1].split(".", 1)[0]
    kept = ("name", "description", "targetConfiguration", "credentialProviderConfigurations",
            "metadataConfiguration", "privateEndpoint")
    for item in control.list_gateway_targets(gatewayIdentifier=gateway)["items"]:
        target = control.get_gateway_target(gatewayIdentifier=gateway, targetId=item["targetId"])
        request = {key: target[key] for key in kept if target.get(key)}
        # GetGatewayTarget lists a header AgentCore adds itself for the policy engine
        # (x-amzn-bedrock-agentcore-policy-session-id), and UpdateGatewayTarget refuses it back.
        metadata = request.get("metadataConfiguration", {})
        for field, values in metadata.items():
            if isinstance(values, list):
                metadata[field] = [v for v in values if not str(v).lower().startswith("x-amzn-")]
        request["certificateConfigurations"] = [{"s3": {"uri": lab["private_ca_s3_uri"]}}]
        try:
            control.update_gateway_target(gatewayIdentifier=gateway, targetId=item["targetId"], **request)
        except ClientError as exc:
            print(f"{item['name']}: {exc.response['Error']['Code']}: {exc.response['Error'].get('Message', '')[:200]}")
            continue
        for _ in range(40):  # the update synchronizes the target again
            target = control.get_gateway_target(gatewayIdentifier=gateway, targetId=item["targetId"])
            if target["status"] not in ("UPDATING", "CREATING", "SYNCHRONIZING"):
                break
            time.sleep(15)
        reasons = "; ".join(target.get("statusReasons") or [])
        print(f"{item['name']}: {target['status']} {re.sub(r'[0-9]{12}', '<account>', reasons)[:300]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("image").set_defaults(run=image)
    write = commands.add_parser("tfvars")
    write.add_argument("--azure-env", help="a file with an ARM_TENANT_ID= line")
    write.add_argument("--entra-apps", help="the author's registrations, as secrets/entra-sandbox-apps.json")
    write.set_defaults(run=tfvars)
    cert = commands.add_parser("signing-cert")
    cert.add_argument("--entra-apps", required=True, help="the registrations file; the thumbprint is written into it")
    cert.set_defaults(run=signing_cert)
    commands.add_parser("register-ca").set_defaults(run=register_ca)
    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
