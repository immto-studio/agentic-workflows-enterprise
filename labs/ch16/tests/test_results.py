"""The committed results are what the report writes, two reports write the same bytes, the README's tables
are the summary's, and nothing leaves the machine."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

import offline
import report

LAB = Path(__file__).resolve().parents[1]
FILES = ["costlines.jsonl", "ledger-summary.md", "ledger.json"]
STEP3 = "## The Collector (step 3)"  # the README's section whose tables are the Collector run's summary's
STEP3B = "## The workflows through the Collector (step 3b)"  # and the one whose tables are step 3b's summary's
STEP4 = "## Budgets and switches (step 4)"  # step 4's tables are its own summary's (tests/test_budget_results.py)
STEP5 = "## Capacity and continuity (step 5)"  # and step 5's (tests/test_capacity_results.py)
STEP5B = "## The store, the retries and W3's fallback (step 5b)"  # and step 5b's (tests/test_capacity_5b_results.py)
STEP6 = "## SLOs, the simulated month, the alerts and the playbook (step 6)"  # and step 6's (tests/test_slo_results.py)
STEP7 = "## The cloud session (step 7)"  # and step 7's (tests/test_cloud_results.py)
STEP8 = "## The model register and the upgrade path (step 8)"  # and step 8's (tests/test_lifecycle_results.py)
STEP9 = "## The monthly review (step 9)"  # and step 9's are the review's (tests/test_review_results.py)


def committed() -> Path:
    """The newest results folder that holds the ledger; step 5b's folder holds capacity results only."""
    return sorted(p for p in (LAB / "results").iterdir() if p.is_dir() and (p / "ledger.json").is_file())[-1]


def readme_rows() -> tuple[list[str], list[str], list[str]]:
    """The README's table rows: the ledger's, those of step 3's section (tests/test_collector_results.py), and those
    of step 3b's (tests/test_workflows.py). Step 4's, step 5's, step 5b's, step 6's, step 7's, step 8's and step 9's
    are left out; tests/test_budget_results.py, tests/test_capacity_results.py, tests/test_capacity_5b_results.py,
    tests/test_slo_results.py, tests/test_cloud_results.py, tests/test_lifecycle_results.py and
    tests/test_review_results.py read them."""
    readme = (LAB / "README.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    ledger, collector, workflows, elsewhere, section = [], [], [], [], ""
    for line in readme.splitlines():
        if line.startswith("## "):
            section = line
        if line.startswith("|") and not line.startswith("|---"):
            (collector if section == STEP3 else workflows if section == STEP3B
             else elsewhere if section in (STEP4, STEP5, STEP5B, STEP6, STEP7, STEP8, STEP9) else ledger).append(line)
    return ledger, collector, workflows


def test_the_committed_results_are_what_the_report_writes(runs, tmp_path: Path) -> None:
    report.write(tmp_path, runs)
    # the folder also holds step 3's results, in collector/
    assert sorted(p.name for p in tmp_path.iterdir()) == FILES == sorted(p.name for p in committed().iterdir() if p.is_file())
    for name in FILES:
        fresh = (tmp_path / name).read_text(encoding="utf-8")
        assert fresh == (committed() / name).read_text(encoding="utf-8").replace("\r\n", "\n"), name


def test_two_reports_write_the_same_bytes(tmp_path: Path) -> None:
    """Two processes, each with its own hash seed, so no set's order reaches a file."""
    outs = []
    for seed in ("1", "2"):
        out = tmp_path / f"run-{seed}"
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
        subprocess.run([sys.executable, str(LAB / "ledger" / "report.py"), "--out", str(out)], check=True, env=env,
                       capture_output=True, cwd=str(LAB))
        outs.append(out)
    for name in FILES:
        assert (outs[0] / name).read_bytes() == (outs[1] / name).read_bytes(), name


def test_the_readmes_tables_are_the_summarys() -> None:
    summary = (committed() / "ledger-summary.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    rows, _, _ = readme_rows()
    assert len(rows) >= 20
    for row in rows:
        assert row in summary.splitlines(), row


def test_the_network_is_blocked_and_loopback_is_not() -> None:
    with pytest.raises(offline.NetworkBlocked):
        socket.create_connection(("192.0.2.1", 443), timeout=1)
    with pytest.raises(offline.NetworkBlocked):
        socket.getaddrinfo("raw.githubusercontent.com", 443)
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    try:
        client = socket.create_connection(server.getsockname(), timeout=1)
        client.close()
    finally:
        server.close()
