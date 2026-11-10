"""vet.py over the three servers and the fourth, misleading one: a clean report for each real server,
the lock mismatch, the missing catalog entry, the misleading read-only hint, and the authentication probe."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time

import pytest

from conftest import SECRET, W2, free_port

sys.path.insert(0, str(W2))
import vet  # noqa: E402

HERE = W2 / "tests"


@pytest.fixture(scope="session")
def misleading_server(table_file, tmp_path_factory):
    """tests/misleading_server.py as a process, its lock written first. Yields its URL."""
    folder = tmp_path_factory.mktemp("w2-misleading")
    lock = folder / "secrets.lock.json"
    env = {**os.environ, "TOOL_IDENTITY": "larkspur-ops-secrets-rotator", "W2_TOKEN_SECRET": SECRET,
           "TOOL_LOG_FILE": str(folder / "secrets.log"), "MEMBERSHIP_TABLE": str(table_file)}
    script = str(HERE / "misleading_server.py")
    written = subprocess.run([sys.executable, script, "--write-lock", "--lock", str(lock)], env=env,
                             capture_output=True, text=True, timeout=120)
    assert written.returncode == 0, written.stderr
    port = free_port()
    stderr = (folder / "secrets.stderr").open("w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, script, "--port", str(port), "--lock", str(lock)], env=env,
                            stdout=subprocess.DEVNULL, stderr=stderr, text=True)
    deadline = time.time() + 60
    while time.time() < deadline:
        if proc.poll() is not None:
            stderr.close()
            pytest.fail(f"misleading server exited: {(folder / 'secrets.stderr').read_text(encoding='utf-8')}")
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                break
        time.sleep(0.2)
    yield f"http://127.0.0.1:{port}/mcp", lock
    proc.terminate()
    stderr.close()


def report_of(url: str, server: str, **options) -> dict:
    options.setdefault("catalog_path", vet.CATALOG_PATH)
    options.setdefault("lock_path", vet.LOCK_DIR / f"{server.removesuffix('-mcp')}.lock.json")
    options.setdefault("token", None)
    options.setdefault("probe_auth", False)
    return asyncio.run(vet.inspect(url, server, **options))


def test_each_real_server_vets_clean_and_read_only(running_servers):
    for name, (url, _) in running_servers.items():
        report = report_of(url, f"{name}-mcp")
        assert report["findings"] == [], (name, report["findings"])
        assert report["identity"]["read_only"] and report["identity"]["identity"] == f"larkspur-ops-{name}-reader"
        assert report["transport"] == "streamable-http" and report["protocol_version"]
        assert "tools" in report["capabilities"]
        for tool in report["tools"]:
            assert tool["lock"]["state"] == "matches"
            assert tool["annotations"]["readOnlyHint"] == {"value": True, "source": "stated"}
            assert tool["annotations"]["destructiveHint"] == {"value": False, "source": "stated"}
            assert tool["catalog"]["listed"] and tool["catalog"]["server"] == f"{name}-mcp"


def test_a_read_only_hint_on_a_writing_identity_is_flagged(misleading_server):
    url, lock = misleading_server
    report = report_of(url, "secrets-mcp", catalog_path=HERE / "vet-catalog.yaml", lock_path=lock)
    (tool,) = report["tools"]
    assert tool["annotations"]["readOnlyHint"]["value"] is True  # what the server says
    assert tool["lock"]["state"] == "matches"  # the lock pins the lie faithfully; it isn't the lock's job
    # what the identity can do: a secret's value is a write in chapter 4's sense, whatever the verb says
    assert report["identity"]["writes"] == ["secretsmanager:GetSecretValue", "secretsmanager:RotateSecret"]
    assert any("readOnlyHint is true" in f and "secretsmanager:RotateSecret" in f for f in report["findings"])


def test_a_changed_description_is_a_lock_mismatch(running_servers, tmp_path):
    url, _ = running_servers["metrics"]
    lock = json.loads((vet.LOCK_DIR / "metrics.lock.json").read_text(encoding="utf-8"))
    lock["tools"]["query_metric"]["sha256"] = "0" * 64
    edited = tmp_path / "metrics.lock.json"
    edited.write_text(json.dumps(lock), encoding="utf-8")
    report = report_of(url, "metrics-mcp", lock_path=edited)
    assert report["tools"][0]["lock"]["state"] == "MISMATCH"
    assert any(f.startswith("query_metric: served definition") for f in report["findings"])


def test_a_tool_the_catalog_doesnt_list_is_a_finding(running_servers):
    url, _ = running_servers["logs"]
    report = report_of(url, "logs-mcp", catalog_path=HERE / "vet-catalog.yaml")
    assert "server logs-mcp is not in the catalog" in report["findings"]
    assert "search_logs: not in the catalog" in report["findings"]


def test_the_probe_shows_the_actor_token_is_required(running_servers):
    url, _ = running_servers["kubernetes"]
    report = report_of(url, "kubernetes-mcp", probe_auth=True)
    auth = report["authentication"]
    assert auth["probed"] and auth["refused"] and "x-larkspur-actor" in auth["text"].lower()
    assert report["findings"] == []  # a refusal is the right answer


def test_a_secret_or_parameter_read_counts_as_a_write():
    assert not vet.is_read_action("secretsmanager:GetSecretValue")
    assert not vet.is_read_action("ssm:GetParametersByPath")
    assert vet.is_read_action("logs:GetLogEvents") and vet.is_read_action("eks:DescribeCluster")


def test_the_defaults_fill_in_what_a_server_leaves_out():
    hints = vet.hints_of({"name": "x", "annotations": {"readOnlyHint": True}})
    assert hints["readOnlyHint"] == {"value": True, "source": "stated"}
    assert hints["destructiveHint"] == {"value": True, "source": "default"}
    assert hints["openWorldHint"] == {"value": True, "source": "default"}
    bare = vet.hints_of({"name": "y"})
    assert all(h["source"] == "default" for h in bare.values()) and bare["readOnlyHint"]["value"] is False


def test_the_command_line_prints_the_report_and_exits_on_findings(running_servers, misleading_server, capsys):
    url, _ = running_servers["kubernetes"]
    assert vet.main([url, "--server", "kubernetes-mcp"]) == 0
    out = capsys.readouterr().out
    assert "tool get_pod_status" in out and "readOnlyHint=True" in out and "findings: none" in out
    bad_url, lock = misleading_server
    assert vet.main([bad_url, "--server", "secrets-mcp", "--catalog", str(HERE / "vet-catalog.yaml"),
                     "--lock", str(lock), "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["findings"] and report["identity"]["writes"] == ["secretsmanager:GetSecretValue",
                                                                  "secretsmanager:RotateSecret"]
