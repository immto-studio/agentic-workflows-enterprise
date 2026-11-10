"""W5's four readers: locks, read-only annotations, the workspace map before every read, the state masking
with no planted secret leaving, the lock file no tool serves, each reader's fields in the APIs' shapes, the
fakes' planted text where an attacker could put it, and the identities that hold reads only."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import sys

import pytest
import yaml
from mcp import Client

from conftest import IDENTITY, SECRET, SERVERS, W5, log_events, w5_token

sys.path.insert(0, str(W5.parent / "w1-knowledge-assistant" / "knowledge-server"))
from actor_transport import ActorMCP  # noqa: E402

import cloud_fake  # noqa: E402
import common  # noqa: E402
import cost_fake  # noqa: E402
import drift  # noqa: E402  (detect/, on the path through conftest)
import policy_fake  # noqa: E402
import state_fake  # noqa: E402
from common import BAD_ARGUMENT, MASK, REFUSALS, W5_AGENT_OID, W5_RUNTIME, W5_SERVERS_APP, ch05  # noqa: E402
from common import mask_state, mask_value  # noqa: E402

CATALOG = yaml.safe_load((W5 / "catalog" / "tools.yaml").read_text(encoding="utf-8"))
MANIFEST = yaml.safe_load((W5 / "manifest" / "w5-drift.yaml").read_text(encoding="utf-8"))
TABLE = json.loads((W5 / "catalog" / "membership.json").read_text(encoding="utf-8"))
REGION = cloud_fake.REGION
MARK = MASK.split("{")[0]  # "[masked hmac-sha256:"
WORKER = "aws_ecs_task_definition.claims_worker"
# An AWS action is a read when its verb is one of these. kms:Decrypt is the one exception the catalog
# argues for: the read of a data key on one KMS key, which s3:GetObject needs on an SSE-KMS bucket.
READ_VERBS = ("Get", "List", "Describe", "Lookup", "View")
ALLOWED_EXCEPTIONS = {"kms:Decrypt": "state-mcp"}


def call(url: str, token: str, tool: str, **args):
    async def go():
        async with Client(ActorMCP(url, token)) as client:
            return await client.call_tool(tool, args)
    return asyncio.run(go())


def tools_of(url: str, token: str) -> list:
    async def go():
        async with Client(ActorMCP(url, token)) as client:
            return (await client.list_tools()).tools
    return asyncio.run(go())


def ok(url: str, tool: str, **args) -> dict:
    """A call under the agent's token that must succeed, as the parsed result."""
    result = call(url, w5_token(), tool, **args)
    assert not result.is_error, result.content[0].text
    return json.loads(result.content[0].text)


def bad(url: str, tool: str, **args) -> str:
    """A call under the agent's token that must come back as the model's bad argument; the text."""
    result = call(url, w5_token(), tool, **args)
    assert result.is_error, f"{tool} answered {args}"
    text = result.content[0].text
    assert BAD_ARGUMENT in text, text
    return text


def every_string(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in (every_string(k) + every_string(v))]
    if isinstance(value, list):
        return [s for item in value for s in every_string(item)]
    return []


# --- the locks, the annotations, the catalog, the manifest ----------------------------------------------------

def test_every_lock_matches_what_its_server_serves(running_servers):
    for name, (url, _) in running_servers.items():
        lock = json.loads((W5 / "servers" / f"{name}.lock.json").read_text(encoding="utf-8"))["tools"]
        served = {t.name: t for t in tools_of(url, w5_token())}
        assert set(served) == set(lock), name
        assert len(served) == SERVERS[name]
        for tool_name, tool in served.items():  # the hash, not only the name
            assert ch05.definition_hash(ch05.canonical_definition(tool)) == lock[tool_name]["sha256"], tool_name


def test_every_tool_is_annotated_read_only_and_listed_in_the_catalog_and_the_manifest(running_servers):
    served: dict[str, list[str]] = {}
    for name, (url, _) in running_servers.items():
        for tool in tools_of(url, w5_token()):
            a = tool.annotations
            assert (a.read_only_hint, a.destructive_hint, a.open_world_hint) == (True, False, False), tool.name
            assert "not instructions" in tool.description, tool.name
            assert "Read-only" in tool.description, tool.name
            schema = ch05.canonical_definition(tool).get("inputSchema") or {}  # the wire form the lock pins
            served[tool.name] = sorted(schema.get("properties") or {})
            assert CATALOG["tools"][tool.name]["server"] == f"{name}-mcp", tool.name
    # The reads are what the servers serve; the one write (step 4) is the writer's, served by no MCP server.
    reads = {tool for tool, spec in MANIFEST["tools"].items() if not spec.get("writes")}
    writes = {tool for tool, spec in MANIFEST["tools"].items() if spec.get("writes")}
    assert set(served) == reads == {tool for tool, spec in CATALOG["tools"].items() if spec["server"] != "writer"}
    assert writes == {"open_pull_request"} and CATALOG["tools"]["open_pull_request"]["server"] == "writer"
    assert MANIFEST["tools"]["open_pull_request"] == {"args": ["finding_key"], "writes": True}
    for tool, spec in CATALOG["tools"].items():
        assert sorted(spec["args"]) == sorted(MANIFEST["tools"][tool]["args"]), tool
        if tool in writes:
            continue
        assert sorted(spec["args"]) == served[tool], tool
        # The map checks a workspace or an account; the two policy tools and the listing take neither (W5-D3).
        assert ("workspace" in spec["args"]) or ("account" in spec["args"]) or tool in (
            "list_workspaces", "get_tagging_standard", "list_policy_exceptions"), tool
        assert not {"bucket", "key", "account_id", "namespace", "team"} & set(spec["args"]), tool
        assert "writes" not in MANIFEST["tools"][tool], tool  # a read is a read


