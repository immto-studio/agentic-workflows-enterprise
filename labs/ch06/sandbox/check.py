"""After a sandbox apply of chapter 6's lab: what AWS made of it, and the first-apply facts it can settle.

  python check.py --out ../results/<date>/first-apply.json [--model-call] [--stand-in-minutes N]

Reads the lab's Terraform outputs (../terraform) and asks AWS, read-only, for the state of the
runtime, the tool gateway and its targets, the policy engine, the knowledge base, the guardrail,
the endpoints and invocation logging. With --model-call it makes one small Converse call in the
Region, outside the VPC, and reads back the invocation log's record, to see whether a record with
text delivery off holds metadata only. When the sandbox's MCP stand-ins exist (its `mcp_stand_ins`
output), their log of the last N minutes is summarized too: which methods the gateway sent to
which server, and the token it presented, by its header and claims. Writes JSON with account IDs
removed.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
TERRAFORM = HERE.parent / "terraform"
LOG_GROUP = "/aws/bedrock/model-invocations"


GUID_RX = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


def redact(value: Any, entra: dict[str | None, str] | None = None) -> Any:
    """Account IDs become <account>, and each Entra identifier in `entra` (identifier to name) becomes its name."""
    text = json.dumps(value, default=str)
    for ident, name in (entra or {}).items():      # first: a GUID can end in twelve digits
        if ident and GUID_RX.fullmatch(ident):
            text = re.sub(re.escape(ident), name, text, flags=re.IGNORECASE)
    return json.loads(re.sub(r"\b\d{12}\b", "<account>", text))


def entra_names(record: dict) -> dict[str | None, str]:
    """The tenant and the two apps that the token the gateway presented names, for `redact`."""
    claims = ((record.get("mcp_stand_ins") or {}).get("token_presented") or {}).get("claims") or {}
    return {claims.get("tid"): "<tenant>",
            str(claims.get("aud") or "").removeprefix("api://"): "<mcp-servers-app>",
            claims.get("appid") or claims.get("azp"): "<tool-gateway-app>"}


def outputs(folder: Path = TERRAFORM) -> dict:
    run = subprocess.run(["terraform", "output", "-json"], cwd=folder, capture_output=True, text=True, check=True)
    return {name: value["value"] for name, value in json.loads(run.stdout).items()}


def stand_in_log(session: Any, log_group: str, minutes: int) -> dict[str, Any]:
    """What the gateway sent the stand-ins: the request lines the function printed (handler.py)."""
    logs = session.client("logs")
    since = int((time.time() - minutes * 60) * 1000)
    requests: list[dict[str, Any]] = []
    token = None
    for page in logs.get_paginator("filter_log_events").paginate(logGroupName=log_group, startTime=since):
        for event in page.get("events", []):
            text = event["message"].strip()
            if not text.startswith("{"):
                continue
            try:
                record = json.loads(text)
            except json.JSONDecodeError:
                continue
            if record.get("event") == "request":
                requests.append(record)
                if record.get("token", {}).get("claims") and token is None:
                    token = record["token"]
    by_host: dict[str, dict[str, int]] = {}
    for r in requests:
        host = str(r.get("host", "?")).split(".", 1)[0]
        by_host.setdefault(host, {})
        by_host[host][r.get("method", "?")] = by_host[host].get(r.get("method", "?"), 0) + 1
    return {"requests": len(requests), "methods_by_server": by_host, "token_presented": token,
            "actor_header_seen": any(r.get("actor_header") for r in requests),
            "sessions": sorted({str(r.get("session")) for r in requests if r.get("session")})[:5]}


def ask(call: Callable[[], Any]) -> Any:
    """AWS's answer, or what went wrong: a refusal is a finding here, not a crash."""
    from botocore.exceptions import ClientError

    try:
        return call()
    except ClientError as exc:
        return {"error": exc.response["Error"]["Code"], "message": exc.response["Error"].get("Message", "")}
    except Exception as exc:  # an API this boto3 lacks, or a parameter it refuses
        return {"error": type(exc).__name__, "message": str(exc)[:300]}


