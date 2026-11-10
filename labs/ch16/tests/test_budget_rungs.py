"""The rung-down switch: an override only lowers, a file the harness can't fully read stops the run before any
call, and at a lowered rung a write tool is refused before it is called.

The harness is budget/rung_harness.py on chapter 1's loop, unchanged; the manifest is chapter 5's W3, at rung 3
with `restart_deployment` marked `writes: true`.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import oncall
import pytest
import rung_harness
import rungs
import yaml

LAB = Path(__file__).resolve().parents[1]
W3 = yaml.safe_load((LAB.parent / "ch05" / "manifest" / "w3-incident.yaml").read_text(encoding="utf-8"))
LEAD = "oncall.lead@larkspur.example"


def write(folder: Path, text: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "w3-incident.yaml").write_text(text, encoding="utf-8")


def test_no_override_keeps_the_manifests_rung_and_tools(tmp_path):
    plan = rungs.plan(W3, tmp_path)
    assert (plan.manifest_rung, plan.rung, plan.dropped, plan.note) == (3, 3, (), "no override")
    assert plan.allowed["restart_deployment"] == {"service"}


def test_an_override_lowers_the_rung_and_drops_every_write(tmp_path):
    write(tmp_path, "workflow: w3-incident\nrung: 1\nby: oncall.lead@larkspur.example\n")
    plan = rungs.plan(W3, tmp_path)
    assert plan.rung == 1
    assert plan.dropped == ("restart_deployment",)
    assert set(plan.allowed) == {"get_pod_status", "get_recent_alerts"}


@pytest.mark.parametrize("rung", [3, 4, 5])
def test_an_override_never_raises_a_rung(tmp_path, rung):
    write(tmp_path, f"workflow: w3-incident\nrung: {rung}\n")
    plan = rungs.plan(W3, tmp_path)
    assert plan.rung == 3 and plan.dropped == ()
    assert "ignored" in plan.note and "only lowers" in plan.note


@pytest.mark.parametrize("text, says", [
    ("workflow: w3-incident\nrung: 1\n  by: [\n", "not YAML"),
    ("- workflow: w3-incident\n- rung: 1\n", "not a mapping"),
    ("", "not a mapping"),
    ("workflow: w2-ops-assistant\nrung: 1\n", "names workflow"),
    ("rung: 1\n", "names workflow"),
    ("workflow: w3-incident\nrung: '1'\n", "not an integer"),
    ("workflow: w3-incident\nrung: one\n", "not an integer"),
    ("workflow: w3-incident\nrung: true\n", "not an integer"),
    ("workflow: w3-incident\nrung: 1.0\n", "not an integer"),
    ("workflow: w3-incident\nrung: 6\n", "not an integer"),
    ("workflow: w3-incident\nrung: -1\n", "not an integer"),
    ("workflow: w3-incident\n", "not an integer"),
    ("workflow: w3-incident\nrung: 1\nrnug: 1\n", "unknown key"),
    ("workflow: w3-incident\nrung: 1\nby: 7\n", "not text"),
])
def test_a_malformed_override_fails_closed(tmp_path, text, says):
    write(tmp_path, text)
    with pytest.raises(rungs.RungOverrideError, match=says):
        rungs.plan(W3, tmp_path)


def test_at_the_manifests_rung_the_write_reaches_its_tool(tmp_path):
    run = rung_harness.run("Restart claims-api", W3, tmp_path, rung_harness.RESTART)
    assert run["rung"] == 3 and run["tool_calls"] == {"restart_deployment": 1}
    assert run["answer"] == "Restarted claims-api."


def test_at_a_lowered_rung_the_write_is_refused_before_it_is_called(tmp_path):
    oncall.lower_rung("w3-incident", 1, manifest_rung=3, by=LEAD, change="EC-TEST", reason="test", folder=tmp_path)
    run = rung_harness.run("Restart claims-api", W3, tmp_path / "rungs", rung_harness.RESTART)
    assert run["rung"] == 1 and run["dropped"] == ["restart_deployment"]
    assert run["answer"] == "Refused: restart_deployment is not an allowed call."
    assert run["tool_calls"] == {}                    # the fake restart never ran
    assert "restart_deployment" not in run["offered"]  # nor was the model offered it
    assert run["model_calls"] == 1


def test_reads_still_run_at_the_lowered_rung(tmp_path):
    oncall.lower_rung("w3-incident", 1, manifest_rung=3, by=LEAD, change="EC-TEST", reason="test", folder=tmp_path)
    run = rung_harness.run("Is claims-api healthy?", W3, tmp_path / "rungs", rung_harness.READ)
    assert run["tool_calls"] == {"get_pod_status": 1}
    assert run["answer"] == "claims-api has 2 of 3 pods ready."


@pytest.mark.parametrize("text", ["workflow: w3-incident\nrung: one\n", "workflow: w3-incident\nrung: 1\n  by: [\n"])
def test_a_malformed_file_stops_the_run_before_any_call(tmp_path, text):
    write(tmp_path, text)
    run = rung_harness.run("Is claims-api healthy?", W3, tmp_path, rung_harness.READ)
    assert run["started"] is False
    assert (run["model_calls"], run["tool_calls"]) == (0, {})


def test_lower_rung_refuses_to_raise_and_records_each_change(tmp_path):
    at = datetime(2026, 11, 3, 23, 40, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="only lowers"):
        oncall.lower_rung("w3-incident", 3, manifest_rung=3, by=LEAD, change="EC-1", reason="x", folder=tmp_path)
    oncall.lower_rung("w3-incident", 1, manifest_rung=3, by=LEAD, change="EC-1", reason="planted line", folder=tmp_path,
                      now=at)
    oncall.lower_rung("w3-incident", None, manifest_rung=3, by=LEAD, change="EC-1", reason="review done",
                      folder=tmp_path, now=at + timedelta(hours=5))
    assert not (tmp_path / "rungs" / "w3-incident.yaml").exists()
    lines = [json.loads(line) for line in (tmp_path / "changes.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(c["lever"], c["from"], c["to"]) for c in lines] == [
        ("rung down", "manifest (3)", 1), ("rung restored", 1, "manifest (3)")]
    first = lines[0]
    assert first["kind"] == "emergency" and first["authority"] == "on-call lead" and first["by"] == LEAD
    assert first["document_by"] == "2026-11-04T23:40:00.000+00:00"  # within twenty-four hours, ch02:163
    assert first["review"] == "the next board meeting"


def test_the_override_is_written_whole(tmp_path):
    path = rungs.write_override(tmp_path, "w3-incident", 1, by=LEAD, at="2026-11-03T23:40:00+00:00",
                                change="EC-1", reason="test")
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["rung"] == 1
    assert [p.name for p in tmp_path.iterdir()] == ["w3-incident.yaml"]  # no temporary file left behind
    assert rungs.plan(W3, tmp_path).rung == 1
