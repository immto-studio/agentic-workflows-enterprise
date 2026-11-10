"""The golden set: well-formed, 100 percent with the fake model, and failures are counted."""

from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

import pytest

import run_golden
from conftest import GOLDEN_SUMMARY
from server import LOCK_PATH, read_lock

pytestmark = pytest.mark.anyio


def test_golden_set_is_well_formed() -> None:
    cases = run_golden.load_cases()
    assert len(cases) == 20
    assert len({case["id"] for case in cases}) == 20
    tools_in_lock = set(read_lock(LOCK_PATH))
    used = {case["expect"]["tool"] for case in cases if case["expect"].get("tool")}
    assert used == tools_in_lock == {"get_pod_status", "get_recent_alerts"}  # both tools covered, nothing else
    assert any(not case["expect"].get("tool") for case in cases)  # and one case where no tool is the right call


async def test_golden_set_passes_with_the_fake_model(request: pytest.FixtureRequest) -> None:
    report = await run_golden.run_golden()
    request.config.stash[GOLDEN_SUMMARY] = report.summary()
    print("\n" + "\n".join(report.lines()))
    failures = [f"{r.id}: {r.reason}" for r in report.results if not r.passed]
    assert report.pass_rate == 1.0, "\n".join(failures)


async def test_a_wrong_expectation_lowers_the_pass_rate() -> None:
    cases = copy.deepcopy(run_golden.load_cases())
    cases[0]["expect"]["answer"] = "claims-api has 3 of 3 pods ready."
    cases[1]["expect"]["args"] = {"service": "quote-engine"}  # right answer text, wrong tool call
    report = await run_golden.run_golden(cases=cases)
    assert report.passed == 18 and report.pass_rate == pytest.approx(0.9)
    assert "answer" in report.results[0].reason and "tool calls" in report.results[1].reason


def test_cli_reports_the_pass_rate(tmp_path: Path) -> None:
    report_file = tmp_path / "report.json"
    result = subprocess.run([sys.executable, str(Path(run_golden.__file__)), "--json", str(report_file)],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "pass rate: 20/20 (100.0%)"
    assert result.stdout.count("PASS  ") == 20
    assert report_file.exists()