def main(argv: list[str] | None = None) -> int:
    import boto3

    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--region", default="us-east-2")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model-call", action="store_true")
    parser.add_argument("--stand-in-minutes", type=int, default=180, help="how far back to read the stand-ins' log")
    args = parser.parse_args(argv)

    session = boto3.Session(region_name=args.region)
    control = session.client("bedrock-agentcore-control")
    out = outputs()
    runtime_id = out["runtime_arn"].rsplit("/", 1)[-1]
    gateway_id = out["tool_gateway_url"].split("//", 1)[1].split(".", 1)[0]
    record: dict[str, Any] = {"region": args.region, "checked": time.strftime("%Y-%m-%dT%H:%M:%S%z")}

    runtime = ask(lambda: control.get_agent_runtime(agentRuntimeId=runtime_id))
    record["runtime"] = {k: runtime.get(k) for k in ("status", "failureReason", "agentRuntimeVersion", "platformVersion")} \
        if "error" not in runtime else runtime
    gateway = ask(lambda: control.get_gateway(gatewayIdentifier=gateway_id))
    record["tool_gateway"] = {k: gateway.get(k) for k in ("status", "statusReasons", "authorizerType")} \
        if "error" not in gateway else gateway
    targets = {}
    for name, target_id in (out.get("tool_gateway_targets") or {}).items():
        target = ask(lambda target_id=target_id: control.get_gateway_target(gatewayIdentifier=gateway_id,
                                                                            targetId=target_id))
        targets[name] = {k: target.get(k) for k in ("status", "statusReasons", "lastSynchronizedAt")} \
            if "error" not in target else target
    record["tool_gateway_targets"] = targets
    listed = ask(lambda: control.list_gateway_targets(gatewayIdentifier=gateway_id))
    record["targets_listed"] = [{k: t.get(k) for k in ("name", "status")} for t in listed.get("items", [])] \
        if "error" not in listed else listed

    engine_id = gateway.get("policyEngineConfiguration", {}).get("arn", "").rsplit("/", 1)[-1] if "error" not in gateway else ""
    if engine_id:
        engine = ask(lambda: control.get_policy_engine(policyEngineId=engine_id))
        policies = ask(lambda: control.list_policies(policyEngineId=engine_id))
        record["policy_engine"] = {"status": engine.get("status"), "policies": [
            {k: p.get(k) for k in ("name", "status", "statusReasons")} for p in policies.get("policies", [])]}

    agent = session.client("bedrock-agent")
    kb = ask(lambda: agent.get_knowledge_base(knowledgeBaseId=out["knowledge_base_id"]))
    record["knowledge_base"] = {"status": kb.get("knowledgeBase", {}).get("status")} if "error" not in kb else kb

    bedrock = session.client("bedrock")
    guardrail = ask(lambda: bedrock.get_guardrail(guardrailIdentifier=out["guardrail"]["identifier"],
                                                  guardrailVersion=str(out["guardrail"]["version"])))
    record["guardrail"] = {k: guardrail.get(k) for k in ("status", "version", "crossRegionDetails")} \
        if "error" not in guardrail else guardrail
    logging_config = ask(lambda: bedrock.get_model_invocation_logging_configuration())
    record["invocation_logging"] = logging_config.get("loggingConfig", logging_config)

    ec2 = session.client("ec2")
    service = f"com.amazonaws.{args.region}.bedrock-agentcore.gateway"
    services = ask(lambda: ec2.describe_vpc_endpoint_services(ServiceNames=[service]))
    record["privatelink_gateway_service"] = {"name": service, "exists": bool(services.get("ServiceDetails"))} \
        if "error" not in services else services
    endpoints = ask(lambda: ec2.describe_vpc_endpoints(Filters=[{"Name": "tag:workflow", "Values": ["w3-incident"]}]))
    record["endpoints"] = sorted((e["ServiceName"].split(".", 3)[-1], e["State"]) for e in endpoints.get("VpcEndpoints", [])) \
        if "error" not in endpoints else endpoints

    if args.model_call:
        runtime_client = session.client("bedrock-runtime")
        started = int(time.time() * 1000)
        reply = ask(lambda: runtime_client.converse(
            modelId="us.amazon.nova-lite-v1:0",
            messages=[{"role": "user", "content": [{"text": "Reply with the word ready."}]}],
            inferenceConfig={"maxTokens": 10, "temperature": 0}))
        record["model_call"] = {"stop": reply.get("stopReason"), "usage": reply.get("usage")} if "error" not in reply else reply
        logs = session.client("logs")
        found = None
        for _ in range(24):  # delivery takes a minute or so
            events = ask(lambda: logs.filter_log_events(logGroupName=LOG_GROUP, startTime=started, limit=5))
            if "error" not in events and events.get("events"):
                found = json.loads(events["events"][0]["message"])
                break
            time.sleep(10)
        if found is None:
            record["invocation_record"] = "no record within four minutes"
        else:
            text_fields = [k for k in ("inputBodyJson", "outputBodyJson") if k in found.get("input", {}) or k in found.get("output", {})]
            record["invocation_record"] = {
                "keys": sorted(found), "input_keys": sorted(found.get("input", {})),
                "output_keys": sorted(found.get("output", {})), "text_fields_present": text_fields,
            }

    try:
        stand_ins = outputs(HERE).get("mcp_stand_ins")
    except Exception:  # no sandbox state here: the lab was applied against Larkspur's own platform
        stand_ins = None
    if stand_ins:
        record["mcp_stand_ins"] = ask(lambda: stand_in_log(session, stand_ins["log_group"], args.stand_in_minutes))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(redact(record, entra_names(record)), indent=1) + "\n", encoding="utf-8")
    print(json.dumps(redact({k: record.get(k) for k in ("runtime", "tool_gateway", "tool_gateway_targets",
                                                         "policy_engine", "mcp_stand_ins", "invocation_record")}))[:2500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