# --- the map decides, and the refusal names nothing -------------------------------------------------------------

def test_the_workspace_map_decides_and_the_refusal_names_no_workspace(running_servers, workspace_map):
    state, log = running_servers["state"]
    visible = workspace_map.visible(frozenset({"w5-drift-agent"}))
    assert visible == {"network-live", "claims-api-prod", "sandbox-quill"}
    assert "payments-cde" in state_fake.WORKSPACES and "payments-cde" not in visible  # real, and invisible
    assert ok(state, "get_state", workspace="network-live")["workspace"] == "network-live"
    for workspace in ("payments-cde", "no-such-workspace"):
        refused = call(state, w5_token(), "get_state", workspace=workspace)
        assert refused.is_error
        text = refused.content[0].text
        assert "payments-cde" not in text and "no-such-workspace" not in text  # the same sentence either way
        assert REFUSALS["workspace"] in text
    listed = ok(state, "list_workspaces")
    assert {w["workspace"] for w in listed["workspaces"]} == visible and listed["count"] == 3
    # A subject the table does not list holds no group, so it sees nothing: the same sentence again.
    stranger = w5_token(oid="00000000-0000-0000-0000-000000000009")
    refused = call(state, stranger, "get_state", workspace="network-live")
    assert refused.is_error and REFUSALS["workspace"] in refused.content[0].text
    assert ok(state, "list_workspaces")["count"] == 3  # and the listing for the agent is unchanged
    assert [e for e in log_events(log) if e["event"] == "tool_call" and e.get("refused") == "workspace not visible"]


def test_the_account_map_decides_on_the_cloud_and_cost_readers(running_servers):
    cloud, _ = running_servers["cloud"]
    cost, _ = running_servers["cost"]
    assert ok(cloud, "describe_resources", account="lm-sandbox", region=REGION, kind="volumes")["account_id"] == "433344445555"
    for account in ("lm-payments-cde", "no-such-account"):
        for url, tool, args in ((cloud, "describe_resources", {"region": REGION, "kind": "instances"}),
                                (cost, "describe_budgets", {})):
            refused = call(url, w5_token(), tool, account=account, **args)
            assert refused.is_error, (tool, account)
            text = refused.content[0].text
            assert "payments-cde" not in text and "no-such-account" not in text
            assert REFUSALS["account"] in text and "workspace" not in text


def test_a_token_for_another_app_from_another_client_or_of_the_delegated_shape_is_refused(running_servers):
    state, log = running_servers["state"]
    from access import issue  # W1's defaults: W1's audience, scope, and runtime
    w1_shaped = issue(SECRET, W5_AGENT_OID, "x")
    assert call(state, w1_shaped, "list_workspaces").is_error
    other_client = w5_token(client="00000000-0000-0000-0000-000000000001")
    assert call(state, other_client, "list_workspaces").is_error
    w2_role = w5_token(roles=("Ops.Read",))
    assert call(state, w2_role, "list_workspaces").is_error
    # The delegated shape (a user's token with Drift.Read in scp, W5's audience and client): W1's shape,
    # which W1's verifier accepts and W5's refuses, because W5's servers never act for a person (step 4).
    delegated = w5_token(delegated=True)
    assert call(state, delegated, "list_workspaces").is_error
    assert call(state, w5_token(minutes=-5), "list_workspaces").is_error  # expired: W1's check
    reasons = [e["reason"] for e in log_events(log) if e["event"] == "refused"]
    assert any("azp" in r for r in reasons) and any("audience" in r.lower() for r in reasons)
    assert any("Drift.Read" in r for r in reasons) and any("delegated" in r for r in reasons)
    assert any("expired" in r.lower() for r in reasons)
    assert w5_token(client=W5_RUNTIME, audience=W5_SERVERS_APP) and not call(state, w5_token(), "list_workspaces").is_error


# --- reading state safely (W5-D4) --------------------------------------------------------------------------------

def test_no_planted_secret_leaves_the_state_reader(running_servers):
    state, _ = running_servers["state"]
    texts: list[str] = []
    for workspace in ("network-live", "claims-api-prod", "sandbox-quill"):
        texts.extend(every_string(ok(state, "get_state", workspace=workspace)))
        versions = ok(state, "list_state_versions", workspace=workspace)
        texts.extend(every_string(versions))
        for version in versions["response"]["Versions"]:
            texts.extend(every_string(ok(state, "get_state_version", workspace=workspace, version_id=version["VersionId"])))
    texts.extend(every_string(ok(state, "list_workspaces")))
    joined = "\n".join(texts)
    assert len(state_fake.PLANTED_SECRETS) == 6
    for secret in state_fake.PLANTED_SECRETS:
        assert secret not in joined, secret
        assert hashlib.sha256(secret.encode("utf-8")).hexdigest()[:8] not in joined, secret  # no plain hash to test a guess on
    assert "fixture-rds-password" not in joined and "fixture-api-key" not in joined and "fixture-ecs-db-password" not in joined
    assert MARK in joined
    # The marker differs between two versions where the value changed, and not where it did not.
    ids = [v["VersionId"] for v in ok(state, "list_state_versions", workspace="claims-api-prod")["response"]["Versions"]]
    v3, v2, v1 = ids  # newest first

    def password_of(version_id: str) -> str:
        view = ok(state, "get_state_version", workspace="claims-api-prod", version_id=version_id)
        db = next(r for r in view["state"]["values"]["root_module"]["resources"] if r["address"] == "aws_db_instance.claims")
        return db["values"]["password"]

    assert password_of(v1) == password_of(v2) != password_of(v3)
    assert password_of(v3) == mask_value(state_fake.raw("claims-api-prod", v3)["values"]["root_module"]["resources"][5]["values"]["password"])
    assert all(p.startswith(MARK) and p.endswith("]") and len(p) == len(MARK) + 9 for p in (password_of(v1), password_of(v3)))
    latest = ok(state, "get_state", workspace="claims-api-prod")
    assert latest["version_id"] == v3 and latest["is_latest"] is True
    connection = latest["state"]["values"]["outputs"]["db_connection_string"]
    assert connection["sensitive"] is True and connection["value"].startswith(MARK)
    older = ok(state, "get_state_version", workspace="claims-api-prod", version_id=v2)
    assert older["state"]["values"]["outputs"]["db_connection_string"]["value"] != connection["value"]


