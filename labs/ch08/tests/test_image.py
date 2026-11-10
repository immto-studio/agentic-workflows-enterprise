"""The harness image for Microsoft Foundry hosted agents: its Dockerfile, Foundry's routes end to end,
Larkspur's private root CA in the runtime's bundle, and a clean stop on SIGTERM.

Chapter 8. The image runs chapter 7's entry point with RUNTIME=foundry, so these tests use chapter
7's helpers (labs/ch07/tests/image_support.py) and leave the entry point's contract as a whole to
chapter 7's tests. They need chapter 5's pinned set (labs/ch05/requirements.txt). This lab's own
environment has no httpx, so the whole file is skipped there; chapter 7's runs the Dockerfile and
CA bundle checks and skips the rest, which need `mcp`. The tests don't build the image, which needs
a container engine. The TLS tests use certificates they generate.
"""

from __future__ import annotations

import importlib.util
import io
import ipaddress
import json
import os
import re
import signal
import ssl
import sys
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

pytest.importorskip("httpx", reason="the image's tests use chapter 5's environment (labs/ch05/requirements.txt)")

import httpx  # noqa: E402

LAB = Path(__file__).resolve().parent.parent  # labs/ch08
sys.path.insert(0, str(LAB.parent / "ch07" / "tests"))
pytest.register_assert_rewrite("image_support")
import image_support as support  # noqa: E402
from image_support import ANSWER, QUESTION, needs_ch05  # noqa: E402

sys.path.insert(0, str(support.ENTRYPOINT.parent))
import ca_bundle  # noqa: E402

DOCKERFILE = LAB / "image" / "Dockerfile"
GOOGLE_DOCKERFILE = LAB.parent / "ch07" / "image" / "Dockerfile"
ROOT_SOURCE = "ch08/image/private-ca.pem"  # the reader writes it before a build; it is never committed

needs_tls_tools = pytest.mark.skipif(
    importlib.util.find_spec("cryptography") is None or importlib.util.find_spec("requests") is None,
    reason="the TLS tests generate certificates with cryptography and call through requests too",
)


# --- the Dockerfile -------------------------------------------------------------------------------

def test_the_base_image_is_pinned_by_digest_and_is_chapter_7s() -> None:
    bases = support.arguments(DOCKERFILE, "FROM")
    assert len(bases) == 1 and re.fullmatch(r"python:3\.12-slim@sha256:[0-9a-f]{64}", bases[0]), bases
    assert bases == support.arguments(GOOGLE_DOCKERFILE, "FROM")  # one entry point, one Python


def test_larkspurs_root_goes_in_as_a_file_and_the_runtime_keeps_its_bundle() -> None:
    """Larkspur's root sits where the entry point looks for it, outside the system store.

    Foundry injects its egress proxy's CA and the bundle variables, and Microsoft says not to persist
    that CA, so the image sets none of the variables and holds no CA but Larkspur's own.
    """
    copied = support.image_paths(DOCKERFILE)
    certificates = {source: dest for source, dest in copied.items() if source.endswith((".pem", ".crt"))}
    assert certificates == {ROOT_SOURCE: support.literal(support.ENTRYPOINT.parent / "ca_bundle.py", "DEFAULT_ROOTS")}
    runs = support.arguments(DOCKERFILE, "RUN")
    assert any(f"openssl x509 -in {certificates[ROOT_SOURCE]}" in run for run in runs)  # no certificate, no build
    assert not [run for run in runs if "update-ca-certificates" in run or re.search(r"\b(curl|wget)\b", run)]
    assert not set(support.BUNDLE_VARIABLES) & set(support.environment(DOCKERFILE))
    assert not support.arguments(DOCKERFILE, "ADD")


