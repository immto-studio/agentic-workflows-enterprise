"""The harness image for Agent Runtime: its contract with runtime.tf, its refusal, one request end to
end, a clean stop on SIGTERM, and the rules its Dockerfile keeps.

Chapter 7. The tests don't build the image, which needs a container engine. The Dockerfile and
contract checks read files and run wherever httpx is installed, this lab's environment included;
without httpx the whole file is skipped. The others import the entry point, which needs chapter
5's pinned set (labs/ch05/requirements.txt) rather than this lab's, and are skipped when `mcp` is
not installed. The entry point serves Foundry as well: this file covers its contract
as a whole and Google's route, and labs/ch08/tests covers Foundry's image and routes. The helpers
both chapters use are in image_support.py.
"""

from __future__ import annotations

import io
import json
import os
import re
import signal
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

pytest.importorskip("httpx", reason="the image's tests use chapter 5's environment (labs/ch05/requirements.txt)")

import httpx  # noqa: E402

pytest.register_assert_rewrite("image_support")
import image_support as support  # noqa: E402
from image_support import ANSWER, QUESTION, needs_ch05  # noqa: E402

LAB = Path(__file__).resolve().parent.parent  # labs/ch07
DOCKERFILE = LAB / "image" / "Dockerfile"
RUNTIME_TF = LAB / "terraform" / "runtime.tf"
CA_SOURCE = "ch07/image/gateway-ca.pem"  # the pipeline writes it before a build; it is never committed
SYSTEM_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"


# --- reading runtime.tf ---------------------------------------------------------------------------

def without_comments(hcl: str) -> str:
    return re.sub(r"(?m)^\s*(#|//).*$|\s#.*$", "", hcl)


def block_bodies(hcl: str, keyword: str) -> list[str]:
    """The body of every `keyword { ... }` block, nested blocks included."""
    bodies = []
    for start in re.finditer(rf"(?m)^\s*{keyword}\s*\{{", hcl):
        depth, end = 1, start.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(hcl[end], 0)
            end += 1
        bodies.append(hcl[start.end():end - 1])
    return bodies


def runtime_tf_env() -> dict[str, str | None]:
    """runtime.tf's env and secret_env blocks, name -> value as written (None for a secret)."""
    hcl = without_comments(RUNTIME_TF.read_text(encoding="utf-8"))
    found: dict[str, str | None] = {}
    for keyword in ("env", "secret_env"):
        for body in block_bodies(hcl, keyword):
            while re.search(r"\{[^{}]*\}", body):  # drop nested blocks, such as secret_ref
                body = re.sub(r"\{[^{}]*\}", "", body)
            name = re.search(r'(?m)^\s*name\s*=\s*"([^"]+)"', body)
            value = re.search(r'(?m)^\s*value\s*=\s*"?([^"\n]*?)"?\s*$', body)
            if name:
                found[name.group(1)] = value.group(1) if value else None
    return found


# --- the contract with runtime.tf -----------------------------------------------------------------

def test_runtime_tf_sets_what_the_entry_point_requires_and_nothing_it_ignores() -> None:
    set_by_terraform = set(runtime_tf_env())
    required = set(support.literal(support.ENTRYPOINT, "REQUIRED"))
    unset = required - set_by_terraform
    assert not unset, f"the entry point requires, but runtime.tf doesn't set: {sorted(unset)}"
    # On Google the key is the secret runtime.tf mounts; AgentCore's provider is chapter 6's.
    assert set_by_terraform & set(support.literal(support.ENTRYPOINT, "KEY_SOURCES")) == {"GATEWAY_KEY"}
    readable = required | set(support.literal(support.ENTRYPOINT, "KEY_SOURCES")) \
        | set(support.literal(support.ENTRYPOINT, "OPTIONAL"))
    ignored = set_by_terraform - readable
    assert not ignored, f"runtime.tf sets, but the entry point never reads: {sorted(ignored)}"


def test_the_container_listens_where_runtime_tf_calls_it_and_runs_the_entry_point() -> None:
    runtime = runtime_tf_env()["RUNTIME"]
    assert runtime == "agent-runtime" and runtime in support.literal(support.ENTRYPOINT, "RUNTIMES")
    port = re.search(r"container_spec\s*\{[^}]*\bport\s*=\s*(\d+)",
                     without_comments(RUNTIME_TF.read_text(encoding="utf-8")))
    assert port and int(port.group(1)) == support.literal(support.ADAPTER, "PORTS")[runtime] == 8080
    assert support.arguments(DOCKERFILE, "EXPOSE") == [port.group(1)]
    command = json.loads(support.arguments(DOCKERFILE, "CMD")[-1])  # exec form: Python gets SIGTERM
    assert command == ["python", support.image_paths(DOCKERFILE)["ch07/image/entrypoint.py"]]