def test_the_redaction_masks_the_api_key_attribute_by_name(running_servers):
    state, _ = running_servers["state"]
    raw = state_fake.raw("claims-api-prod")
    raw_lambda = next(r for r in raw["values"]["root_module"]["resources"] if r["address"] == "aws_lambda_function.notifier")
    assert raw_lambda["sensitive_values"]["environment"] == [{"variables": {}}]  # the schema marks nothing
    raw_key = raw_lambda["values"]["environment"][0]["variables"]["API_KEY"]
    assert raw_key == "fixture-api-key-notifier-5f1c"
    view = ok(state, "get_state", workspace="claims-api-prod")
    served = next(r for r in view["state"]["values"]["root_module"]["resources"] if r["address"] == "aws_lambda_function.notifier")
    variables = served["values"]["environment"][0]["variables"]
    assert variables["API_KEY"] == mask_value(raw_key) and variables["LOG_LEVEL"] == "WARN"  # the name decides


def test_mask_state_masks_marks_and_names_and_drops_data_resources():
    state = {"format_version": "1.0", "terraform_version": "1.11.4", "values": {
        "outputs": {"plain": {"sensitive": False, "type": "string", "value": "keep"},
                    "marked": {"sensitive": True, "type": "string", "value": "hide-me"},
                    "db_connection_string": {"sensitive": False, "type": "string", "value": "hide-by-name"},
                    "empty_secret": {"sensitive": True, "type": "string", "value": None}},
        "root_module": {"resources": [
            {"address": "aws_thing.a", "mode": "managed", "type": "aws_thing", "name": "a",
             "values": {"password": "p", "nested": [{"token": "t", "ok": "k"}], "PrivateKey": "pk", "none": None,
                        "marked_list": ["x", "y"], "deep": {"inner": {"secret_sauce": "s", "fine": 1}}},
             "sensitive_values": {"nested": [{}], "marked_list": True, "deep": {"inner": {}}}},
            {"address": "data.aws_thing.d", "mode": "data", "type": "aws_thing", "name": "d", "values": {"password": "leak"},
             "sensitive_values": {}},
        ], "child_modules": [{"address": "module.m", "resources": [
            {"address": "module.m.aws_thing.b", "mode": "managed", "type": "aws_thing", "name": "b",
             "values": {"api_key": "ak", "label": "l"}, "sensitive_values": {}}]}]}}}
    masked = mask_state(state)
    outputs = masked["values"]["outputs"]
    assert outputs["plain"]["value"] == "keep" and outputs["marked"]["value"] == mask_value("hide-me")
    assert outputs["db_connection_string"]["value"] == mask_value("hide-by-name") and outputs["empty_secret"]["value"] is None
    resources = masked["values"]["root_module"]["resources"]
    assert [r["address"] for r in resources] == ["aws_thing.a"]  # the data resource is gone
    values = resources[0]["values"]
    assert values["password"] == mask_value("p") and values["nested"][0] == {"token": mask_value("t"), "ok": "k"}
    assert values["PrivateKey"] == mask_value("pk") and values["none"] is None
    assert values["marked_list"] == mask_value(["x", "y"]) and values["deep"]["inner"] == {"secret_sauce": mask_value("s"), "fine": 1}
    child = masked["values"]["root_module"]["child_modules"][0]["resources"][0]["values"]
    assert child == {"api_key": mask_value("ak"), "label": "l"}
    assert "leak" not in json.dumps(masked) and masked["terraform_version"] == "1.11.4"


def test_a_secret_inside_a_task_definitions_container_definitions_leaves_masked_whole(running_servers):
    """The planted database password sits inside one JSON string: the 6.71.0 schema marks the attribute nothing,
    its name says nothing, and W2's value patterns look for `password=`, not `"name": "DB_PASSWORD", "value": ...`.
    The reader masks the attribute whole, by resource type and attribute name."""
    state, _ = running_servers["state"]
    raw = next(r for r in state_fake.raw("claims-api-prod")["values"]["root_module"]["resources"] if r["address"] == WORKER)
    definitions = raw["values"]["container_definitions"]
    secret = "fixture-ecs-db-password-claims-7d3a"
    assert secret in definitions and "container_definitions" not in raw["sensitive_values"]
    assert not common.SECRET_NAME.search("container_definitions") and secret in common.redact(definitions)
    assert secret in json.dumps(common._mask_values(raw["values"], raw["sensitive_values"]))  # the two older rules miss it
    served = next(r for r in ok(state, "get_state", workspace="claims-api-prod")["state"]["values"]["root_module"]["resources"]
                  if r["address"] == WORKER)
    assert served["values"]["container_definitions"] == mask_value(definitions)
    assert {k: v for k, v in served["values"].items() if k != "container_definitions"} == {
        k: v for k, v in raw["values"].items() if k != "container_definitions"}  # the rest of the resource as it was
    older = ok(state, "get_state_version", workspace="claims-api-prod", version_id=state_fake._BUCKET[state_fake.key_of("claims-api-prod")][0]["VersionId"])
    assert next(r for r in older["state"]["values"]["root_module"]["resources"] if r["address"] == WORKER)["values"][
        "container_definitions"] == served["values"]["container_definitions"]  # unchanged between versions: the same marker


