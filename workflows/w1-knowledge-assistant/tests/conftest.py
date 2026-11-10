"""Shared fixtures for W1's tests: the corpus chunked both ways, the golden questions, the personas, the tables."""

from __future__ import annotations

import inspect
import json
import os
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest
import yaml

W1 = Path(__file__).resolve().parents[1]
for folder in ("ingest", "store", "knowledge-server", "knowledge-server/membership"):
    sys.path.insert(0, str(W1 / folder))

import ingest  # noqa: E402
import sync  # noqa: E402
from group_map import load as load_group_map  # noqa: E402

CORPUS = W1 / "corpus"
MEMBERSHIP = W1 / "knowledge-server" / "membership"
EXPORT = json.loads((MEMBERSHIP / "graph-export.json").read_text(encoding="utf-8"))
DELTA = json.loads((MEMBERSHIP / "graph-delta.json").read_text(encoding="utf-8"))
GROUPS = load_group_map()
# Persona -> object ID, from the users the Graph stand-in lists.
USERS = {upn.split("@")[0]: oid for upn, oid in sync.users(EXPORT).items()}
# The golden set's persona: an on-call platform engineer (corpus README, "Golden questions").
ON_CALL = frozenset({"lm-all-staff", "lm-eng-all", "lm-platform-oncall"})
SECRET = "lab-secret-for-tests-at-least-32-bytes"
AUDIT_KEY = "w1-audit-hmac-key-for-tests-at-least-32-bytes"  # AUDIT_HMAC_KEY, fixed for the tests
MEMBER_OF ={"lm-vault-break-glass": "vault.custodian", "lm-pci-cde-operators": "pci.operator",
             "lm-sec-incident-response": "incident.responder", "lm-ea-leads": "ea.lead",
             "lm-legal-regulatory": "regulatory.liaison"}


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text)


def fresh_table(now: datetime | None = None) -> dict:
    """Tonight's rebuild and today's delta, stamped now: a table the server treats as current."""
    now = now or datetime.now(timezone.utc)
    stamp = (now - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    table, _ = sync.rebuild(EXPORT, GROUPS, stamp)
    return sync.apply_delta(table, DELTA, stamp)


def printable(function, lines: int = 40, columns: int = 70) -> None:
    """The book prints this function with callouts: it has to fit."""
    source = inspect.getsource(function).splitlines()
    assert len(source) <= lines, f"{function.__name__}: {len(source)} lines"
    wide = [line for line in source if len(line) > columns]
    assert not wide, f"{function.__name__}: {wide}"


@pytest.fixture(scope="session")
def fixed():
    chunks, refusals = ingest.ingest(variant="fixed")
    assert not refusals
    return chunks


@pytest.fixture(scope="session")
def heading():
    chunks, refusals = ingest.ingest(variant="heading")
    assert not refusals
    return chunks


@pytest.fixture(scope="session")
def golden() -> list[dict]:
    return yaml.safe_load((CORPUS / "golden-questions.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def restricted_docs() -> set[str]:
    manifest = yaml.safe_load((CORPUS / "manifest.yaml").read_text(encoding="utf-8"))
    return set(manifest["traps"]["access"])


def member(question: dict) -> frozenset[str]:
    """The on-call engineer who also holds the question's required group."""
    return ON_CALL | {question["required_access_group"]}


# --- the knowledge server as a process, and a stand-in for the gateway ----------------------------

GATEWAY_KEY = "sk-test-gateway"
FAIL_EMBEDDING = "the embedding call fails for this question"  # the stand-in answers it with a 500
SLOW_EMBEDDING = "the embedding call takes three seconds"
FAIL_CHAT = "the model call fails for this question"
STUBBORN = "(keep searching)"  # the stand-in model asks for a search even when it's offered no tool
SERVER_PY = W1 / "knowledge-server" / "server.py"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def question_vectors() -> dict:
    data = np.load(W1 / "index" / "qwen3-embedding-0.6b" / "fixed.npz", allow_pickle=False)
    return {str(i): v for i, v in zip(data["question_ids"], data["questions"])}


@pytest.fixture(scope="session")
def fake_gateway(golden, question_vectors):
    """The gateway's two routes the lab uses: embeddings for the golden questions, and chat with a
    scripted model that searches with the question while it is offered a tool and answers once it
    isn't, unless the question asks it to keep searching, as gpt-oss does. Records every request."""
    from embedding import SERVED_MODEL, prefixes

    query_prefix, _ = prefixes(SERVED_MODEL)
    by_text = {query_prefix + q["question"]: question_vectors[q["id"]].tolist() for q in golden}
    seen: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append({"path": self.path, "auth": self.headers.get("Authorization"), **body})
            if self.path.endswith("/embeddings"):
                if any(SLOW_EMBEDDING in text for text in body["input"]):
                    time.sleep(3)
                    return self.reply(500, {"error": "too late"})
                if any(FAIL_EMBEDDING in text or text not in by_text for text in body["input"]):
                    return self.reply(500, {"error": "the embedding model is down"})
                return self.reply(200, {"data": [{"index": i, "embedding": by_text[text]}
                                                 for i, text in enumerate(body["input"])]})
            question = next(m["content"] for m in body["messages"] if m["role"] == "user")
            if FAIL_CHAT in question:
                return self.reply(500, {"error": "the model is down"})
            if body.get("tools") or STUBBORN in question:
                query = question.replace(STUBBORN, "").strip()
                message = {"role": "assistant", "content": None, "tool_calls": [{
                    "id": "call_1", "type": "function",
                    "function": {"name": "search_docs", "arguments": json.dumps({"query": query})}}]}
            else:
                message = {"role": "assistant", "content": "Nothing in the documents you can read answers this."}
            return self.reply(200, {"choices": [{"message": message}],
                                    "usage": {"prompt_tokens": 100, "completion_tokens": 10}})

        def reply(self, status: int, payload: dict) -> None:
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", free_port()), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", seen
    httpd.shutdown()


@pytest.fixture(scope="session")
def running_server(fake_gateway, tmp_path_factory):
    """server.py as a process, with a membership table rebuilt now. Yields its URL, log and table."""
    url, _ = fake_gateway
    port = free_port()
    folder = tmp_path_factory.mktemp("w1")
    log, table = folder / "server.log", folder / "table.json"
    sync.write_table(fresh_table(), table)
    env = {**os.environ, "TOOL_IDENTITY": "larkspur-knowledge-reader", "W1_TOKEN_SECRET": SECRET,
           "GATEWAY_URL": url, "GATEWAY_KEY": GATEWAY_KEY, "TOOL_LOG_FILE": str(log), "MEMBERSHIP_TABLE": str(table),
           "AUDIT_HMAC_KEY": AUDIT_KEY}
    stderr = (folder / "stderr.log").open("w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, str(SERVER_PY), "--port", str(port)], env=env,
                            stdout=subprocess.DEVNULL, stderr=stderr, text=True)
    deadline = time.time() + 60
    while time.time() < deadline:
        if proc.poll() is not None:
            stderr.close()
            pytest.fail(f"server exited: {(folder / 'stderr.log').read_text(encoding='utf-8')}")
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                break
        time.sleep(0.2)
    yield f"http://127.0.0.1:{port}/mcp", log, table
    proc.terminate()
    proc.wait(timeout=30)
    stderr.close()


def log_events(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
