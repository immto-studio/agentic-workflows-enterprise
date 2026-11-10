"""Shared fixtures for W5's tests: the four readers as processes, W5's membership table, the agent's token."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

W5 = Path(__file__).resolve().parents[1]
W1 = W5.parent / "w1-knowledge-assistant"
for folder in (W5 / "servers", W5 / "detect", W5 / "writer", W5 / "harness", W1 / "knowledge-server",
               W1 / "knowledge-server" / "membership"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import launch  # noqa: E402  (harness/launch.py: the readers as processes, the restamped table)
from common import W5_AGENT_OID, load_workspace_map, mint_app_token  # noqa: E402

SECRET = "w5-lab-secret-for-tests-at-least-32-bytes"
SERVERS = {"state": 4, "cloud": 4, "cost": 5, "policy": 2}  # name -> tools served
IDENTITY = launch.IDENTITY
fresh_table = launch.fresh_table
free_port = launch.free_port


def w5_token(oid: str = W5_AGENT_OID, **overrides) -> str:
    """The token W5's runtime gets for the servers through the client-credentials grant, minted by W5's
    own stand-in for Entra (servers/w5_access.mint_app_token): app-only, no user behind it, the app role
    Drift.Read in `roles`, W5's audience and client, the agent's service principal as subject. An override
    names a claim to get wrong on purpose (roles, client, audience, minutes, delegated)."""
    return mint_app_token(SECRET, oid, **overrides)


@pytest.fixture(scope="session")
def workspace_map():
    return load_workspace_map()


@pytest.fixture(scope="session")
def table_file(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("w5") / "membership.json"
    path.write_text(json.dumps(fresh_table(), indent=2), encoding="utf-8")
    return path


@pytest.fixture(scope="session")
def running_servers(table_file, tmp_path_factory):
    """The four readers as processes, each under its own identity. Yields name -> (url, log path)."""
    readers = launch.start_readers(tmp_path_factory.mktemp("w5-servers"), SECRET, table_file)
    yield {name: (readers.urls[f"{name}-mcp"], readers.logs[name]) for name in SERVERS}
    readers.stop()


def log_events(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