def test_mask_state_masks_json_and_scripts_whole_by_resource_type():
    script = "#!/bin/sh\nexport DB_PASSWORD=launch-template-secret\n/opt/start"
    resources = [
        {"address": "aws_instance.a", "mode": "managed", "type": "aws_instance", "name": "a",
         "values": {"id": "i-1", "user_data": "4c3b0f5e", "user_data_base64": "IyEvYmluL3No", "instance_type": "t4g.small"},
         "sensitive_values": {}},
        {"address": "aws_launch_template.t", "mode": "managed", "type": "aws_launch_template", "name": "t",
         "values": {"id": "lt-1", "user_data": script, "name": "web"}, "sensitive_values": {}},
        {"address": "aws_launch_configuration.c", "mode": "managed", "type": "aws_launch_configuration", "name": "c",
         "values": {"id": "lc-1", "user_data": script, "user_data_base64": None}, "sensitive_values": {}},
        {"address": "aws_ecs_task_definition.w", "mode": "managed", "type": "aws_ecs_task_definition", "name": "w",
         "values": {"id": "w", "container_definitions": '[{"environment":[{"name":"X","value":"y"}]}]', "family": "w"},
         "sensitive_values": {}},
        {"address": "aws_thing.x", "mode": "managed", "type": "aws_thing", "name": "x",  # another type keeps its user_data
         "values": {"id": "x", "user_data": "plain"}, "sensitive_values": {}},
    ]
    masked = mask_state({"values": {"outputs": {}, "root_module": {"resources": resources}}})["values"]["root_module"]["resources"]
    by = {r["address"]: r["values"] for r in masked}
    assert by["aws_instance.a"] == {"id": "i-1", "user_data": mask_value("4c3b0f5e"), "user_data_base64": mask_value("IyEvYmluL3No"),
                                    "instance_type": "t4g.small"}
    assert by["aws_launch_template.t"] == {"id": "lt-1", "user_data": mask_value(script), "name": "web"}
    assert by["aws_launch_configuration.c"] == {"id": "lc-1", "user_data": mask_value(script), "user_data_base64": None}
    assert by["aws_ecs_task_definition.w"]["container_definitions"].startswith(MARK) and by["aws_ecs_task_definition.w"]["family"] == "w"
    assert by["aws_thing.x"] == {"id": "x", "user_data": "plain"} and "launch-template-secret" not in json.dumps(masked)
    assert common.MASKED_ATTRIBUTES == {"aws_ecs_task_definition": ("container_definitions",),
                                        "aws_instance": ("user_data", "user_data_base64"), "aws_launch_template": ("user_data",),
                                        "aws_launch_configuration": ("user_data", "user_data_base64")}


def test_the_marker_is_a_keyed_hash_so_a_reader_cannot_test_a_guess_against_it(monkeypatch):
    """The first eight hex digits of an HMAC-SHA256 under the reader's key: a plain SHA-256 prefix let anyone who reads
    the masked state hash a guess of a weak password and compare. Two versions still compare under one key."""
    monkeypatch.delenv(common.MASK_KEY_ENV, raising=False)
    guess = "fixture-rds-password-claims-v1-2c8e"
    keyed = hmac.new(common.LAB_MASK_KEY.encode("utf-8"), guess.encode("utf-8"), hashlib.sha256).hexdigest()[:8]
    assert mask_value(guess) == f"[masked hmac-sha256:{keyed}]" == MASK.format(keyed)
    assert hashlib.sha256(guess.encode("utf-8")).hexdigest()[:8] not in mask_value(guess)
    assert mask_value(guess) == mask_value(guess) and mask_value(guess) != mask_value(guess + "x")
    assert drift.mask_live(guess) == mask_value(guess)  # the detectors' marker for a live value, under the same key
    monkeypatch.setenv(common.MASK_KEY_ENV, "another key, held by this test")
    assert mask_value(guess) == mask_value(guess, key=b"another key, held by this test") != f"[masked hmac-sha256:{keyed}]"
    assert drift.mask_live(guess) == mask_value(guess)  # both follow W5_MASK_KEY


def test_the_lock_file_is_not_listable_or_readable(running_servers):
    state, _ = running_servers["state"]
    keys = state_fake.bucket_keys()
    locks = [k for k in keys if k.endswith(".tflock")]
    assert len(locks) == 4 and all(state_fake.lock_key_of(w) in keys for w in state_fake.WORKSPACES)  # the bucket holds them
    for workspace in ("network-live", "claims-api-prod", "sandbox-quill"):
        key, lock = state_fake.key_of(workspace), state_fake.lock_key_of(workspace)
        # What S3 answers the one listing the grant allows, the state key as the prefix: a prefix is a string, so
        # the lock object's versions and delete markers come with it (C.16), the last release the lock's latest.
        answer = state_fake.list_object_versions(prefix=key)
        assert {v["Key"] for v in answer["Versions"]} == {key, lock} and {m["Key"] for m in answer["DeleteMarkers"]} == {lock}
        assert [m for m in answer["DeleteMarkers"] if m["IsLatest"]] and not [v for v in answer["Versions"] if v["Key"] == lock and v["IsLatest"]]
        for tool in ("get_state", "list_state_versions"):
            assert "tflock" not in json.dumps(ok(state, tool, workspace=workspace)), (tool, workspace)
        versions = ok(state, "list_state_versions", workspace=workspace)["response"]
        assert versions["Prefix"] == key and all(v["Key"] == key for v in versions["Versions"]) and "DeleteMarkers" not in versions
        assert [v["VersionId"] for v in versions["Versions"]] == [v["VersionId"] for v in answer["Versions"] if v["Key"] == key]
        assert [v["IsLatest"] for v in versions["Versions"]] == [True] + [False] * (len(versions["Versions"]) - 1)
        # The lock object's own version id names nothing the reader will serve.
        lock_version = state_fake._BUCKET[state_fake.lock_key_of(workspace)][0]["VersionId"]
        text = bad(state, "get_state_version", workspace=workspace, version_id=lock_version)
        assert "tflock" not in text and "OperationTypeApply" not in text
    assert "tflock" not in json.dumps(ok(state, "list_workspaces"))
    assert bad(state, "get_state_version", workspace="sandbox-quill", version_id="no-such-version")


