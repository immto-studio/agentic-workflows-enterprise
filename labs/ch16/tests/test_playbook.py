"""The misbehaving-agent playbook (O-D13): every symptom the plan names, its signal tied to what the lab emits or
marked as missing, the four levers with who pulls them and the record each leaves, and the runbook in step."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

import oncall

LAB = Path(__file__).resolve().parents[1]
COMPANION = LAB.parents[1]
PLAYBOOK = yaml.safe_load((LAB / "playbook" / "playbook.yaml").read_text(encoding="utf-8"))
RUNBOOK = (LAB / "playbook" / "runbook.md").read_text(encoding="utf-8")
SYMPTOMS = ["a loop that exhausts its step budget", "a cost spike", "a run of refusals or tool errors",
            "a planted text restated", "a denied egress", "confident wrong answers reported by people",
            "a provider outage", "a model that changed under its alias"]


def test_every_symptom_of_o_d13_has_a_row():
    assert [row["symptom"] for row in PLAYBOOK["symptoms"]] == SYMPTOMS


def test_every_row_has_a_signal_two_levers_and_says_what_isnt_emitted():
    for row in PLAYBOOK["symptoms"]:
        assert row["signal"] and row["alert"], row["symptom"]
        assert row["first_lever"] in PLAYBOOK["levers"] and row["second_lever"] in PLAYBOOK["levers"], row["symptom"]
        assert row["emitted"] in ("yes", "partly", "no"), row["symptom"]
        if row["emitted"] != "yes":
            assert row["not_emitted"], row["symptom"]
    assert [row["symptom"] for row in PLAYBOOK["symptoms"] if row["emitted"] == "no"] == ["a denied egress"]


def test_the_four_levers_each_with_its_record_and_the_on_call_lead():
    assert list(PLAYBOOK["levers"]) == ["rate", "remap", "rung", "kill"]
    for lever in PLAYBOOK["levers"].values():
        assert lever["name"] and lever["what"] and lever["command"] and lever["record"]
    assert "Tomasz's rota" in PLAYBOOK["who"] and "ch02:163" in PLAYBOOK["authority"]
    assert oncall.DOCUMENT_WITHIN.total_seconds() == 24 * 3600 and oncall.REVIEW == "the next board meeting"


def test_the_commands_the_levers_name_are_the_labs():
    for name in ("rung", "kill"):
        command = PLAYBOOK["levers"][name]["command"]
        assert command.startswith(f"python budget/oncall.py {name} ")
    source = (LAB / "budget" / "oncall.py").read_text(encoding="utf-8")
    assert '"kill", "reopen", "rung", "restore-rung"' in source
    assert "def update(" in (LAB / "budget" / "keys.py").read_text(encoding="utf-8")


def test_every_file_and_alert_the_playbook_names_exists():
    text = (LAB / "playbook" / "playbook.yaml").read_text(encoding="utf-8")
    for path in sorted(set(re.findall(r"(?:labs/ch1[56]/|budget/|slo/|capacity/)[\w/.-]+\.(?:py|yaml)", text))):
        where = COMPANION / path if path.startswith("labs/") else LAB / path
        assert where.exists(), path
    alerts = yaml.safe_load((LAB / "slo" / "alerts.yaml").read_text(encoding="utf-8"))
    names = {r["name"] for r in alerts["burn_rate"]["rules"]}
    for name in re.findall(r"(fast-burn-1h|fast-burn-6h|slow-burn-3d)", text):
        assert name in names


def test_the_runbook_takes_every_symptom_and_every_lever_with_its_command():
    for symptom in SYMPTOMS:
        assert symptom in RUNBOOK.lower(), symptom
    for name in ("rung", "kill"):
        assert PLAYBOOK["levers"][name]["command"] in RUNBOOK
    assert "budget/identity.py pull" in RUNBOOK
