"""The harness image for Amazon Bedrock AgentCore Runtime: its Dockerfile, AgentCore's routes end to
end, the gateway key from the token vault, MCP requests signed for the tool gateway, and runtime.tf
setting what the entry point reads.

Chapter 6. The image runs chapter 7's entry point with RUNTIME=agentcore, so these tests use
chapter 7's helpers (labs/ch07/tests/image_support.py) and leave the entry point's contract as a
whole to chapter 7's tests. They need chapter 5's pinned set (labs/ch05/requirements.txt); this lab's
own environment has no httpx, so the whole file is skipped there. The image isn't built here, which
needs a container engine that builds linux/arm64.
"""

from __future__ import annotations

import io
import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

pytest.importorskip("httpx", reason="the image's tests use chapter 5's environment (labs/ch05/requirements.txt)")

LAB = Path(__file__).resolve().parent.parent  # labs/ch06
sys.path.insert(0, str(LAB.parent / "ch07" / "tests"))
pytest.register_assert_rewrite("image_support")
import image_support as support  # noqa: E402
from image_support import ANSWER, QUESTION, needs_ch05  # noqa: E402

DOCKERFILE = LAB / "image" / "Dockerfile"
GOOGLE_DOCKERFILE = LAB.parent / "ch07" / "image" / "Dockerfile"
RUNTIME_TF = LAB / "terraform" / "runtime.tf"
ROOT_SOURCE = "ch06/image/private-ca.pem"  # the reader writes it before a build; it is never committed
PROVIDER = "w3-incident-model-gateway"
VAULT_KEY = "sk-w3-incident-from-the-token-vault"


def runtime_tf_env() -> dict[str, str]:
    """runtime.tf's environment_variables, names to their literal values or expressions."""
    text = RUNTIME_TF.read_text(encoding="utf-8")
    block = re.search(r"environment_variables\s*=\s*\{(.*?)\n\s*\}", text, re.S)
    assert block, "runtime.tf sets environment_variables"
    pairs = re.findall(r"^\s*([A-Z_]+)\s*=\s*(.+?)\s*$", block.group(1), re.M)
    return {name: value.strip('"') for name, value in pairs}


# --- the Dockerfile -------------------------------------------------------------------------------

def test_the_base_image_is_pinned_by_digest_and_is_chapter_7s() -> None:
    base = support.arguments(DOCKERFILE, "FROM")
    assert len(base) == 1 and re.search(r"@sha256:[0-9a-f]{64}$", base[0])
    assert base == support.arguments(GOOGLE_DOCKERFILE, "FROM")


def test_the_image_is_built_for_arm64_and_runs_chapter_7s_entry_point_on_8080() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "docker build --platform linux/arm64 -f ch06/image/Dockerfile" in text  # AgentCore runs ARM64 only
    assert support.environment(DOCKERFILE)["RUNTIME"] == "agentcore"
    assert support.literal(support.ADAPTER, "PORTS")["agentcore"] == 8080
    assert support.arguments(DOCKERFILE, "EXPOSE") == ["8080"]
    command = json.loads(support.arguments(DOCKERFILE, "CMD")[-1])
    assert command == ["python", support.image_paths(DOCKERFILE)["ch07/image/entrypoint.py"]]


def test_the_image_copies_the_token_vault_and_signing_modules_and_larkspurs_root() -> None:
    copied = support.image_paths(DOCKERFILE)
    for module in ("ch07/image/token_vault.py", "ch07/image/sigv4_mcp.py", "ch07/image/ca_bundle.py"):
        assert copied.get(module) == f"/app/labs/{module}"
    assert copied.get(ROOT_SOURCE) == "/app/custom-roots.pem"
    assert "GATEWAY_KEY" not in support.environment(DOCKERFILE)  # no key in the image or its environment


def test_every_file_the_dockerfile_copies_is_in_the_build_context() -> None:
    missing = [source for source in support.image_paths(DOCKERFILE)
               if source != ROOT_SOURCE and not (support.LABS / source).exists()]
    assert not missing, missing


def test_the_container_runs_as_a_user_of_its_own() -> None:
    support.check_runs_as_its_own_user(DOCKERFILE)


def test_the_image_installs_chapter_5s_pinned_set_and_nothing_proprietary() -> None:
    assert not support.pinned_set_problems(DOCKERFILE)


# --- the contract with runtime.tf -----------------------------------------------------------------