# --- the Dockerfile -------------------------------------------------------------------------------

def test_the_base_image_is_pinned_by_digest() -> None:
    bases = support.arguments(DOCKERFILE, "FROM")
    assert bases and all(re.fullmatch(r"python:3\.12-slim@sha256:[0-9a-f]{64}", base) for base in bases), bases


def test_the_gateway_ca_comes_from_the_build_context_into_the_system_store() -> None:
    ops = support.instructions(DOCKERFILE)
    installs = [i for i, (op, args) in enumerate(ops)
                if op == "COPY" and re.search(r" /usr/local/share/ca-certificates/[^/ ]+\.crt$", args)]
    assert len(installs) == 1, "one COPY into /usr/local/share/ca-certificates, as a .crt file"
    assert ops[installs[0]][1].split()[:-1] == [CA_SOURCE]
    assert any(op == "RUN" and "update-ca-certificates" in args for op, args in ops[installs[0] + 1:])
    # Taken from the build context, never fetched while building.
    assert not support.arguments(DOCKERFILE, "ADD")
    assert not [args for args in support.arguments(DOCKERFILE, "RUN") if re.search(r"\b(curl|wget)\b", args)]


def test_python_http_and_grpc_clients_trust_the_system_store() -> None:
    env = support.environment(DOCKERFILE)
    for name in support.BUNDLE_VARIABLES:
        assert env.get(name) == SYSTEM_BUNDLE, name


def test_the_container_runs_as_a_user_of_its_own() -> None:
    support.check_runs_as_its_own_user(DOCKERFILE)


def test_every_file_the_dockerfile_copies_is_in_the_build_context() -> None:
    copied = support.image_paths(DOCKERFILE)
    missing = [source for source in copied if source != CA_SOURCE and not (support.LABS / source).is_file()]
    assert not missing, missing


def test_the_image_installs_chapter_5s_pinned_set_and_nothing_proprietary() -> None:
    assert support.pinned_set_problems(DOCKERFILE) == []


# --- the entry point, in chapter 5's environment --------------------------------------------------

class Recorded(dict[str, str]):
    """An environment that remembers which names were read from it."""

    def __init__(self, values: dict[str, str]) -> None:
        super().__init__(values)
        self.read: set[str] = set()

    def get(self, key: str, default: Any = None) -> Any:
        self.read.add(key)
        return super().get(key, default)

    def __getitem__(self, key: str) -> str:
        self.read.add(key)
        return super().__getitem__(key)


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


@needs_ch05
def test_the_entry_point_reads_every_variable_runtime_tf_sets_and_needs_no_other(entrypoint: ModuleType) -> None:
    values = support.contract("agent-runtime")
    environ = Recorded({name: values.get(name, "8080") for name in runtime_tf_env()})
    settings = entrypoint.read_settings(environ)  # it would refuse if it needed anything else
    assert set(runtime_tf_env()) <= environ.read
    assert (settings.runtime, settings.port) == ("agent-runtime", 8080)
    assert "sk-workflow-virtual-key" not in repr(settings)


