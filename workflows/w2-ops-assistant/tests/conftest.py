"""Shared fixtures for W2's tests: the three servers as processes, W1's membership table, lab tokens."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

W2 = Path(__file__).resolve().parents[1]
W1 = W2.parent / "w1-knowledge-assistant"
for folder in (W2 / "servers", W1 / "knowledge-server", W1 / "knowledge-server" / "membership"):
    sys.path.insert(0, str(folder))

import sync  # noqa: E402
from access import issue  # noqa: E402
from common import W2_RUNTIME, W2_SCOPE, W2_SERVERS_APP, load_service_map  # noqa: E402
from group_map import load as load_group_map  # noqa: E402

MEMBERSHIP = W1 / "knowledge-server" / "membership"
EXPORT = json.loads((MEMBERSHIP / "graph-export.json").read_text(encoding="utf-8"))
DELTA = json.loads((MEMBERSHIP / "graph-delta.json").read_text(encoding="utf-8"))
GROUPS = load_group_map()
USERS = {upn.split("@")[0]: oid for upn, oid in sync.users(EXPORT).items()}
SECRET = "w2-lab-secret-for-tests-at-least-32-bytes"
AUDIT_KEY = "w2-audit-hmac-key-for-tests-at-least-32-bytes"  # AUDIT_HMAC_KEY, fixed for the tests
SERVERS ={"kubernetes": 4, "metrics": 1, "logs": 1}  # name -> tools served


def fresh_table(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    stamp = (now - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    table, _ = sync.rebuild(EXPORT, GROUPS, stamp)
    return sync.apply_delta(table, DELTA, stamp)


def w2_token(user: str, **overrides) -> str:
    """A token shaped like the one W2's runtime gets for the servers through the on-behalf-of exchange.
    An override names a claim to get wrong on purpose (client, scope, audience, minutes)."""
    shape = {"scope": W2_SCOPE, "client": W2_RUNTIME, "audience": W2_SERVERS_APP, **overrides}
    return issue(SECRET, USERS[user], f"{user}@larkspur.example", **shape)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def service_map():
    return load_service_map()


@pytest.fixture(scope="session")
def table_file(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("w2") / "table.json"
    sync.write_table(fresh_table(), path)
    return path


@pytest.fixture(scope="session")
def running_servers(table_file, tmp_path_factory):
    """The three servers as processes, each under its own identity. Yields name -> (url, log path)."""
    folder = tmp_path_factory.mktemp("w2-servers")
    procs, out = [], {}
    for name in SERVERS:
        port = free_port()
        log = folder / f"{name}.log"
        env = {**os.environ, "TOOL_IDENTITY": f"larkspur-ops-{name}-reader", "W2_TOKEN_SECRET": SECRET,
               "TOOL_LOG_FILE": str(log), "MEMBERSHIP_TABLE": str(table_file), "AUDIT_HMAC_KEY": AUDIT_KEY}
        stderr = (folder / f"{name}.stderr").open("w", encoding="utf-8")
        proc = subprocess.Popen([sys.executable, str(W2 / "servers" / f"{name}_server.py"), "--port", str(port)],
                                env=env, stdout=subprocess.DEVNULL, stderr=stderr, text=True)
        procs.append((proc, stderr, folder / f"{name}.stderr"))
        out[name] = (f"http://127.0.0.1:{port}/mcp", log, port)
    deadline = time.time() + 60
    for name, (_, _, port) in out.items():
        while time.time() < deadline:
            proc, stderr, path = next(p for p in procs if p[2].stem == name)
            if proc.poll() is not None:
                stderr.close()
                pytest.fail(f"{name} server exited: {path.read_text(encoding='utf-8')}")
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.2)
    yield {name: (url, log) for name, (url, log, _) in out.items()}
    for proc, stderr, _ in procs:
        proc.terminate()
        proc.wait(timeout=30)
        stderr.close()


def log_events(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
