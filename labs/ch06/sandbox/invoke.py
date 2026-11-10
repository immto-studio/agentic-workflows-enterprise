"""One invocation of the lab's runtime with a token for the bot's app, and what the runtime logged.

  python invoke.py --entra-apps FILE --out ../results/<date>/invocation.json [--prompt "..."] [--direct]

The bot's app (book #69) has no credential of its own; this gives it one for the session, a
certificate made here and uploaded through Graph, asks Entra for a client-credentials token with the
runtime's `.default` scope (a v2.0 token whose `aud` is the runtime's client ID and whose `azp` is the
bot's, what runtime.tf's authorizer checks), and calls InvokeAgentRuntime over HTTPS with it as the
bearer, through the sandbox's bot stand-in in the VPC when there is one (the runtime's resource policy
admits calls through Larkspur's endpoint only; --direct calls from here and records the refusal). The
session ID ends as the adapter requires, with a hash of the token's `oid`. Then it reads
the runtime's log group for the harness's lines: the tool check against the lock, the token vault's
answer, the model call, or the refusal. Writes JSON with account IDs removed; prints no token.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).resolve().parent
TERRAFORM = HERE.parent / "terraform"
BOT_CERT = HERE / "bot-cert.pem"  # the public half; the key stays in memory


def outputs(folder: Path = TERRAFORM) -> dict:
    run = subprocess.run(["terraform", "output", "-json"], cwd=folder, capture_output=True, text=True, check=True)
    return {name: value["value"] for name, value in json.loads(run.stdout).items()}


def sandbox_outputs() -> dict:
    try:
        return outputs(HERE)
    except Exception:  # no sandbox state: the lab stands on Larkspur's own platform
        return {}


GUID_RX = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


def redact(value: Any, entra: dict[str | None, str] | None = None) -> Any:
    """Account IDs become <account>, and each Entra identifier in `entra` (identifier to name) becomes its name."""
    text = json.dumps(value, default=str)
    for ident, name in (entra or {}).items():      # first: a GUID can end in twelve digits
        if ident and GUID_RX.fullmatch(ident):
            text = re.sub(re.escape(ident), name, text, flags=re.IGNORECASE)
    return json.loads(re.sub(r"\b\d{12}\b", "<account>", text))


def session_suffix(user: str) -> str:
    """As labs/ch05/adapter/runtime_adapter.py builds it: the session names the engineer the token names."""
    return "-" + hashlib.sha256(user.encode("utf-8")).hexdigest()[:32]


def bot_certificate() -> tuple[bytes, Any]:
    """A two-day self-signed certificate for the bot's client assertion; the key lives in this process."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "larkspur-sandbox-bot")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=2)).sign(key, hashes.SHA256()))
    BOT_CERT.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert.public_bytes(serialization.Encoding.DER), key


def runtime_log(session: Any, region: str, runtime_id: str, since_ms: int, wait_s: int = 150) -> dict[str, Any]:
    """The harness's lines from the runtime's log groups since the invocation, once delivery catches up."""
    logs = session.client("logs", region_name=region)
    groups = [g["logGroupName"] for g in logs.describe_log_groups(logGroupNamePrefix="/aws/bedrock-agentcore/runtimes/")
              .get("logGroups", []) if runtime_id in g["logGroupName"]]
    deadline = time.time() + wait_s
    found: dict[str, list[str]] = {}
    while time.time() < deadline:
        for group in groups:
            events = logs.filter_log_events(logGroupName=group, startTime=since_ms, limit=200).get("events", [])
            if events:
                found[group] = [e["message"].rstrip()[:400] for e in events]
        if found:
            break
        time.sleep(15)
    return {"groups": groups, "lines": found or "no record within the wait"}


def main(argv: list[str] | None = None) -> int:
    import boto3

    import entra

    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--entra-apps", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--prompt", default="Is claims-api healthy?")
    parser.add_argument("--region", default="us-east-2")
    parser.add_argument("--direct", action="store_true", help="call from here, outside the VPC (the policy refuses it)")
    args = parser.parse_args(argv)

    apps = json.loads(Path(args.entra_apps).read_text(encoding="utf-8"))
    out = outputs()
    runtime_arn, endpoint = out["runtime_arn"], out["runtime_endpoint"]
    runtime_id = runtime_arn.rsplit("/", 1)[-1]
    record: dict[str, Any] = {"region": args.region, "invoked": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "endpoint": endpoint}

    der, key = bot_certificate()
    record["bot_credential"] = entra.set_certificate(apps["bot_object_id"], der, "sandbox bot certificate (book #69)")
    time.sleep(20)  # a new key credential takes a moment to reach the token service
    token = entra.token_for(apps["entra_tenant_id"], apps["entra_bot_client_id"],
                            f"api://{apps['entra_runtime_client_id']}/.default", der, key)["access_token"]
    claims = entra.claims_of(token)
    record["token"] = {k: claims.get(k) for k in ("aud", "azp", "ver", "tid", "roles", "oid")}
    user = claims.get("oid") or claims.get("sub")
    session_id = f"sandbox-{uuid.uuid4().hex}{session_suffix(user)}"
    record["session_id_shape"] = f"sandbox-<32 hex>{session_suffix(user)}"

    url = (f"https://bedrock-agentcore.{args.region}.amazonaws.com/runtimes/{urllib.parse.quote(runtime_arn, safe='')}"
           f"/invocations?qualifier={endpoint}")
    session = boto3.Session(region_name=args.region)
    started = int(time.time() * 1000)
    clock = time.perf_counter()
    bot = sandbox_outputs().get("bot_stand_in")
    if bot and not args.direct:
        # From inside the VPC, as the bot stands: the runtime's policy admits its endpoint's callers only.
        answer = session.client("lambda").invoke(FunctionName=bot, Payload=json.dumps({
            "url": url, "token": token, "session_id": session_id, "body": {"prompt": args.prompt}}).encode("utf-8"))
        reply = json.loads(answer["Payload"].read())
        record["invocation"] = {"from": "the bot stand-in in the VPC", **reply, "body": (reply.get("body") or "")[:1500]}
    else:
        reply = httpx.post(url, timeout=120.0, json={"prompt": args.prompt},
                           headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                                    "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id})
        record["invocation"] = {"from": "outside the VPC", "status": reply.status_code,
                                "headers": {k: v for k, v in reply.headers.items() if k.lower().startswith(("x-amzn", "content-type"))},
                                "body": reply.text[:1500]}
    record["invocation"]["elapsed_s"] = round(time.perf_counter() - clock, 1)
    print(f"invocation ({record['invocation']['from']}): HTTP {record['invocation'].get('status')} in "
          f"{record['invocation']['elapsed_s']}s; body: {str(record['invocation'].get('body') or record['invocation'].get('error'))[:300]}")

    record["runtime_log"] = runtime_log(session, args.region, runtime_id, started - 60_000)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    names = {claims.get("tid"): "<tenant>", claims.get("aud"): "<runtime-app>", claims.get("azp"): "<bot-app>",
             user: "<engineer-object-id>"}
    args.out.write_text(json.dumps(redact(record, names), indent=1) + "\n", encoding="utf-8")
    lines = record["runtime_log"]["lines"]
    if isinstance(lines, dict):
        for group, items in lines.items():
            print(f"{group}: {len(items)} lines")
            for line in items[:30]:
                print("  ", re.sub(r"\b\d{12}\b", "<account>", line)[:300])
    else:
        print(lines)
    return 0


if __name__ == "__main__":
    sys.exit(main())