def test_the_image_runs_chapter_7s_entry_point_on_foundrys_port() -> None:
    env = support.environment(DOCKERFILE)
    assert env["RUNTIME"] == "foundry" and "foundry" in support.literal(support.ENTRYPOINT, "RUNTIMES")
    port = support.literal(support.ADAPTER, "PORTS")["foundry"]
    assert port == 8088 and support.arguments(DOCKERFILE, "EXPOSE") == [str(port)]
    assert "PORT" not in env  # Microsoft: set it only when the platform needs a port other than 8088
    command = json.loads(support.arguments(DOCKERFILE, "CMD")[-1])  # exec form: Python gets SIGTERM
    assert command == ["python", support.image_paths(DOCKERFILE)["ch07/image/entrypoint.py"]]
    assert not list((LAB / "image").rglob("*.py"))  # chapter 7's entry point, reused rather than copied


def test_python_loads_nothing_from_the_sessions_storage() -> None:
    """$HOME is the session's storage, which callers can upload into: no user site-packages, no code there."""
    assert support.environment(DOCKERFILE).get("PYTHONNOUSERSITE") == "1"
    assert all(dest.startswith("/app/") for dest in support.image_paths(DOCKERFILE).values())
    assert support.arguments(DOCKERFILE, "WORKDIR") == ["/app"]


def test_the_container_runs_as_a_user_of_its_own() -> None:
    support.check_runs_as_its_own_user(DOCKERFILE)


def test_it_copies_the_same_code_as_chapter_7s_image() -> None:
    def code(dockerfile: Path) -> dict[str, str]:  # each image's CA file is its own
        return {source: dest for source, dest in support.image_paths(dockerfile).items() if not source.endswith(".pem")}

    assert code(DOCKERFILE) == code(GOOGLE_DOCKERFILE)


def test_every_file_the_dockerfile_copies_is_in_the_build_context() -> None:
    copied = support.image_paths(DOCKERFILE)
    missing = [source for source in copied if source != ROOT_SOURCE and not (support.LABS / source).is_file()]
    assert not missing, missing


def test_the_image_installs_chapter_5s_pinned_set_and_nothing_proprietary() -> None:
    assert support.pinned_set_problems(DOCKERFILE) == []


# --- certificates and TLS servers for the CA bundle tests -----------------------------------------

def make_ca(name: str) -> tuple[Any, Any]:
    """A self-signed CA, valid for a day: its key and its certificate."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.now(timezone.utc)
    usage = x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=False,
                          data_encipherment=False, key_agreement=False, key_cert_sign=True, crl_sign=True,
                          encipher_only=False, decipher_only=False)
    certificate = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
                   .serial_number(x509.random_serial_number())
                   .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=1))
                   .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                   .add_extension(usage, critical=True)
                   .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
                   .sign(key, hashes.SHA256()))
    return key, certificate


def issue(ca: tuple[Any, Any], folder: Path, name: str) -> tuple[Path, Path]:
    """A server certificate for 127.0.0.1, signed by `ca`, as (certificate file, key file)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    ca_key, ca_certificate = ca
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.now(timezone.utc)
    certificate = (x509.CertificateBuilder()
                   .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")]))
                   .issuer_name(ca_certificate.subject).public_key(key.public_key())
                   .serial_number(x509.random_serial_number())
                   .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=1))
                   .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                                  critical=False)
                   .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                   .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                   .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                                  critical=False)
                   .sign(ca_key, hashes.SHA256()))
    paths = folder / f"{name}.crt", folder / f"{name}.key"
    paths[0].write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    paths[1].write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    return paths


def write_cas(path: Path, *cas: tuple[Any, Any]) -> Path:
    """A PEM bundle of the CAs' certificates."""
    from cryptography.hazmat.primitives import serialization

    path.write_bytes(b"".join(ca[1].public_bytes(serialization.Encoding.PEM) for ca in cas))
    return path


class TLSServer(ThreadingHTTPServer):
    """An HTTPS server on 127.0.0.1 whose certificate can change between connections, as a
    TLS-inspecting proxy's does when its CA rotates."""

    daemon_threads = True

    def use(self, certificate: tuple[Path, Path]) -> None:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(*certificate)
        self.context = context

    def get_request(self) -> tuple[Any, Any]:
        sock, address = super().get_request()
        return self.context.wrap_socket(sock, server_side=True), address


