"""The container's entry point: chapter 5's harness, behind its runtime adapter, on a managed runtime.

Chapters 6, 7 and 8. One entry point serves three runtimes, chosen by RUNTIME from chapter 5's adapter:

- agent-runtime (Google's Agent Runtime, chapter 7): port 8080, POST /api/reasoning_engine. The
  image is built from the `Dockerfile` next to this file; `../terraform/runtime.tf` sets the
  environment.
- foundry (Microsoft Foundry hosted agents, chapter 8): port 8088, GET /readiness and POST
  /invocations. The image is built from `labs/ch08/image/Dockerfile`, which sets RUNTIME; the
  hosted agent's version sets the rest.
- agentcore (Amazon Bedrock AgentCore Runtime, chapter 6): port 8080, GET /ping and POST
  /invocations. The image is built for linux/arm64 from `labs/ch06/image/Dockerfile`;
  `labs/ch06/terraform/runtime.tf` sets the environment.

The image doesn't know which workflow it serves. The process refuses to start, naming every
variable that is missing, unless all of these are set:

- RUNTIME: agent-runtime, foundry or agentcore.
- GATEWAY_URL: the model gateway's OpenAI-compatible base URL, ending in /v1.
- GATEWAY_KEY: the workflow's virtual key for the gateway, from the platform's secret store at
  run time (Secret Manager on Google, a project connection on Foundry). On AgentCore,
  GATEWAY_KEY_PROVIDER names an API-key credential provider instead, and `token_vault.py` fetches
  the key from AgentCore Identity's token vault with each request's workload access token.
- WORKFLOW, MODEL_ALIAS, DATA_CLASS: the workflow's name in its manifest, the alias it calls and
  the highest data class it sends. The gateway checks all three against the manifest on every call.
- MCP_URL: the Kubernetes MCP server's Streamable HTTP endpoint.
- OTEL_EXPORTER_OTLP_ENDPOINT: the OpenTelemetry Collector. Without it chapter 5's tracing writes
  to a file, and a file inside the container is lost with the instance, so it is required here.

MCP_AUTH=sigv4 signs every MCP request with the role the process runs under (`sigv4_mcp.py`),
which AgentCore Gateway's IAM authorization asks for; it needs AWS_REGION, as GATEWAY_KEY_PROVIDER
does. TOOL_TARGETS, as `tool=target` pairs separated by commas, names the gateway target that
serves each tool, since the gateway lists the tools under their target's prefix. PORT is optional and defaults to the runtime's own port. CUSTOM_ROOTS_FILE is optional too: it
names Larkspur's private root CA, /app/custom-roots.pem by default. When that file exists, as in
chapter 8's image, `ca_bundle.py` adds it to the CA bundle the runtime provides, at start and again
before every question, because Foundry's egress proxy CA rotates while the sandbox runs.

The rest is chapter 5's code, imported rather than copied. `GatewayModel` sends the model calls
through the gateway and offers the model only the tools the harness allows, as `tools.lock.json`
pins them. The harness checks the MCP server's tools against the same lock before the model sees
one. The runtime adapter serves the runtime's routes, `trace_setup` exports the spans, and on
SIGTERM the adapter's handler lets the process exit normally, so the last spans are sent. Inside
the container the server binds 0.0.0.0, and the platform is its only caller.

Run, from labs/ch07 in chapter 5's environment, with chapter 5's gateway on port 4010 and its MCP
server on 8765 (labs/ch05/README.md starts both) and the variables set, for example
RUNTIME=agent-runtime, GATEWAY_URL=http://127.0.0.1:4010/v1, GATEWAY_KEY=sk-local-only,
WORKFLOW=w2-ops-assistant, MODEL_ALIAS=larkspur-chat, DATA_CLASS=internal,
MCP_URL=http://127.0.0.1:8765/mcp, and OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318 for a
local Collector:

  python image/entrypoint.py --host 127.0.0.1
  curl -s localhost:8080/api/reasoning_engine -d '{"class_method": "query", "input": {"message": "Is claims-api healthy?"}}'

With RUNTIME=foundry the same run listens on 8088:

  curl -s localhost:8088/invocations -d '{"message": "Is claims-api healthy?"}'
"""

from __future__ import annotations

import argparse
import os
import re
import signal
import ssl
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NoReturn, TextIO

import httpx
import uvicorn
from starlette.applications import Starlette