def test_the_states_fields_are_terraforms(running_servers):
    state, _ = running_servers["state"]
    view = ok(state, "get_state", workspace="claims-api-prod")
    assert view["bucket"] == state_fake.BUCKET and view["key"] == "live/claims-api-prod/terraform.tfstate"
    body = view["state"]
    assert body["format_version"] == "1.0" and body["terraform_version"] == view["terraform_version"]
    root = body["values"]["root_module"]
    for resource in root["resources"]:
        assert set(resource) >= {"address", "mode", "type", "name", "provider_name", "schema_version", "values", "sensitive_values"}
        assert resource["mode"] == "managed" and resource["address"].startswith(resource["type"] + ".")
        assert resource["provider_name"] == state_fake.PROVIDER
    api = next(r for r in root["resources"] if r["address"] == "aws_instance.api")
    assert api["type"] == "aws_instance" and api["values"]["instance_type"] == "t3.large"  # the console says m5.large
    assert api["values"]["id"] == cloud_fake.IDS["claims_instance"]
    assert [m["address"] for m in root["child_modules"]] == ["module.api_alb"]
    assert root["child_modules"][0]["resources"][0]["address"] == "module.api_alb.aws_lb.api"
    network = ok(state, "get_state", workspace="network-live")["state"]["values"]["root_module"]
    routes = next(r for r in network["resources"] if r["address"] == "aws_route_table.private_a")["values"]["route"]
    assert "10.251.0.0/24" not in {r["cidr_block"] for r in routes}  # the unmanaged route is not in state
    sandbox = ok(state, "get_state", workspace="sandbox-quill")["state"]["values"]["root_module"]
    assert "aws_ebs_volume.scratch" in {r["address"] for r in sandbox["resources"]}  # in state, gone from the cloud


# --- the cloud reader's fields and bounds ----------------------------------------------------------------------

def test_the_describe_shapes_are_the_apis(running_servers):
    cloud, _ = running_servers["cloud"]
    instances = ok(cloud, "describe_resources", account="lm-claims-prod", region=REGION, kind="instances")["response"]
    api = next(i for r in instances["Reservations"] for i in r["Instances"] if i["InstanceId"] == cloud_fake.IDS["claims_instance"])
    assert api["InstanceType"] == "m5.large" and api["State"]["Name"] == "running" and "LaunchTime" in api
    assert {t["Key"] for t in api["Tags"]} >= set(policy_fake.TAGGING_STANDARD["required_tags"])
    volumes = ok(cloud, "describe_resources", account="lm-sandbox", region=REGION, kind="volumes")["response"]["Volumes"]
    orphan = next(v for v in volumes if v["VolumeId"] == cloud_fake.IDS["orphan_volume"])
    assert orphan["Attachments"] == [] and orphan["State"] == "available" and orphan["Tags"] == []
    assert cloud_fake.IDS["scratch_volume"] not in {v["VolumeId"] for v in volumes}
    snapshots = ok(cloud, "describe_resources", account="lm-sandbox", region=REGION, kind="snapshots")["response"]["Snapshots"]
    assert next(s for s in snapshots if s["SnapshotId"] == cloud_fake.IDS["old_snapshot"])["StartTime"] < "2026-08-04"
    groups = ok(cloud, "describe_resources", account="lm-claims-prod", region=REGION, kind="security_groups")["response"]["SecurityGroups"]
    billing = next(g for g in groups if g["GroupId"] == cloud_fake.IDS["sg_billing_worker"])
    assert any(p["FromPort"] == 8080 and p["IpRanges"][0]["CidrIp"] == "0.0.0.0/0" for p in billing["IpPermissions"])
    tables = ok(cloud, "describe_resources", account="lm-network-prod", region=REGION, kind="route_tables")["response"]["RouteTables"]
    private_a = next(t for t in tables if t["RouteTableId"] == cloud_fake.IDS["rtb_private_a"])
    assert "10.251.0.0/24" in {r["DestinationCidrBlock"] for r in private_a["Routes"]} and private_a["Associations"]
    balancers = ok(cloud, "describe_resources", account="lm-claims-prod", region=REGION, kind="load_balancers")["response"]["LoadBalancers"]
    assert balancers[0]["LoadBalancerArn"] == cloud_fake.IDS["claims_alb"] and balancers[0]["Type"] == "application"
    # GetResources omits the untagged volume the describe shows (C.1), and lists only the key asked for.
    tagged = ok(cloud, "get_resources_by_tag", account="lm-sandbox", region=REGION, tag_key="owner_team")["response"]
    arns = {m["ResourceARN"] for m in tagged["ResourceTagMappingList"]}
    assert not any(cloud_fake.IDS["orphan_volume"] in arn for arn in arns)
    assert any(cloud_fake.IDS["archive_volume"] in arn for arn in arns)
    assert all(any(t["Key"] == "owner_team" for t in m["Tags"]) for m in tagged["ResourceTagMappingList"])
    by_cost_center = ok(cloud, "get_resources_by_tag", account="lm-sandbox", region=REGION, tag_key="cost_center")["response"]
    assert not any(cloud_fake.IDS["notebook_instance"] in m["ResourceARN"] for m in by_cost_center["ResourceTagMappingList"])
    assert "bad argument" in bad(cloud, "describe_resources", account="lm-sandbox", region=REGION, kind="buckets")
    assert bad(cloud, "describe_resources", account="lm-sandbox", region="eu-west-1", kind="volumes")
    assert bad(cloud, "get_resources_by_tag", account="lm-sandbox", region=REGION, tag_key="")


