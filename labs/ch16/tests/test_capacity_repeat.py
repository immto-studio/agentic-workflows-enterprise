"""What stops a run repeated after a failover from repeating a write, with W3's own code and nothing in W3 changed:
the run's store for the same run, the approval service's binding of a yes to one run and one apply for any other
attempt, and a person's fresh yes for a new run. The approval service runs on 127.0.0.1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import repeat_write

LAB = Path(__file__).resolve().parents[1]
DRILLS = LAB / "results" / "2026-11-03" / "capacity" / "drills.json"


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    return repeat_write.check(tmp_path_factory.mktemp("repeat"))


def rows(result) -> dict[str, dict]:
    return {row["case"]: row for row in result["rows"]}


def test_the_first_run_writes_once_and_dies_before_recording_it(result):
    first = rows(result)["run A writes under its approval, and its pod is lost before it records the result"]
    assert first["write_ran"] and (first["generation_before"], first["generation_after"]) == (1, 2)
    assert first["reason"] == "the process died after the write"


def test_the_same_run_resumed_verifies_instead_of_writing(result):
    resumed = rows(result)["run A resumed by a new harness process, its store intact"]
    assert not resumed["write_ran"] and resumed["stopped_by"] == "W3's store"
    assert "marked started" in resumed["reason"] and resumed["reason"].endswith("done after verifying")


def test_a_second_run_cant_borrow_the_first_runs_yes(result):
    borrowed = rows(result)["run B presents run A's approval"]
    assert not borrowed["write_ran"] and borrowed["stopped_by"] == "the approval service"
    assert borrowed["reason"] == "the approval is for another run"


def test_the_first_runs_yes_applies_once_even_without_its_store(result):
    again = rows(result)["run A's approval presented again, by a harness that lost run A's store"]
    assert not again["write_ran"] and again["reason"] == "already applied"


def test_a_second_run_writes_only_after_a_person_approves_its_own_request(result):
    pending = rows(result)["run B presents its own approval before anyone has decided"]
    assert not pending["write_ran"] and pending["reason"] == "the approval is pending"
    approved = rows(result)["a person approves run B's own request"]
    assert approved["write_ran"] and (approved["generation_before"], approved["generation_after"]) == (2, 3)
    assert result["restarts"] == 2 and result["approvals"] == {"run A": "approved", "run B": "approved"}


def test_the_approval_service_recorded_every_refusal(result):
    refused = [c for c in result["approval_checks"] if not c["covers"]]
    assert {(c["approval"], c["trace"], c["reason"]) for c in refused} == {
        ("run A", "run B", "the approval is for another run"), ("run A", "run A", "already applied"),
        ("run B", "run B", "the approval is pending")}


def test_the_drills_recorded_the_same_cases(result):
    recorded = json.loads(DRILLS.read_text(encoding="utf-8"))["repeat"]
    assert [(r["case"], r["write_ran"], r["stopped_by"], r["reason"]) for r in recorded["rows"]] == [
        (r["case"], r["write_ran"], r["stopped_by"], r["reason"]) for r in result["rows"]]