@needs_ch05
def test_the_entry_point_refuses_to_start_naming_every_missing_variable(
        entrypoint: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        entrypoint.read_settings({})
    assert exc.value.code == 2
    err = capsys.readouterr().err
    named = (*entrypoint.REQUIRED, "GATEWAY_KEY")  # the key, or on AgentCore the provider that holds it
    assert err.startswith("refusing to start: ") and all(name in err for name in named)
    # A blank value counts as missing, and only what is missing is named.
    env = support.contract("agent-runtime", MCP_URL="  ")
    del env["GATEWAY_KEY"]
    with pytest.raises(SystemExit):
        entrypoint.read_settings(env)
    err = capsys.readouterr().err
    assert {name for name in named if name in err} == {"GATEWAY_KEY", "MCP_URL"}


@needs_ch05
def test_each_runtime_listens_on_its_own_port_unless_told_otherwise(
        entrypoint: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    assert entrypoint.read_settings(support.contract("agent-runtime")).port == 8080
    assert entrypoint.read_settings(support.contract("foundry")).port == 8088
    assert entrypoint.read_settings(support.contract("foundry", PORT="9090")).port == 9090
    assert entrypoint.read_settings(support.contract("agentcore")).port == 8080  # chapter 6
    for runtime in ("Foundry", "lambda", "agent_runtime"):
        with pytest.raises(SystemExit):
            entrypoint.read_settings(support.contract(runtime))
        assert f"RUNTIME {runtime!r}" in capsys.readouterr().err
    for bad in ("http", "0", "65536", "-1"):
        with pytest.raises(SystemExit):
            entrypoint.read_settings(support.contract("agent-runtime", PORT=bad))
        assert f"PORT {bad!r}" in capsys.readouterr().err


@needs_ch05
def test_without_a_roots_file_the_runtimes_bundle_is_left_alone(entrypoint: ModuleType,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    # Google's image has no /app/custom-roots.pem: the Agent Gateway checks the destinations itself.
    monkeypatch.delenv("CUSTOM_ROOTS_FILE", raising=False)
    monkeypatch.setenv("SSL_CERT_FILE", SYSTEM_BUNDLE)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    assert entrypoint.trust_bundle() is None
    assert os.environ["SSL_CERT_FILE"] == SYSTEM_BUNDLE and "REQUESTS_CA_BUNDLE" not in os.environ


@needs_ch05
def test_the_process_exits_before_serving_anything_without_its_environment() -> None:
    contract_names = set(support.literal(support.ENTRYPOINT, "REQUIRED"))
    env = {k: v for k, v in os.environ.items() if k not in contract_names | {"PORT"}} | {"PYTHONUTF8": "1"}
    result = subprocess.run([sys.executable, str(support.ENTRYPOINT)], env=env, stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 2, result.stderr
    assert result.stdout == ""
    assert "refusing to start" in result.stderr
    assert all(name in result.stderr for name in contract_names)


@needs_ch05
def test_the_command_serves_googles_route_on_every_interface(
        entrypoint: ModuleType, trace_file: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    # `trace_file` has set tracing up already, so main's own configure() call keeps the file exporter.
    served: dict[str, Any] = {}
    handlers: dict[int, Any] = {}
    monkeypatch.setattr(entrypoint.uvicorn, "run", lambda app, **options: served.update(options, app=app))
    monkeypatch.setattr(entrypoint.signal, "signal", lambda signum, handler: handlers.update({signum: handler}))
    for name, value in support.contract("agent-runtime").items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("CUSTOM_ROOTS_FILE", raising=False)  # Google's image carries no roots file
    assert entrypoint.main([]) == 0
    assert (served["host"], served["port"]) == ("0.0.0.0", 8080)
    assert handlers == {signal.SIGTERM: entrypoint.adapter.exit_cleanly}  # chapter 5's, shared
    start = json.loads([line for line in capsys.readouterr().err.splitlines() if line.startswith("{")][-1])
    assert (start["event"], start["runtime"], start["workflow"]) == ("adapter_start", "agent-runtime", "ops-assistant")
    assert "sk-workflow-virtual-key" not in json.dumps(start)
    with support.client_for(served["app"]) as http:
        wrong = http.post("/api/reasoning_engine", json={"class_method": "delete_everything", "input": {}})
        assert wrong.status_code == 400
        assert http.post("/invocations", json={"prompt": QUESTION}).status_code == 404


@needs_ch05
def test_the_image_holds_every_file_the_entry_point_loads() -> None:
    needed = support.files_the_entry_point_loads()
    assert "ch01/agent_loop.py" in needed  # the harness runs the chapter 1 loop
    copied = support.image_paths(DOCKERFILE)
    assert not needed - set(copied), f"loaded but not copied into the image: {sorted(needed - set(copied))}"
    assert all(copied[path] == f"/app/labs/{path}" for path in needed), "the image keeps the repository's layout"


@needs_ch05
def test_one_question_end_to_end_on_googles_route(entrypoint: ModuleType, mcp_server: dict[str, Any],
                                                  trace_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-master-key-the-image-must-not-send")
    env = support.contract("agent-runtime", MCP_URL=mcp_server["url"])
    seen: list[dict[str, Any]] = []
    log = io.StringIO()
    app = entrypoint.build_app(entrypoint.read_settings(env), client=httpx.Client(transport=support.play_gateway(seen)),
                               log=log)
    trace_id, caller = entrypoint.tracing.new_trace_id(), "b7ad6b7169203331"
    with support.client_for(app) as http:
        response = http.post("/api/reasoning_engine", json={"class_method": "query", "input": {"message": QUESTION}},
                             headers={"traceparent": f"00-{trace_id}-{caller}-01"})
        assert http.post("/invocations", json={"message": QUESTION}).status_code == 404  # Foundry's route
    assert response.status_code == 200
    assert response.json() == {"output": ANSWER}
    support.check_one_run(entrypoint.tracing, env, seen, log, mcp_server["log"], trace_file, trace_id, caller)


@needs_ch05
def test_sigterm_stops_the_process_cleanly_and_its_spans_still_leave() -> None:
    result, received = support.serve_then_sigterm("agent-runtime", "/api/reasoning_engine")
    assert result.returncode == 0, result.stderr
    assert "probe 405" in result.stdout  # it serves Google's route, which takes POST only
    assert "/v1/traces" in received  # the span queued before SIGTERM was flushed on the way out
    assert "Traceback" not in result.stderr