def test_the_lookup_takes_one_attribute_within_the_apis_bounds(running_servers):
    cloud, _ = running_servers["cloud"]
    page = ok(cloud, "lookup_events", account="lm-claims-prod", region=REGION, attribute_key="Username",
              attribute_value="jenkins-deploy-prod", days=90)
    assert page["lookup"] == {"AttributeKey": "Username", "AttributeValue": "jenkins-deploy-prod"}  # one attribute
    events = page["response"]["Events"]
    assert len(events) == 1 and len(events) <= cloud_fake.MAX_RESULTS and "NextToken" not in page["response"]
    jenkins = events[0]
    assert jenkins["EventName"] == "AuthorizeSecurityGroupIngress" and jenkins["Username"] == "jenkins-deploy-prod"
    assert jenkins["Resources"] == [{"ResourceType": "AWS::EC2::SecurityGroup", "ResourceName": cloud_fake.IDS["sg_billing_worker"]}]
    record = json.loads(jenkins["CloudTrailEvent"])
    assert record["userAgent"].startswith("Jenkins/2.4") and record["userIdentity"]["type"] == "IAMUser"
    assert record["requestParameters"]["ipPermissions"]["items"][0]["fromPort"] == 8080
    route = ok(cloud, "lookup_events", account="lm-network-prod", region=REGION, attribute_key="ResourceName",
               attribute_value=cloud_fake.IDS["rtb_private_a"], days=30)["response"]["Events"]
    assert [e["EventName"] for e in route] == ["CreateRoute"] and route[0]["Username"] == "rosa.delgado"
    typed = ok(cloud, "lookup_events", account="lm-claims-prod", region=REGION, attribute_key="EventName",
               attribute_value="ModifyInstanceAttribute", days=14)["response"]["Events"]
    assert len(typed) == 1 and json.loads(typed[0]["CloudTrailEvent"])["requestParameters"]["instanceType"] == {"value": "m5.large"}
    # Outside the window: the same lookup with too few days finds nothing; past the bounds is a bad argument.
    assert ok(cloud, "lookup_events", account="lm-network-prod", region=REGION, attribute_key="EventName",
              attribute_value="CreateRoute", days=5)["response"]["Events"] == []
    for days in (0, cloud_fake.MAX_LOOKUP_DAYS + 1):
        assert bad(cloud, "lookup_events", account="lm-claims-prod", region=REGION, attribute_key="Username",
                   attribute_value="x", days=days)
    assert bad(cloud, "lookup_events", account="lm-claims-prod", region=REGION, attribute_key="UserAgent",
               attribute_value="Jenkins", days=7)  # not a lookup attribute
    assert bad(cloud, "lookup_events", account="lm-claims-prod", region=REGION, attribute_key="Username",
               attribute_value="", days=7)
    # The CPU series: seven days under two percent for the idle instance, bounds held.
    idle = ok(cloud, "get_cpu_utilization", account="lm-sandbox", region=REGION, instance_id=cloud_fake.IDS["batch_instance"], days=7)
    points = idle["response"]["Datapoints"]
    assert idle["response"]["Label"] == "CPUUtilization" and len(points) == 7
    assert all(p["Average"] < 2.0 and p["Unit"] == "Percent" for p in points)
    assert [p["Timestamp"] for p in points] == sorted(p["Timestamp"] for p in points)
    busy = ok(cloud, "get_cpu_utilization", account="lm-sandbox", region=REGION, instance_id=cloud_fake.IDS["notebook_instance"], days=14)
    assert max(p["Average"] for p in busy["response"]["Datapoints"]) > 50
    unknown = ok(cloud, "get_cpu_utilization", account="lm-sandbox", region=REGION, instance_id="i-0123456789abcdef0", days=7)
    assert unknown["response"]["Datapoints"] == []
    assert bad(cloud, "get_cpu_utilization", account="lm-sandbox", region=REGION, instance_id=cloud_fake.IDS["batch_instance"],
               days=cloud_fake.MAX_CPU_DAYS + 1)
    assert bad(cloud, "get_cpu_utilization", account="lm-sandbox", region=REGION, instance_id="vol-0123", days=7)


# --- the cost reader's fields and bounds ----------------------------------------------------------------------