def test_runtime_tf_sets_what_the_entry_point_reads_and_no_key() -> None:
    env = runtime_tf_env()
    required = set(support.literal(support.ENTRYPOINT, "REQUIRED"))
    readable = required | set(support.literal(support.ENTRYPOINT, "KEY_SOURCES")) \
        | set(support.literal(support.ENTRYPOINT, "OPTIONAL"))
    assert required <= set(env), f"runtime.tf doesn't set: {sorted(required - set(env))}"
    assert set(env) <= readable, f"runtime.tf sets, but the entry point never reads: {sorted(set(env) - readable)}"
    assert "GATEWAY_KEY" not in env and env["GATEWAY_KEY_PROVIDER"] == "local.key_provider"
    assert (env["RUNTIME"], env["MCP_AUTH"]) == ("agentcore", "sigv4")
    assert env["MCP_URL"] == "local.tool_gateway"  # the tool gateway's URL, set in runtime.tf's locals
    assert env["TOOL_TARGETS"] == "local.tool_targets"  # each tool's target, from the catalog


# --- AgentCore's routes, in chapter 5's environment -----------------------------------------------

class Vault:
    """A stand-in for AgentCore Identity's data-plane client: one key, for one provider, per token."""

    def __init__(self, refuse: bool = False) -> None:
        self.calls: list[dict[str, str]] = []
        self.refuse = refuse

    def get_resource_api_key(self, **request: str) -> dict[str, str]:
        self.calls.append(request)
        if self.refuse or request["resourceCredentialProviderName"] != PROVIDER:
            raise PermissionError("AccessDeniedException")
        return {"apiKey": VAULT_KEY}


def agentcore_env(**overrides: str) -> dict[str, str]:
    env = support.contract("agentcore", GATEWAY_KEY_PROVIDER=PROVIDER, AWS_REGION="ca-central-1")
    del env["GATEWAY_KEY"]
    return env | overrides


@pytest.fixture(scope="module")
def entrypoint() -> ModuleType:
    return support.load_entrypoint()


@pytest.fixture(scope="module")
def trace_file(entrypoint: ModuleType, tmp_path_factory: pytest.TempPathFactory) -> Path:
    return support.trace_to_file(entrypoint, tmp_path_factory.mktemp("traces") / "traces.jsonl")