@contextmanager
def tls_server(handler: type[BaseHTTPRequestHandler], certificate: tuple[Path, Path]) -> Iterator[TLSServer]:
    server = TLSServer(("127.0.0.1", 0), handler)
    server.use(certificate)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


class Hello(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("content-length", "5")
        self.end_headers()
        self.wfile.write(b"hello")

    def log_message(self, *args: Any) -> None:
        pass


class Gateway(BaseHTTPRequestHandler):
    """The model gateway behind TLS, with the answers the httpx mock gives."""

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))))
        reply = json.dumps(support.gateway_reply(body)).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture
def runtime_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Larkspur's root as the image's roots file, and a runtime bundle that holds an egress proxy's CA,
    named by SSL_CERT_FILE and REQUESTS_CA_BUNDLE as Foundry names it. The variables are restored after."""
    larkspur, proxy = make_ca("Larkspur private root (test)"), make_ca("Foundry egress proxy (test)")
    roots = write_cas(tmp_path / "custom-roots.pem", larkspur)
    runtime = write_cas(tmp_path / "runtime-bundle.pem", proxy)
    for name in ca_bundle.VARIABLES:
        monkeypatch.setenv(name, str(runtime))
    monkeypatch.setenv(ca_bundle.ROOTS_ENV, str(roots))
    return {"larkspur": larkspur, "proxy": proxy, "roots": roots, "runtime": runtime, "dir": tmp_path}


# --- Larkspur's root in the runtime's bundle ------------------------------------------------------

@needs_tls_tools
def test_the_combined_bundle_reaches_a_server_larkspurs_root_signed(runtime_bundle: dict[str, Any]) -> None:
    import requests

    folder = runtime_bundle["dir"]
    with tls_server(Hello, issue(runtime_bundle["larkspur"], folder, "gateway")) as server:
        url = f"https://127.0.0.1:{server.server_port}/"
        with pytest.raises(httpx.ConnectError):
            httpx.get(url)  # the runtime's bundle alone doesn't hold Larkspur's root
        trust = ca_bundle.TrustBundle.from_environment(combined=folder / "runtime-ca-bundle.pem")
        assert trust is not None and trust.refresh()
        assert {os.environ[name] for name in ca_bundle.VARIABLES} == {str(trust.combined)}
        assert httpx.get(url).text == "hello"  # httpx reads SSL_CERT_FILE, as the model calls do
        assert requests.get(url, timeout=10).text == "hello"  # REQUESTS_CA_BUNDLE, as the OTLP exporter does
        if importlib.util.find_spec("httpx2"):  # the MCP client's library, in chapter 5's environment
            import httpx2

            assert httpx2.get(url).text == "hello"
        server.use(issue(runtime_bundle["proxy"], folder, "through-the-proxy"))
        assert httpx.get(url).text == "hello"  # and the runtime's proxy CA is still trusted


@needs_tls_tools
def test_without_a_runtime_bundle_larkspurs_root_joins_certifis(runtime_bundle: dict[str, Any],
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    import certifi

    for name in ca_bundle.VARIABLES:
        monkeypatch.delenv(name)  # egress controls off: the runtime sets no bundle
    trust = ca_bundle.TrustBundle.from_environment(combined=runtime_bundle["dir"] / "runtime-ca-bundle.pem")
    assert trust is not None and trust.base == Path(certifi.where())
    trust.refresh()
    combined = trust.combined.read_bytes()
    assert combined.startswith(Path(certifi.where()).read_bytes().rstrip(b"\n"))
    assert combined.endswith(runtime_bundle["roots"].read_bytes())
    with tls_server(Hello, issue(runtime_bundle["larkspur"], runtime_bundle["dir"], "gateway")) as server:
        assert httpx.get(f"https://127.0.0.1:{server.server_port}/").text == "hello"


@needs_tls_tools
def test_a_rotated_runtime_bundle_is_picked_up_and_a_half_written_one_is_not(runtime_bundle: dict[str, Any]) -> None:
    folder, runtime = runtime_bundle["dir"], runtime_bundle["runtime"]
    trust = ca_bundle.TrustBundle.from_environment(combined=folder / "runtime-ca-bundle.pem")
    assert trust is not None and trust.refresh()
    rotated = make_ca("Foundry egress proxy, rotated (test)")
    with tls_server(Hello, issue(rotated, folder, "rotated")) as server:  # the proxy, after its CA rotated
        url = f"https://127.0.0.1:{server.server_port}/"
        with pytest.raises(httpx.ConnectError):
            httpx.get(url)  # the bundle as built before the rotation
        write_cas(runtime, rotated)  # the runtime rewrites its bundle in place
        assert trust.refresh() and httpx.get(url).text == "hello"
        assert not trust.refresh()  # nothing changed since, so nothing is written
        runtime.write_bytes(b"-----BEGIN CERTIFICATE-----\nMIIBszCCAVmgAwIBAgIU")  # caught half-written
        with pytest.raises(ssl.SSLError):
            trust.refresh()
        assert httpx.get(url).text == "hello"  # the last good bundle is still in place


# --- Foundry's routes, in chapter 5's environment -------------------------------------------------

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
def test_the_image_holds_every_file_the_entry_point_loads() -> None:
    needed = support.files_the_entry_point_loads()
    copied = support.image_paths(DOCKERFILE)
    assert not needed - set(copied), f"loaded but not copied into the image: {sorted(needed - set(copied))}"
    assert all(copied[path] == f"/app/labs/{path}" for path in needed), "the image keeps the repository's layout"


@needs_ch05
@needs_tls_tools
def test_the_command_serves_foundrys_routes_on_8088_with_larkspurs_root_in_the_bundle(
        entrypoint: ModuleType, trace_file: Path, runtime_bundle: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    # `trace_file` has set tracing up already, so main's own configure() call keeps the file exporter.
    served: dict[str, Any] = {}
    handlers: dict[int, Any] = {}
    monkeypatch.setattr(entrypoint.uvicorn, "run", lambda app, **options: served.update(options, app=app))
    monkeypatch.setattr(entrypoint.signal, "signal", lambda signum, handler: handlers.update({signum: handler}))
    monkeypatch.setattr(tempfile, "tempdir", str(runtime_bundle["dir"]))  # where main writes the bundle
    runtime = support.environment(DOCKERFILE)["RUNTIME"]  # what the image sets itself
    for name, value in support.contract(runtime).items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("PORT", raising=False)
    assert entrypoint.main([]) == 0
    assert (served["host"], served["port"]) == ("0.0.0.0", 8088)
    assert handlers == {signal.SIGTERM: entrypoint.adapter.exit_cleanly}
    start = json.loads([line for line in capsys.readouterr().err.splitlines() if line.startswith("{")][-1])
    assert (start["ca_roots"], start["ca_base"]) == (str(runtime_bundle["roots"]), str(runtime_bundle["runtime"]))
    assert os.environ["SSL_CERT_FILE"] == str(runtime_bundle["dir"] / "runtime-ca-bundle.pem")
    with support.client_for(served["app"]) as http:
        assert http.get("/readiness").status_code == 200
        assert http.post("/api/reasoning_engine", json={"class_method": "query", "input": {}}).status_code == 404


@needs_ch05
@pytest.mark.parametrize("roots", ["missing.pem", "empty.pem"])
def test_the_entry_point_refuses_to_start_with_a_roots_file_it_cannot_use(
        entrypoint: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str], roots: str) -> None:
    (tmp_path / "empty.pem").write_text("", encoding="utf-8")
    monkeypatch.setenv(ca_bundle.ROOTS_ENV, str(tmp_path / roots))
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    for name in ca_bundle.VARIABLES:
        monkeypatch.delenv(name, raising=False)  # restored afterwards, whatever the entry point sets
    with pytest.raises(SystemExit) as exc:
        entrypoint.trust_bundle()
    assert exc.value.code == 2
    assert "refusing to start: the CA bundle can't be built" in capsys.readouterr().err


@needs_ch05
def test_one_question_end_to_end_on_foundrys_routes(entrypoint: ModuleType, mcp_server: dict[str, Any],
                                                    trace_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-master-key-the-image-must-not-send")
    env = support.contract("foundry", MCP_URL=mcp_server["url"])
    seen: list[dict[str, Any]] = []
    log = io.StringIO()
    app = entrypoint.build_app(entrypoint.read_settings(env), client=httpx.Client(transport=support.play_gateway(seen)),
                               log=log)
    trace_id, caller = entrypoint.tracing.new_trace_id(), "b7ad6b7169203331"
    with support.client_for(app) as http:
        ready = http.get("/readiness")  # Foundry's health probe
        response = http.post("/invocations", json={"message": QUESTION},
                             headers={"traceparent": f"00-{trace_id}-{caller}-01"})
    assert ready.status_code == 200
    assert response.status_code == 200
    assert response.json() == {"output": ANSWER}
    support.check_one_run(entrypoint.tracing, env, seen, log, mcp_server["log"], trace_file, trace_id, caller)


@needs_ch05
@needs_tls_tools
def test_after_a_rotation_the_next_question_still_verifies(entrypoint: ModuleType, mcp_server: dict[str, Any],
                                                           trace_file: Path, runtime_bundle: dict[str, Any]) -> None:
    """The egress proxy's CA rotates between two questions. The entry point refreshes the bundle
    before the second, and the model calls, real TLS connections from GatewayModel, still verify."""
    folder, runtime = runtime_bundle["dir"], runtime_bundle["runtime"]
    trust = ca_bundle.TrustBundle.from_environment(combined=folder / "runtime-ca-bundle.pem")
    assert trust is not None and trust.refresh()
    with tls_server(Gateway, issue(runtime_bundle["proxy"], folder, "gateway-through-the-proxy")) as gateway:
        url = f"https://127.0.0.1:{gateway.server_port}"
        env = support.contract("foundry", GATEWAY_URL=f"{url}/v1", MCP_URL=mcp_server["url"])
        log = io.StringIO()
        app = entrypoint.build_app(entrypoint.read_settings(env), log=log, trust=trust)  # no mock: real TLS
        with support.client_for(app) as http:
            first = http.post("/invocations", json={"message": QUESTION})
            rotated = make_ca("Foundry egress proxy, rotated (test)")
            write_cas(runtime, rotated)  # the runtime rotates its bundle...
            gateway.use(issue(rotated, folder, "gateway-through-the-rotated-proxy"))  # ...and the proxy its certificate
            with pytest.raises(httpx.ConnectError):
                httpx.post(f"{url}/v1/chat/completions", json={})  # the bundle as it stood before the question
            second = http.post("/invocations", json={"message": QUESTION})
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == {"output": ANSWER}
    assert "ca_bundle_kept" not in log.getvalue()


@needs_ch05
def test_sigterm_after_readiness_stops_the_process_cleanly_and_its_spans_still_leave() -> None:
    result, received = support.serve_then_sigterm("foundry", "/readiness")
    assert result.returncode == 0, result.stderr
    assert "probe 200" in result.stdout  # GET /readiness, as Foundry's health probe sends it
    assert "/v1/traces" in received  # the span queued before SIGTERM was flushed on the way out
    start = [json.loads(line) for line in result.stderr.splitlines() if line.startswith("{")][0]
    assert (start["event"], start["runtime"]) == ("adapter_start", "foundry")
    assert "Traceback" not in result.stderr