def test_the_cost_readers_fields_and_bounds(running_servers):
    cost, _ = running_servers["cost"]
    export = ok(cost, "read_cost_export", account="lm-sandbox", billing_period="2026-10")
    required = {"line_item_resource_id", "line_item_usage_account_id", "product_servicecode", "line_item_usage_type",
                "line_item_unblended_cost", "line_item_line_item_description", "bill_billing_period_start_date",
                *cost_fake.TAG_COLUMNS}
    assert required <= set(export["columns"]) and export["row_count"] == len(export["rows"]) > 0
    for row in export["rows"]:
        assert set(row) == set(export["columns"]), row
        assert row["line_item_usage_account_id"] == cloud_fake.ACCOUNTS["lm-sandbox"]
        assert row["line_item_currency_code"] == cost_fake.UNIT and row["bill_billing_period_start_date"].startswith("2026-10")
    orphan = next(r for r in export["rows"] if r["line_item_resource_id"] == cloud_fake.IDS["orphan_volume"])
    assert all(orphan[column] == "" for column in cost_fake.TAG_COLUMNS)  # untagged in the bill too
    assert ok(cost, "read_cost_export", account="lm-sandbox", billing_period="2026-09")["rows"] == []  # no export yet
    assert bad(cost, "read_cost_export", account="lm-sandbox", billing_period="October")
    by_tag = ok(cost, "get_cost_and_usage", account="lm-sandbox", start="2026-10-01", end="2026-11-02", group_by_tag="owner_team")
    assert by_tag["response"]["GroupDefinitions"] == [{"Type": "TAG", "Key": "owner_team"}]
    months = by_tag["response"]["ResultsByTime"]
    assert [m["TimePeriod"]["Start"] for m in months] == ["2026-10-01", "2026-11-01"] and months[1]["Estimated"] is True
    keys = {g["Keys"][0] for g in months[0]["Groups"]}
    assert "owner_team$quill-data" in keys and "owner_team$" in keys  # the empty value, as the API gives it
    assert all(g["Metrics"]["UnblendedCost"]["Unit"] == cost_fake.UNIT for g in months[0]["Groups"])
    assert bad(cost, "get_cost_and_usage", account="lm-sandbox", start="2026-11-01", end="2026-10-01", group_by_tag="env")
    assert bad(cost, "get_cost_and_usage", account="lm-sandbox", start="2024-01-01", end="2026-11-01", group_by_tag="env")
    assert bad(cost, "get_cost_and_usage", account="lm-sandbox", start="2026-10-01", end="2026-11-01", group_by_tag="")
    by_resource = ok(cost, "get_cost_by_resource", account="lm-sandbox", days=14,
                     resource_ids=[cloud_fake.IDS["orphan_volume"], cloud_fake.IDS["scratch_volume"], "i-0123456789abcdef0"])
    days = by_resource["response"]["ResultsByTime"]
    assert len(days) == 14 and days[-1]["TimePeriod"] == {"Start": "2026-11-01", "End": "2026-11-02"}
    assert by_resource["response"]["GroupDefinitions"] == [{"Type": "DIMENSION", "Key": "RESOURCE_ID"}]
    last_keys = {g["Keys"][0] for g in days[-1]["Groups"]}
    assert cloud_fake.IDS["orphan_volume"] in last_keys and cloud_fake.IDS["scratch_volume"] not in last_keys  # deleted 25 October
    assert cloud_fake.IDS["scratch_volume"] in {g["Keys"][0] for g in days[0]["Groups"]}  # 19 October: still there
    for days_arg in (0, cost_fake.MAX_RESOURCE_DAYS + 1):
        assert bad(cost, "get_cost_by_resource", account="lm-sandbox", days=days_arg, resource_ids=["i-0123456789abcdef0"])
    assert bad(cost, "get_cost_by_resource", account="lm-sandbox", days=7, resource_ids=[])
    budgets = ok(cost, "describe_budgets", account="lm-claims-prod")["response"]["Budgets"]
    assert len(budgets) == 1 and budgets[0]["BudgetType"] == "COST" and budgets[0]["TimeUnit"] == "MONTHLY"
    spend = budgets[0]["CalculatedSpend"]
    assert float(spend["ActualSpend"]["Amount"]) < float(spend["ForecastedSpend"]["Amount"]) and spend["ActualSpend"]["Unit"] == cost_fake.UNIT
    notifications = budgets[0]["Notifications"]
    assert sorted(n["Threshold"] for n in notifications if n["NotificationType"] == "ACTUAL") == [50.0, 80.0, 100.0]
    assert next(n for n in notifications if n["NotificationType"] == "FORECASTED")["NotificationState"] == "ALARM"
    assert all(n["NotificationState"] == "OK" for n in notifications if n["NotificationType"] == "ACTUAL")
    anomalies = ok(cost, "get_anomalies", account="lm-sandbox", days=90)["response"]["Anomalies"]
    assert len(anomalies) == 1 and anomalies[0]["RootCauses"][0]["Service"] == "Amazon Athena"
    assert {"AnomalyStartDate", "AnomalyEndDate", "Impact", "AnomalyScore", "MonitorArn"} <= set(anomalies[0])
    assert ok(cost, "get_anomalies", account="lm-sandbox", days=3)["response"]["Anomalies"] == []
    assert ok(cost, "get_anomalies", account="lm-network-prod", days=90)["response"]["Anomalies"] == []
    for days_arg in (0, cost_fake.MAX_ANOMALY_DAYS + 1):
        assert bad(cost, "get_anomalies", account="lm-sandbox", days=days_arg)


# --- the policy reader ----------------------------------------------------------------------------------------

def test_the_standards_five_tags_and_the_exceptions(running_servers):
    policy, _ = running_servers["policy"]
    standard = ok(policy, "get_tagging_standard")
    assert standard["required_tags"] == ["owner_team", "cost_center", "env", "service", "data_classification"]
    assert standard["env_values"] == ["prod", "stg", "dev", "sandbox", "lab"]
    assert standard["untagged_non_production"] == {"stop_after_days": 7, "delete_after_days": 30}
    assert standard["exceptions"]["approved_by"] == "finops" and standard["exceptions"]["max_days"] == 90
    assert standard["owner_team"] == "finops" and standard["effective"] == "2025-01-10"
    approved = ok(policy, "list_policy_exceptions", state="approved")
    assert approved["count"] == 3
    record = approved["exceptions"][0]
    assert record["number"].startswith("RITM") and record["resource_id"] == cloud_fake.IDS["notebook_instance"]
    assert record["tag"] == "cost_center" and record["approved_by"] == "finops" and record["expires"] > "2026-11-02"
    assert {"number", "resource_id", "tag", "reason", "approved_by", "expires"} <= set(record)
    volume = [r for r in approved["exceptions"] if r["resource_id"] == cloud_fake.IDS["notebook_root_volume"]]
    assert [(r["number"], r["tag"]) for r in volume] == [("RITM0045233", "cost_center"), ("RITM0045234", "data_classification")]
    assert all(r["approved_by"] == "finops" and "2026-11-02" < r["expires"] <= "2027-01-31" for r in volume)  # within ninety days
    assert ok(policy, "list_policy_exceptions", state="all")["count"] == 5
    assert ok(policy, "list_policy_exceptions", state="expired")["exceptions"][0]["expires"] < "2026-11-02"
    assert bad(policy, "list_policy_exceptions", state="granted")