@pytest.fixture(scope="module")
def mcp_server(trace_file: Path, tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    with support.running_mcp_server(trace_file, tmp_path_factory.mktemp("mcp-server")) as server:
        yield server


@pytest.fixture
def session_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SESSION_STORAGE_DIR", str(tmp_path))  # Foundry's pin, if anything wrote one
    return tmp_path


# --- the tool gateway's names -------------------------------------------------------------------

TARGETS = {"get_pod_status": "k8s", "get_recent_alerts": "k8s", "search_runbooks": "knowledge"}


def served_as(names: dict[str, str]) -> list[Any]:
    """Chapter 5's locked tools as a gateway would list them: `names` maps each to its served name."""
    from mcp import types

    lock = json.loads((LAB.parent / "ch05" / "mcp-server" / "tools.lock.json").read_text(encoding="utf-8"))
    return [types.Tool.model_validate({**entry["definition"], "name": names.get(name, name)})
            for name, entry in lock["tools"].items()]


@needs_ch05
def test_the_gateways_prefixed_names_pass_the_lock_check_under_their_own(entrypoint: ModuleType) -> None:
    import sigv4_mcp

    harness, names = entrypoint.harness, sigv4_mcp.GatewayNames(TARGETS)
    lock = harness.read_lock(harness.LOCK_PATH)
    served = served_as({"get_pod_status": "k8s___get_pod_status", "get_recent_alerts": "k8s___get_recent_alerts"})
    assert set(harness.verify_tools(names.local_tools(served), lock, harness.ALLOWED)) == set(lock)
    assert names.served_name("get_pod_status") == "k8s___get_pod_status"
    assert names.served_name("not_in_the_catalog") == "not_in_the_catalog"
    with pytest.raises(harness.LockMismatch):  # unmapped, the gateway's names aren't the lock's
        harness.verify_tools(sigv4_mcp.GatewayNames().local_tools(served), lock, harness.ALLOWED)


@needs_ch05
@pytest.mark.parametrize("served_name", ["knowledge___get_pod_status", "k8s__get_pod_status", "get_pod_status___k8s"])
def test_a_tool_served_under_another_targets_prefix_is_refused(entrypoint: ModuleType, served_name: str) -> None:
    import sigv4_mcp

    harness = entrypoint.harness
    served = sigv4_mcp.GatewayNames(TARGETS).local_tools(served_as({"get_pod_status": served_name}))
    with pytest.raises(harness.LockMismatch, match="served but not in the lock file"):
        harness.verify_tools(served, harness.read_lock(harness.LOCK_PATH), harness.ALLOWED)


@needs_ch05
def test_a_call_goes_out_under_the_gateways_name_and_is_logged_under_the_tools(entrypoint: ModuleType) -> None:
    import asyncio

    import sigv4_mcp

    class Result:
        is_error, content, structured_content = False, [], {"service": "claims-api"}

    class Client:
        def __init__(self) -> None:
            self.names: list[str] = []

        async def call_tool(self, name: str, args: dict[str, Any], meta: dict[str, Any]) -> Result:
            self.names.append(name)
            return Result()

    async def run() -> tuple[Client, str]:
        client, log = Client(), io.StringIO()
        served = sigv4_mcp.GatewayNames(TARGETS).served_name("get_pod_status")
        tool = entrypoint.harness.bridge(client, "get_pod_status", "t-1", "http", log, asyncio.get_running_loop(),
                                         served=served)
        await asyncio.to_thread(tool, service="claims-api")
        return client, log.getvalue()

    client, log = asyncio.run(run())
    assert client.names == ["k8s___get_pod_status"]
    assert json.loads(log)["tool"] == "get_pod_status"


@needs_ch05
def test_the_entry_point_reads_each_tools_target_and_refuses_a_malformed_list(
        entrypoint: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    settings = entrypoint.read_settings(agentcore_env(MCP_AUTH="sigv4", TOOL_TARGETS="get_pod_status=k8s, search_runbooks=knowledge"))
    assert settings.tool_targets == (("get_pod_status", "k8s"), ("search_runbooks", "knowledge"))
    assert entrypoint.read_settings(agentcore_env()).tool_targets == ()
    for malformed in ("get_pod_status", "get_pod_status=", "=k8s", "get pod status=k8s", "a=b=c"):
        with pytest.raises(SystemExit):
            entrypoint.read_settings(agentcore_env(TOOL_TARGETS=malformed))
        assert "TOOL_TARGETS is not a list" in capsys.readouterr().err


@needs_ch05
def test_the_entry_point_takes_agentcores_key_provider_and_refuses_what_doesnt_fit(
        entrypoint: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    settings = entrypoint.read_settings(agentcore_env(MCP_AUTH="sigv4"))
    assert (settings.port, settings.gateway_key, settings.gateway_key_provider) == (8080, "", PROVIDER)
    assert (settings.mcp_auth, settings.aws_region) == ("sigv4", "ca-central-1")
    refusals = {
        "comes from one place": agentcore_env(GATEWAY_KEY="sk-both"),
        "on this runtime the key is GATEWAY_KEY": agentcore_env(RUNTIME="foundry"),
        "MCP_AUTH 'oauth'": agentcore_env(MCP_AUTH="oauth"),
        "AWS_REGION is not set": agentcore_env(AWS_REGION=" "),
    }
    for reason, env in refusals.items():
        with pytest.raises(SystemExit):
            entrypoint.read_settings(env)
        assert reason in capsys.readouterr().err


@needs_ch05
def test_one_question_end_to_end_on_agentcores_routes_with_the_key_from_the_vault(
        entrypoint: ModuleType, mcp_server: dict[str, Any], trace_file: Path, session_storage: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-master-key-the-image-must-not-send")
    env = agentcore_env(MCP_URL=mcp_server["url"])
    seen: list[dict[str, Any]] = []
    log, vault = io.StringIO(), Vault()
    app = entrypoint.build_app(entrypoint.read_settings(env), client=httpx.Client(transport=support.play_gateway(seen)),
                               log=log, vault=vault)
    trace_id, caller = entrypoint.tracing.new_trace_id(), "b7ad6b7169203331"
    headers = {"traceparent": f"00-{trace_id}-{caller}-01", "WorkloadAccessToken": "wat-for-this-request",
               "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": "incident-2026-10-29-claims-api-sam-okafor-0001"}
    with support.client_for(app) as http:
        ping = http.get("/ping")
        response = http.post("/invocations", json={"prompt": QUESTION}, headers=headers)
    assert ping.json() == {"status": "Healthy"}
    assert response.status_code == 200 and response.json() == {"response": ANSWER, "status": "success"}
    # The key came from the vault, once, for the right provider and with the request's token.
    assert vault.calls == [{"workloadIdentityToken": "wat-for-this-request", "resourceCredentialProviderName": PROVIDER}]
    support.check_one_run(entrypoint.tracing, env | {"GATEWAY_KEY": VAULT_KEY}, seen, log, mcp_server["log"],
                          trace_file, trace_id, caller)
    lines = [json.loads(line) for line in log.getvalue().splitlines()]
    assert all(line["agentcore_session_id"].startswith("incident-2026-10-29") for line in lines)
    assert "wat-for-this-request" not in log.getvalue() and VAULT_KEY not in log.getvalue()


@needs_ch05
@pytest.mark.parametrize("headers, vault", [
    ({}, Vault()),  # no workload access token: nothing to ask the vault with
    ({"WorkloadAccessToken": "wat-refused"}, Vault(refuse=True)),
])
def test_without_a_key_from_the_vault_no_model_is_called(entrypoint: ModuleType, mcp_server: dict[str, Any],
                                                          session_storage: Path, headers: dict[str, str],
                                                          vault: Vault) -> None:
    import httpx
    from starlette.testclient import TestClient

    seen: list[dict[str, Any]] = []
    app = entrypoint.build_app(entrypoint.read_settings(agentcore_env(MCP_URL=mcp_server["url"])),
                               client=httpx.Client(transport=support.play_gateway(seen)), log=io.StringIO(), vault=vault)
    with TestClient(app, raise_server_exceptions=False) as http:
        response = http.post("/invocations", json={"prompt": QUESTION}, headers=headers)
    assert response.status_code == 500  # AgentCore hands the caller a RuntimeClientError (424)
    assert seen == []
    assert len(vault.calls) == (1 if headers else 0)


@needs_ch05
def test_the_key_is_kept_for_fifteen_minutes_at_most(entrypoint: ModuleType) -> None:
    import runtime_adapter
    import token_vault

    now = [1000.0]
    vault = Vault()
    key = token_vault.TokenVaultKey(PROVIDER, "ca-central-1", client=vault, clock=lambda: now[0])
    token = runtime_adapter.WORKLOAD_TOKEN.set("wat-1")
    try:
        assert key() == key() == VAULT_KEY and len(vault.calls) == 1
        now[0] += 899
        key()
        assert len(vault.calls) == 1
        now[0] += 2  # past fifteen minutes: a rotated key is picked up
        key()
        assert len(vault.calls) == 2
    finally:
        runtime_adapter.WORKLOAD_TOKEN.reset(token)


@needs_ch05
def test_mcp_requests_to_the_tool_gateway_are_signed_with_the_runtimes_role(
        entrypoint: ModuleType, mcp_server: dict[str, Any], session_storage: Path,
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import httpx
    import httpx2
    import sigv4_mcp

    # Credentials from the environment only, as the runtime's container credentials would be.
    for name, value in {"AWS_ACCESS_KEY_ID": "AKIDEXAMPLE", "AWS_SECRET_ACCESS_KEY": "secret-for-the-test",
                        "AWS_SESSION_TOKEN": "session-token-for-the-test",
                        "AWS_SHARED_CREDENTIALS_FILE": str(tmp_path / "none"), "AWS_CONFIG_FILE": str(tmp_path / "none")}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    sent: list[httpx2.Request] = []
    real_client = httpx2.AsyncClient

    def recording_client(**options: Any) -> httpx2.AsyncClient:
        async def record(request: httpx2.Request) -> None:
            sent.append(request)
        return real_client(event_hooks={"request": [record]}, **options)

    monkeypatch.setattr(sigv4_mcp.httpx2, "AsyncClient", recording_client)
    env = agentcore_env(MCP_URL=mcp_server["url"], MCP_AUTH="sigv4")
    seen: list[dict[str, Any]] = []
    log = io.StringIO()
    app = entrypoint.build_app(entrypoint.read_settings(env), client=httpx.Client(transport=support.play_gateway(seen)),
                               log=log, vault=Vault())
    with support.client_for(app) as http:
        response = http.post("/invocations", json={"prompt": QUESTION}, headers={"WorkloadAccessToken": "wat-1"})
    assert response.status_code == 200 and response.json()["response"] == ANSWER
    assert json.loads(log.getvalue().splitlines()[0])["transport"] == "http"  # the transport says what it is
    assert sent, "the MCP client sent nothing through the signed client"
    scope = re.compile(r"^AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/\d{8}/ca-central-1/bedrock-agentcore/aws4_request, "
                       r"SignedHeaders=([a-z;-]+), Signature=[0-9a-f]{64}$")
    for request in sent:
        signed = scope.match(request.headers["authorization"])
        assert signed, request.headers["authorization"]
        assert {"host", "x-amz-date", "x-amz-security-token"} <= set(signed.group(1).split(";"))
        assert request.headers["x-amz-security-token"] == "session-token-for-the-test"
        if request.method == "POST":
            assert "content-type" in signed.group(1).split(";")

