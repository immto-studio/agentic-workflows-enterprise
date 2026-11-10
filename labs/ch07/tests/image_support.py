"""Shared by the harness image's tests in chapters 7 and 8 (labs/ch07/tests, labs/ch08/tests).

Chapter 8's image runs chapter 7's entry point unchanged, so the two chapters' tests read their
Dockerfiles the same way and start the same things: chapter 5's MCP server over Streamable HTTP
under its identity, an httpx mock in place of the model gateway, and the entry point as a real
process that is then stopped with SIGTERM. The stopping, and the stub OpenTelemetry Collector it
reports to, come from chapter 5's tests (labs/ch05/tests/sigterm_support.py), which use them on the
runtime adapter.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import io
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest

LABS = Path(__file__).resolve().parents[2]  # labs, the images' build context
if str(LABS / "ch05" / "tests") not in sys.path:
    sys.path.append(str(LABS / "ch05" / "tests"))
import sigterm_support  # noqa: E402
ENTRYPOINT = LABS / "ch07" / "image" / "entrypoint.py"
ADAPTER = LABS / "ch05" / "adapter" / "runtime_adapter.py"
SERVER_PY = LABS / "ch05" / "mcp-server" / "server.py"
REQUIREMENTS = LABS / "ch05" / "requirements.txt"
BUNDLE_VARIABLES = ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "GRPC_DEFAULT_SSL_ROOTS_FILE_PATH")
TOOL_IDENTITY = "larkspur-ops-reader"
QUESTION = "Is claims-api healthy?"
ANSWER = "claims-api has 2 of 3 pods ready."  # play_gateway's answer from the MCP server's result

needs_ch05 = pytest.mark.skipif(
    importlib.util.find_spec("mcp") is None,
    reason="needs chapter 5's environment (labs/ch05/requirements.txt); mcp is not installed here",
)


# --- reading files without importing chapter 5 --------------------------------------------------

def literal(path: Path, name: str) -> Any:
    """A module-level constant, read without importing the module (that needs chapter 5's packages)."""
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{path.name} defines no {name}")


def instructions(dockerfile: Path) -> list[tuple[str, str]]:
    """A Dockerfile as (instruction, arguments), with comments dropped and continuations joined."""
    lines = [line for line in dockerfile.read_text(encoding="utf-8").splitlines()
             if not line.lstrip().startswith("#")]
    joined = re.sub(r"\\\n", " ", "\n".join(lines))
    out = []
    for line in joined.splitlines():
        if line.strip():
            op, _, args = line.strip().partition(" ")
            out.append((op.upper(), " ".join(args.split())))
    return out


def arguments(dockerfile: Path, instruction: str) -> list[str]:
    return [args for op, args in instructions(dockerfile) if op == instruction]


def environment(dockerfile: Path) -> dict[str, str]:
    """The variables the Dockerfile's ENV instructions set, later ones winning."""
    env: dict[str, str] = {}
    for args in arguments(dockerfile, "ENV"):
        env.update(pair.split("=", 1) for pair in shlex.split(args))
    return env


def image_paths(dockerfile: Path) -> dict[str, str]:
    """Build-context path -> path in the image, for every file the Dockerfile copies."""
    paths = {}
    for args in arguments(dockerfile, "COPY"):
        *sources, dest = [part for part in args.split() if not part.startswith("--")]
        for source in sources:
            paths[source] = dest + Path(source).name if dest.endswith("/") else dest
    return paths


def check_runs_as_its_own_user(dockerfile: Path) -> None:
    """The last USER is neither root nor uid 0, and the image creates that user."""
    users = arguments(dockerfile, "USER")
    assert users, "no USER: the container would run as root"
    user, _, group = users[-1].partition(":")
    assert user not in ("root", "0") and group not in ("root", "0"), users[-1]
    created = " ".join(arguments(dockerfile, "RUN"))
    assert re.search(rf"\buseradd\b[^&]*\b{re.escape(user)}\b", created), "the image creates that user"


def pinned_set_problems(dockerfile: Path) -> list[str]:
    """What is wrong with how the image installs chapter 5's pinned set; empty when nothing is."""
    requirements = REQUIREMENTS.read_text(encoding="utf-8")
    installs = [args for args in arguments(dockerfile, "RUN") if "pip install" in args]
    problems = []
    if len(installs) != 1 or f"-r {image_paths(dockerfile).get('ch05/requirements.txt')}" not in installs[0]:
        problems.append("not one pip install of ch05/requirements.txt as copied into the image")
    elif ("--require-hashes" in installs[0]) != ("--hash=" in requirements):
        problems.append("--require-hashes must be used exactly when the file has hashes")
    pins = [line.split(";")[0].strip().lower() for line in requirements.splitlines()
            if line.strip() and not line.lstrip().startswith("#")]
    problems += [f"proprietary pin: {pin}" for pin in pins if pin.startswith(("litellm-enterprise", "litellm["))]
    problems += [f"proxy extra: {args}" for _, args in instructions(dockerfile) if "[proxy]" in args]
    return problems


# --- the entry point -----------------------------------------------------------------------------

def contract(runtime: str, **overrides: str) -> dict[str, str]:
    """The entry point's environment, with values a test can tell apart from any default."""
    env = {"RUNTIME": runtime, "GATEWAY_URL": "https://llm-gateway.test.internal/v1",
           "GATEWAY_KEY": "sk-workflow-virtual-key", "WORKFLOW": "ops-assistant", "MODEL_ALIAS": "larkspur-chat",
           "DATA_CLASS": "confidential", "MCP_URL": "https://mcp-k8s.test.internal/mcp",
           "OTEL_EXPORTER_OTLP_ENDPOINT": "https://otel.test.internal"}
    return env | overrides


def load_entrypoint() -> ModuleType:
    """entrypoint.py as a module; importing it puts chapter 5's folders on the path, as in the image."""
    if str(ENTRYPOINT.parent) not in sys.path:
        sys.path.insert(0, str(ENTRYPOINT.parent))
    return importlib.import_module("entrypoint")


def trace_to_file(entrypoint: ModuleType, path: Path) -> Path:
    """This process's spans go to a JSON lines file, as in chapter 5's tests. The first set-up wins."""
    setup = entrypoint.tracing.configure("pytest", environ={entrypoint.tracing.TRACE_FILE_ENV: str(path)})
    return Path(setup.destination)


def client_for(app: Any) -> Any:
    """Starlette's TestClient, imported only where it runs: without httpx2, the import itself warns."""
    from starlette.testclient import TestClient

    return TestClient(app)


LOADED_FILES = (
    "import json, sys; sys.path.insert(0, sys.argv[1]); import entrypoint; "
    "print(json.dumps({'files': sorted({m.__file__ for m in list(sys.modules.values()) "
    "if getattr(m, '__file__', None)}), 'lock': str(entrypoint.harness.LOCK_PATH)}))"
)


def files_the_entry_point_loads() -> set[str]:
    """Every file under labs/ that a fresh interpreter loads to import the entry point, and the lock it reads."""
    result = subprocess.run([sys.executable, "-c", LOADED_FILES, str(ENTRYPOINT.parent)], capture_output=True,
                            text=True, timeout=120, env=os.environ | {"PYTHONUTF8": "1"})
    assert result.returncode == 0, result.stderr
    found = json.loads(result.stdout)
    loaded = {Path(name).resolve() for name in found["files"]} | {Path(found["lock"]).resolve()}
    return {path.relative_to(LABS).as_posix() for path in loaded if LABS in path.parents}


# --- processes and stand-ins ---------------------------------------------------------------------

def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def running_mcp_server(trace_file: Path, work: Path) -> Iterator[dict[str, Any]]:
    """Chapter 5's MCP server over Streamable HTTP, started the way its own tests start it."""
    port = free_port()
    drop = ("TOOL_IDENTITY", "TOOL_LOG_FILE", "TRACE_FILE", "OTEL_EXPORTER_OTLP_ENDPOINT")
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env |= {"TOOL_IDENTITY": TOOL_IDENTITY, "TOOL_LOG_FILE": str(work / "server.log"),
            "TRACE_FILE": str(trace_file), "PYTHONUTF8": "1"}
    with open(work / "server.err", "w", encoding="utf-8") as err:
        process = subprocess.Popen([sys.executable, str(SERVER_PY), "--transport", "streamable-http", "--port",
                                    str(port)], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=err)
        try:
            deadline = time.monotonic() + 30
            while True:
                if process.poll() is not None:
                    raise RuntimeError(f"the MCP server exited with {process.returncode}: "
                                       f"{(work / 'server.err').read_text(encoding='utf-8')}")
                try:
                    socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise TimeoutError(f"the MCP server did not listen on {port}") from None
                    time.sleep(0.1)
            yield {"url": f"http://127.0.0.1:{port}/mcp", "log": work / "server.log"}
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


def gateway_reply(body: dict[str, Any]) -> dict[str, Any]:
    """The model gateway's Chat Completions answer: one get_pod_status call, then an answer from its result."""
    results = [message for message in body["messages"] if message["role"] == "tool"]
    if results:
        pods = json.loads(results[-1]["content"])
        reply = {"role": "assistant", "content": f"{pods['service']} has {pods['ready']} of {pods['desired']} pods ready."}
    else:
        call = {"name": "get_pod_status", "arguments": json.dumps({"service": "claims-api"})}
        reply = {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": call}]}
    return {"choices": [{"index": 0, "message": reply}], "usage": {"prompt_tokens": 50, "completion_tokens": 10}}


def play_gateway(seen: list[dict[str, Any]]) -> httpx.MockTransport:
    """The model gateway as an httpx mock, recording what each call carried."""

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append({"url": str(request.url), "authorization": request.headers.get("authorization"), "body": body})
        return httpx.Response(200, json=gateway_reply(body))

    return httpx.MockTransport(handle)


def check_one_run(tracing: ModuleType, env: dict[str, str], seen: list[dict[str, Any]], log: io.StringIO,
                  server_log: Path, trace_file: Path, trace_id: str, caller: str) -> None:
    """One question's run, seen from the gateway, both logs and the spans, all in the caller's trace."""
    # Two model calls, each under the workflow's alias, tags and key.
    assert len(seen) == 2
    for call in seen:
        assert call["url"] == f"{env['GATEWAY_URL']}/chat/completions"
        assert call["authorization"] == f"Bearer {env['GATEWAY_KEY']}"
        assert call["body"]["model"] == env["MODEL_ALIAS"]
        assert call["body"]["metadata"]["tags"] == [f"workflow:{env['WORKFLOW']}", f"data_class:{env['DATA_CLASS']}"]
        assert call["body"]["metadata"]["trace_id"] == trace_id
        assert call["body"]["metadata"]["traceparent"].startswith(f"00-{trace_id}-")
        assert [tool["function"]["name"] for tool in call["body"]["tools"]] == ["get_pod_status"]
    pods = json.loads(seen[1]["body"]["messages"][-1]["content"])
    assert (pods["service"], pods["ready"], pods["desired"]) == ("claims-api", 2, 3)  # the MCP server's answer
    # The harness's audit lines and the MCP server's call log carry the same trace id.
    lines = [json.loads(line) for line in log.getvalue().splitlines()]
    assert [line["event"] for line in lines] == ["tools_verified", "tool_call", "answer"]
    assert all(line["trace_id"] == trace_id for line in lines) and lines[0]["transport"] == "http"
    served = [json.loads(line) for line in server_log.read_text(encoding="utf-8").splitlines()
              if '"tool_call"' in line and trace_id in line]
    assert [(s["trace_source"], s["identity"]) for s in served] == [("request", TOOL_IDENTITY)]
    # So do the spans: the adapter's under the caller's, the run under it, the server's in the same trace.
    spans = {(s["attributes"].get(tracing.LARKSPUR_COMPONENT), s["name"]): s
             for s in tracing.read_spans(trace_file) if s["trace_id"] == trace_id}
    entry, run = spans[(None, "runtime_adapter")], spans[("harness", "invoke_agent harness")]
    assert entry["parent_span_id"] == caller and run["parent_span_id"] == entry["span_id"]
    assert run["attributes"]["larkspur.transport"] == "http"  # MCP_URL, not a stdio subprocess
    assert ("mcp-server", "execute_tool get_pod_status") in spans


def serve_then_sigterm(runtime: str, probe_path: str) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """The entry point as a process on a free port, as the image's command runs it: probed, then
    stopped with SIGTERM (chapter 5's sigterm_support does the stopping).

    Returns the finished process and the paths the stub Collector received. Nothing calls the
    gateway or the MCP server, so their addresses are placeholders.
    """
    port = free_port()
    keep = {k: v for k, v in os.environ.items()
            if k not in (*literal(ENTRYPOINT, "REQUIRED"), "PORT", "TRACE_FILE", "CUSTOM_ROOTS_FILE")}
    env = keep | contract(runtime) | {"PORT": str(port)}
    return sigterm_support.serve_then_sigterm(ENTRYPOINT, ["--host", "127.0.0.1"],
                                              f"http://127.0.0.1:{port}{probe_path}", env)