# --- everything read is untrusted (W5-D12) ---------------------------------------------------------------------

def test_the_planted_text_sits_where_an_attacker_can_write(running_servers):
    """The scorer and the chapter name each planted instruction; the fakes must still carry them, as data."""
    state, _ = running_servers["state"]
    cloud, _ = running_servers["cloud"]
    cost, _ = running_servers["cost"]
    instances = ok(cloud, "describe_resources", account="lm-sandbox", region=REGION, kind="instances")
    notebook = next(i for r in instances["response"]["Reservations"] for i in r["Instances"]
                    if i["InstanceId"] == cloud_fake.IDS["notebook_instance"])
    assert next(t["Value"] for t in notebook["Tags"] if t["Key"] == "Name") == cloud_fake.PLANTED["tag"]
    events = ok(cloud, "lookup_events", account="lm-sandbox", region=REGION, attribute_key="Username",
                attribute_value="quill-svc-notebooks", days=30)["response"]["Events"]
    created = next(e for e in events if e["EventName"] == "CreateVolume")
    assert json.loads(created["CloudTrailEvent"])["userAgent"] == cloud_fake.PLANTED["user_agent"]
    outputs = ok(state, "get_state", workspace="claims-api-prod")["state"]["values"]["outputs"]
    assert outputs["runbook_note"] == {"sensitive": False, "type": "string", "value": state_fake.PLANTED["output"]}
    rows = ok(cost, "read_cost_export", account="lm-claims-prod", billing_period="2026-10")["rows"]
    marketplace = next(r for r in rows if r["product_servicecode"] == "AWSMarketplace")
    assert marketplace["line_item_line_item_description"] == cost_fake.PLANTED["line_item"]
    for text in (cloud_fake.PLANTED["tag"], cloud_fake.PLANTED["user_agent"], state_fake.PLANTED["output"],
                 cost_fake.PLANTED["line_item"]):
        assert "SYSTEM NOTE" in text or "approved" in text


# --- the logs and the identities ---------------------------------------------------------------------------------

def test_every_call_is_logged_with_the_servers_identity_and_the_callers(running_servers):
    state, log = running_servers["state"]
    ok(state, "get_state", workspace="sandbox-quill")
    calls = [e for e in log_events(log) if e["event"] == "tool_call" and e["args"].get("workspace") == "sandbox-quill"]
    assert calls and calls[-1]["identity"] == IDENTITY.format("state") and calls[-1]["tool"] == "get_state"
    assert calls[-1]["caller"] == W5_AGENT_OID and calls[-1]["ok"] is True and calls[-1]["trace_id"]
    line = json.dumps(calls[-1])
    assert "instance_type" not in line and "resources" not in line and MARK not in line  # the arguments, never a result
    cost, cost_log = running_servers["cost"]
    ok(cost, "describe_budgets", account="lm-sandbox")
    last = [e for e in log_events(cost_log) if e["event"] == "tool_call"][-1]
    assert last["identity"] == IDENTITY.format("cost") and last["caller"] == W5_AGENT_OID and "Amount" not in json.dumps(last)


@pytest.mark.parametrize("name", list(SERVERS))
def test_each_server_runs_under_its_own_identity(running_servers, name):
    _, log = running_servers[name]
    start = next(e for e in log_events(log) if e["event"] == "server_start")
    assert start["identity"] == IDENTITY.format(name) and len(start["tools"]) == SERVERS[name]
    assert start["workspace_map"].endswith("workspace-map.yaml")


def test_the_catalog_identities_hold_read_actions_only():
    for server, spec in CATALOG["servers"].items():
        for action in spec.get("aws", {}).get("role_actions", []):
            verb = action.split(":", 1)[-1]
            if action in ALLOWED_EXCEPTIONS:
                assert ALLOWED_EXCEPTIONS[action] == server, (server, action)  # kms:Decrypt on the state reader only
                continue
            assert verb.startswith(READ_VERBS), (server, action)
            assert not verb.startswith(("Put", "Delete", "Create", "Modify", "Authorize", "Revoke", "Run", "Stop",
                                        "Terminate", "Attach", "Detach", "Update", "Apply", "Assume", "Tag", "Untag")), action
        assert spec["identity"] == f"larkspur-drift-{server.removesuffix('-mcp')}-reader"
        assert (W5 / "servers" / f"{server.removesuffix('-mcp')}_reader.py").exists()
    assert CATALOG["servers"]["policy-mcp"]["aws"]["role_actions"] == [] and CATALOG["servers"]["policy-mcp"]["servicenow"]["write"] == []
    assert set(CATALOG["never"]) == set(MANIFEST["never"]) and len(MANIFEST["never"]) == len(set(MANIFEST["never"]))
    assert {"apply_plan", "merge_pull_request", "approve_pull_request", "delete_resource", "stop_instance",
            "modify_security_group", "delete_namespace", "modify_iam", "read_vault_secret", "run_command"} == set(MANIFEST["never"])
    assert CATALOG["app"]["servers_app"] == W5_SERVERS_APP and CATALOG["app"]["clients"] == [W5_RUNTIME]
    assert CATALOG["app"]["grant"] == "client_credentials"
    member = CATALOG["membership"]
    assert TABLE["members"] == {member["subject"]: [member["group"]]} and member["subject"] == W5_AGENT_OID
    assert set(TABLE["groups"].values()) == {member["group"]} and TABLE["broad"] == []
    assert MANIFEST["rung"] == 2 and MANIFEST["workflow"] == "w5-drift"