# This file's folder and labs/ch05's, found from this file the same way in the repository and in
# the image.
HERE = Path(__file__).resolve().parent
CH05 = HERE.parents[1] / "ch05"
for folder in (HERE, CH05 / "adapter", CH05 / "harness", CH05 / "tracing"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import ca_bundle  # noqa: E402
import client as harness  # noqa: E402
import runtime_adapter as adapter  # noqa: E402
import trace_setup as tracing  # noqa: E402
from gateway_model import GatewayModel, pinned_tool_specs  # noqa: E402

RUNTIMES = ("agent-runtime", "foundry", "agentcore")  # the adapter's routes this image is built and tested for
REQUIRED = ("RUNTIME", "GATEWAY_URL", "WORKFLOW", "MODEL_ALIAS", "DATA_CLASS", "MCP_URL",
            "OTEL_EXPORTER_OTLP_ENDPOINT")
MCP_AUTHS = ("none", "sigv4")
KEY_SOURCES = ("GATEWAY_KEY", "GATEWAY_KEY_PROVIDER")  # exactly one: the key, or AgentCore's provider for it
OPTIONAL = ("PORT", "MCP_AUTH", "AWS_REGION", "CUSTOM_ROOTS_FILE", "TOOL_TARGETS")
NAME = re.compile(r"^[A-Za-z0-9_-]+$")  # a tool's name, or a gateway target's
CONTAINER_HOST = "0.0.0.0"


@dataclass(frozen=True)
class Settings:
    """The environment the deployment sets, read once at start-up."""

    runtime: str
    gateway_url: str
    gateway_key: str = field(repr=False)  # a secret: left out of the repr; empty with a key provider
    workflow: str
    model_alias: str
    data_class: str
    mcp_url: str
    port: int
    gateway_key_provider: str = ""  # AgentCore Identity's API-key credential provider
    mcp_auth: str = "none"
    aws_region: str = ""
    tool_targets: tuple[tuple[str, str], ...] = ()  # (tool, the gateway target that serves it)


def refuse(message: str) -> NoReturn:
    """Refuse to start, as chapter 5's processes do: say why on stderr and exit with status 2."""
    print(f"refusing to start: {message}", file=sys.stderr)
    raise SystemExit(2)


def read_settings(environ: Mapping[str, str] = os.environ) -> Settings:
    """The contract, or a refusal that names every required variable that is unset or blank."""
    # Stripped: a secret stored with a trailing newline arrives with it.
    values = {name: environ.get(name, "").strip() for name in REQUIRED}
    key, provider = (environ.get(name, "").strip() for name in KEY_SOURCES)
    missing = [name for name, value in values.items() if not value]
    if not (key or provider):
        missing.insert(min(2, len(missing)), "GATEWAY_KEY")
    if missing:
        refuse(f"{', '.join(missing)} {'is' if len(missing) == 1 else 'are'} not set. The image takes "
               "its configuration from the environment its deployment sets: runtime.tf on Agent "
               "Runtime and on AgentCore, the hosted agent's version on Foundry.")
    runtime = values["RUNTIME"]
    if runtime not in RUNTIMES:
        refuse(f"RUNTIME {runtime!r} is not one this image serves: {', '.join(RUNTIMES)}.")
    if key and provider:
        refuse("GATEWAY_KEY and GATEWAY_KEY_PROVIDER are both set; the key comes from one place.")
    if provider and runtime != "agentcore":
        refuse("GATEWAY_KEY_PROVIDER names an AgentCore Identity provider; on this runtime the key is GATEWAY_KEY.")
    mcp_auth = environ.get("MCP_AUTH", "").strip() or "none"
    if mcp_auth not in MCP_AUTHS:
        refuse(f"MCP_AUTH {mcp_auth!r} is not one of {', '.join(MCP_AUTHS)}.")
    region = environ.get("AWS_REGION", "").strip()
    if (provider or mcp_auth == "sigv4") and not region:
        refuse("AWS_REGION is not set; the token vault and SigV4 signing need it.")
    pairs = [pair.strip().partition("=") for pair in environ.get("TOOL_TARGETS", "").split(",") if pair.strip()]
    if any(not (NAME.match(tool) and sep and NAME.match(target)) for tool, sep, target in pairs):
        refuse("TOOL_TARGETS is not a list of tool=target pairs separated by commas.")
    port = environ.get("PORT", "").strip() or str(adapter.PORTS[runtime])
    if not (port.isdecimal() and 0 < int(port) < 65536):
        refuse(f"PORT {port!r} is not a port number.")
    return Settings(runtime=runtime, gateway_url=values["GATEWAY_URL"].rstrip("/"),
                    gateway_key=key, workflow=values["WORKFLOW"],
                    model_alias=values["MODEL_ALIAS"], data_class=values["DATA_CLASS"],
                    mcp_url=values["MCP_URL"], port=int(port), gateway_key_provider=provider,
                    mcp_auth=mcp_auth, aws_region=region,
                    tool_targets=tuple((tool, target) for tool, _, target in pairs))


def build_model(settings: Settings, client: httpx.Client | None = None, vault: Any = None) -> GatewayModel:
    """Chapter 5's gateway model, with everything it sends taken from the contract.

    No client is kept for the life of the process: without one, GatewayModel opens a client per
    call, and each reads SSL_CERT_FILE afresh. Foundry's egress proxy rotates its CA under a
    running sandbox (about every 30 days, Microsoft says), and a client made at start-up would
    keep trusting the old one. `client` is for tests, which pass a mock gateway's, and so is
    `vault`, a stand-in for AgentCore Identity's client.
    """
    common: dict[str, Any] = dict(tools=pinned_tool_specs(harness.LOCK_PATH, set(harness.ALLOWED)),
                                  workflow=settings.workflow, data_class=settings.data_class, client=client)
    if settings.gateway_key_provider:
        import token_vault

        key = token_vault.TokenVaultKey(settings.gateway_key_provider, settings.aws_region, client=vault)
        return token_vault.VaultKeyedModel(settings.gateway_url, settings.model_alias, key_source=key, **common)
    return GatewayModel(settings.gateway_url, settings.model_alias,
                        api_key=settings.gateway_key,  # the class would read LITELLM_MASTER_KEY
                        **common)


def mcp_server(settings: Settings) -> Callable[[], Any]:
    """What the harness connects to for each question: the URL, or a signed transport to it."""
    if settings.mcp_auth == "sigv4":
        import sigv4_mcp

        auth = sigv4_mcp.SigV4(settings.aws_region)
        targets = dict(settings.tool_targets)
        return lambda: sigv4_mcp.SignedMCP(settings.mcp_url, auth, targets)
    return lambda: settings.mcp_url


def trust_bundle() -> ca_bundle.TrustBundle | None:
    """Larkspur's roots in the runtime's CA bundle, built now; None when the image has no roots file."""
    try:
        trust = ca_bundle.TrustBundle.from_environment()
        if trust is not None:
            trust.refresh()
        return trust
    except (OSError, ssl.SSLError) as exc:
        refuse(f"the CA bundle can't be built: {exc}")


def with_current_roots(answer: adapter.Answer, trust: ca_bundle.TrustBundle, log: TextIO) -> adapter.Answer:
    """`answer`, once the CA bundle has caught up with the runtime's, whose egress proxy CA rotates.

    Every client a question opens (the model calls, the MCP session, the span export after it)
    reads the bundle when it connects, so refreshing it first covers the whole question.
    """

    async def answer_with_current_roots(question: str, traceparent: str | None,
                                        audit: Mapping[str, str] | None = None) -> str:
        try:
            trust.refresh()
        except (OSError, ssl.SSLError) as exc:  # the last good bundle stays; the next question retries
            harness.json_line(log, event="ca_bundle_kept", reason=str(exc))
        return await answer(question, traceparent, audit)

    return answer_with_current_roots


def build_app(settings: Settings, *, client: httpx.Client | None = None, log: TextIO = sys.stderr,
              trust: ca_bundle.TrustBundle | None = None, vault: Any = None) -> Starlette:
    """The runtime's routes, with the harness behind them and its model calls through the gateway.

    `client`, `log` and `vault` are there for tests: a mock gateway's client, a buffer for the
    harness's audit lines, which otherwise go to stderr and from there to the platform's logs, and
    a stand-in for the token vault.
    """
    answer = adapter.harness_answer(mcp_server(settings), model=build_model(settings, client, vault), log=log)
    if trust is not None:
        answer = with_current_roots(answer, trust, log)
    return adapter.build_app(settings.runtime, answer)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--host", default=CONTAINER_HOST, help="0.0.0.0 in the container; 127.0.0.1 on a laptop")
    args = parser.parse_args(argv)
    settings = read_settings()
    signal.signal(signal.SIGTERM, adapter.exit_cleanly)
    trust = trust_bundle()
    setup = tracing.configure("runtime-adapter")
    roots = {"ca_roots": str(trust.roots), "ca_base": str(trust.base)} if trust else {}
    harness.json_line(sys.stderr, event="adapter_start", runtime=settings.runtime, host=args.host,
                      port=settings.port, workflow=settings.workflow, alias=settings.model_alias,
                      data_class=settings.data_class, gateway=settings.gateway_url, mcp=settings.mcp_url,
                      tracing=setup.destination, **roots)
    uvicorn.run(build_app(settings, trust=trust), host=args.host, port=settings.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
