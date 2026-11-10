"""The sandbox's MCP stand-ins (book #69): the catalog's four tools served by server, the lock the image
gets from them, the function's answers, and the Terraform that keeps them private and short-lived.

They read sandbox/mcp_stand_ins.tf, sandbox/mcp_stand_in/, and sandbox/sandbox.py; nothing here calls AWS.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import hcl2
import yaml

LAB = Path(__file__).resolve().parent.parent
SANDBOX = LAB / "sandbox"
STAND_IN = SANDBOX / "mcp_stand_in"
CATALOG = yaml.safe_load((LAB / "catalog" / "tools.yaml").read_text(encoding="utf-8"))
MANIFEST = yaml.safe_load((LAB / "manifests" / "w3-incident.yaml").read_text(encoding="utf-8"))
TOOLS = json.loads((STAND_IN / "tools.json").read_text(encoding="utf-8"))
CH05_LOCK = json.loads((LAB.parent / "ch05" / "mcp-server" / "tools.lock.json").read_text(encoding="utf-8"))


def clean(value):
    if isinstance(value, dict):
        return {clean(k): clean(v) for k, v in value.items() if k not in ("__is_block__", "__comments__")}
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, str) and len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    return value


RESOURCES: dict[str, dict] = {}
for name in ("main.tf", "mcp_stand_ins.tf"):
    with (SANDBOX / name).open(encoding="utf-8") as handle:
        for block in clean(hcl2.load(handle)).get("resource", []):
            for kind, named in block.items():
                RESOURCES.setdefault(kind, {}).update(named)


def module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[name] = loaded
    spec.loader.exec_module(loaded)  # type: ignore[union-attr]
    return loaded


HANDLER = module("ch06_stand_in_handler", STAND_IN / "handler.py")
SANDBOX_PY = module("ch06_sandbox_py", SANDBOX / "sandbox.py")


def post(host: str, body: dict, token: str = "") -> tuple[int, dict | None]:
    event = {"httpMethod": "POST", "path": "/mcp", "body": json.dumps(body), "isBase64Encoded": False,
             "headers": {"host": host, "authorization": f"Bearer {token}" if token else ""}}
    reply = HANDLER.lambda_handler(event, None)
    return reply["statusCode"], (json.loads(reply["body"]) if reply["body"] else None)


# --- what they serve ------------------------------------------------------------------------------

def test_the_stand_ins_serve_the_catalogs_tools_by_server() -> None:
    by_server = {}
    for name, tool in CATALOG["tools"].items():
        by_server.setdefault(tool["server"], set()).add(name)
    assert {server: set(names) for server, names in TOOLS["servers"].items()} == by_server
    assert set(TOOLS["tools"]) == set(MANIFEST["tools"]) == set(CATALOG["tools"])
    for name, definition in TOOLS["tools"].items():
        assert definition["name"] == name and definition["inputSchema"]["type"] == "object"
        assert set(definition["inputSchema"]["required"]) == set(MANIFEST["tools"][name]["args"])


def test_chapter_5s_two_tools_are_served_exactly_as_its_lock_pins_them() -> None:
    lock = json.loads(SANDBOX_PY.stand_in_lock())
    assert list(lock["tools"]) == sorted(TOOLS["tools"])
    for name in ("get_pod_status", "get_recent_alerts"):
        assert lock["tools"][name]["sha256"] == CH05_LOCK["tools"][name]["sha256"]
        assert lock["tools"][name]["definition"] == CH05_LOCK["tools"][name]["definition"]
    # The hash is the harness's: the locked fields, sorted keys, compact separators.
    for name, entry in lock["tools"].items():
        canonical = {k: entry["definition"][k] for k in SANDBOX_PY.LOCKED_FIELDS if entry["definition"].get(k) is not None}
        text = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        assert entry["sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_the_image_context_carries_the_sandboxs_lock_in_chapter_5s_place() -> None:
    assert SANDBOX_PY.LOCK_IN_IMAGE.as_posix() in {p.as_posix() for p in SANDBOX_PY.context_files()}
    assert "four tools" in json.loads(SANDBOX_PY.stand_in_lock())["comment"]


# --- how the function answers ---------------------------------------------------------------------

def test_each_host_lists_its_own_tools_and_nothing_else() -> None:
    status, body = post("k8s-mcp.sandbox.larkspur.example", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert status == 200 and [t["name"] for t in body["result"]["tools"]] == TOOLS["servers"]["k8s-mcp"]
    status, body = post("knowledge-mcp.sandbox.larkspur.example", {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert status == 200 and [t["name"] for t in body["result"]["tools"]] == ["search_runbooks"]
    status, body = post("elsewhere.example", {"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    assert body["error"]["code"] == -32000


def test_initialize_echoes_a_known_protocol_version_and_a_notification_gets_202() -> None:
    _, body = post("k8s-mcp.sandbox.larkspur.example", {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                                          "params": {"protocolVersion": "2025-03-26"}})
    assert body["result"]["protocolVersion"] == "2025-03-26" and "tools" in body["result"]["capabilities"]
    _, body = post("k8s-mcp.sandbox.larkspur.example", {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                                          "params": {"protocolVersion": "1999-01-01"}})
    assert body["result"]["protocolVersion"] == HANDLER.PROTOCOL_VERSIONS[0]
    status, body = post("k8s-mcp.sandbox.larkspur.example", {"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert (status, body) == (202, None)


def test_a_call_answers_in_the_tools_output_shape_and_a_wrong_tool_is_an_error() -> None:
    _, body = post("k8s-mcp.sandbox.larkspur.example", {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                                          "params": {"name": "get_pod_status", "arguments": {"service": "claims-api"}}})
    structured = body["result"]["structuredContent"]
    assert set(TOOLS["tools"]["get_pod_status"]["outputSchema"]["required"]) <= set(structured)
    assert structured["service"] == "claims-api" and body["result"]["isError"] is False
    _, body = post("knowledge-mcp.sandbox.larkspur.example", {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                                                                "params": {"name": "get_pod_status", "arguments": {}}})
    assert body["error"]["code"] == -32602


def test_only_post_is_served_and_the_token_is_logged_by_its_claims_never_itself(capsys) -> None:
    assert HANDLER.lambda_handler({"httpMethod": "GET", "headers": {"host": "k8s-mcp.sandbox.larkspur.example"}}, None)["statusCode"] == 405
    header = json.dumps({"alg": "RS256", "typ": "JWT", "x5t": "abc"}).encode()
    claims = json.dumps({"aud": "api://servers", "azp": "gateway-app", "tid": "tenant", "secret_claim": "do-not-log"}).encode()
    import base64
    token = ".".join(base64.urlsafe_b64encode(part).rstrip(b"=").decode() for part in (header, claims)) + ".sig"
    post("k8s-mcp.sandbox.larkspur.example", {"jsonrpc": "2.0", "id": 6, "method": "ping"}, token=token)
    printed = capsys.readouterr().out
    assert '"azp": "gateway-app"' in printed and '"x5t": "abc"' in printed
    assert token not in printed and "do-not-log" not in printed


# --- the Terraform ---------------------------------------------------------------------------------

def test_the_load_balancer_is_internal_https_only_and_in_the_mcp_servers_group() -> None:
    lb = RESOURCES["aws_lb"]["mcp"]
    assert lb["internal"] is True and lb["load_balancer_type"] == "application"
    assert lb["security_groups"] == ['${aws_security_group.stand_in["mcp-servers"].id}']
    (listener,) = RESOURCES["aws_lb_listener"].values()
    assert (listener["port"], listener["protocol"]) == (443, "HTTPS")
    assert RESOURCES["aws_lb_target_group"]["mcp"]["target_type"] == "lambda"
    rule = RESOURCES["aws_vpc_security_group_ingress_rule"]["mcp_https"]
    assert (rule["from_port"], rule["to_port"], rule["cidr_ipv4"]) == (443, 443, "${local.cidr}")
    assert "vpc" in RESOURCES["aws_route53_zone"]["sandbox"]  # a private zone, this VPC's


def test_the_certificate_comes_from_the_sandbox_root_and_lives_two_days() -> None:
    cert = RESOURCES["tls_locally_signed_cert"]["mcp"]
    assert cert["ca_cert_pem"] == "${tls_self_signed_cert.root.cert_pem}"
    assert cert["validity_period_hours"] <= 48 and "server_auth" in cert["allowed_uses"]
    acm = RESOURCES["aws_acm_certificate"]["mcp"]
    assert acm["certificate_chain"] == "${tls_self_signed_cert.root.cert_pem}"
    assert "domain_name" not in acm  # imported, never requested from a public CA


def test_the_function_holds_its_log_and_nothing_else() -> None:
    function = RESOURCES["aws_lambda_function"]["mcp"]
    assert function["runtime"] == "python3.12" and function["handler"] == "handler.lambda_handler"
    assert RESOURCES["aws_cloudwatch_log_group"]["mcp"]["retention_in_days"] == 1
    assert set(RESOURCES["aws_iam_role_policy"]) >= {"mcp_logs"}
    assert "aws_iam_role_policy_attachment" not in {k for k, v in RESOURCES.items() if "mcp" in v} or \
        "mcp" not in RESOURCES.get("aws_iam_role_policy_attachment", {})
    assert not {"aws_internet_gateway", "aws_nat_gateway", "aws_eip"} & set(RESOURCES)


def test_every_group_and_rule_description_is_one_ec2_accepts() -> None:
    """EC2 takes a-zA-Z0-9, spaces and ._-:/()#,@[]+=&;{}!$* only; the stand-ins' first apply refused an apostrophe
    in a rule's description, as the lab's first apply had in a group's."""
    allowed = re.compile(r"^[a-zA-Z0-9. _\-:/()#,@\[\]+=&;{}!$*]{0,255}$")
    for kind in ("aws_security_group", "aws_vpc_security_group_ingress_rule", "aws_vpc_security_group_egress_rule"):
        for name, resource in RESOURCES.get(kind, {}).items():
            assert allowed.match(resource["description"]), f"{kind}.{name}"
