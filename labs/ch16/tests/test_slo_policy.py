"""Step 6's error-budget policy: budgets in events, when each is spent, the freeze, and the rung down through step
4's rung switch in a dry run."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import budget_policy
import registry
import rungs
import slis

LAB = Path(__file__).resolve().parents[1]


def test_the_policy_names_who_decides_and_the_record_of_every_action():
    policy = budget_policy.load()
    actions = {a["id"]: a for a in policy["actions"]}
    assert list(actions) == ["freeze", "rung-down", "incident"]
    for a in actions.values():
        assert a["when"] and a["what"] and a["decided_by"] and a["record"], a["id"]
    assert "ch02:163" in actions["rung-down"]["decided_by"]
    assert "budget/oncall.py" in actions["rung-down"]["record"]
    text = (LAB / "slo" / "policy.yaml").read_text(encoding="utf-8")
    assert '"This policy is not intended to serve as a punishment for missing SLOs"' in " ".join(text.split())


def test_a_budget_is_one_minus_the_target_times_the_events_expected():
    slos = slis.load()
    expected = {w: {s: 1000.0 for s in slis.SLI_NAMES} for w in slis.WORKFLOWS}
    b = budget_policy.budgets(slos, expected)
    assert b["w2"] == {"success": pytest.approx(5.0), "latency": pytest.approx(50.0)}
    assert b["w3"]["outcome"] == pytest.approx(100.0) and "outcome" not in b["w1"]


def test_a_budget_is_spent_at_the_bad_event_that_reaches_it():
    events = [slis.RunEvent("w4", f"r{i}", "error" if i in (3, 7) else "proposal", 1.0, at=float(i)) for i in range(10)]
    account = budget_policy.spent(events, "success", 1.97, None)
    assert (account["bad"], account["valid"], account["spent_at"]) == (2, 10, 7.0)
    assert budget_policy.spent(events, "success", 2.5, None)["spent_at"] is None
    assert budget_policy.spent(events, "success", 1.0, None, begin=5.0)["bad"] == 1  # the lead-in counts in no budget
    assert budget_policy.spent(events, "success", 1.0, None, end=7.0)["bad"] == 1  # nor does the next month


def test_an_outcome_counts_in_the_month_a_person_decided_it_in():
    """slos.yaml, in_the_month: a run counts when it ends and an outcome when a person decides, so a lead-in proposal
    decided inside the month counts, and a proposal decided after the month's end counts in the next month."""
    lead_in = slis.RunEvent("w4", "lead", "proposal", 1.0, at=-50.0, decision="rejected", decided_at=20.0)
    late = slis.RunEvent("w4", "late", "proposal", 1.0, at=80.0, decision="rejected", decided_at=120.0)
    inside = slis.RunEvent("w4", "in", "proposal", 1.0, at=30.0, decision="accepted", decided_at=60.0)
    undecided = slis.RunEvent("w4", "open", "proposal", 1.0, at=40.0)
    month = budget_policy.spent([lead_in, late, inside, undecided], "outcome", 1.0, None, begin=0.0, end=100.0)
    assert (month["valid"], month["bad"], month["spent_at"]) == (2, 1, 20.0)
    runs = budget_policy.spent([lead_in, late, inside, undecided], "success", 1.0, None, begin=0.0, end=100.0)
    assert runs["valid"] == 3  # the late proposal's run ended in the month; the lead-in's didn't
    following = budget_policy.spent([lead_in, late, inside, undecided], "outcome", 1.0, None, begin=100.0, end=200.0)
    assert (following["valid"], following["bad"], following["spent_at"]) == (1, 1, 120.0)


def test_spending_the_outcome_budget_moves_w3_down_a_rung_in_a_dry_run(month, tmp_path):
    result = budget_policy.apply(month, slis.load(), budget_policy.load(), state_dir=tmp_path)
    assert result["simulated"] is True
    down = [a for a in result["actions"] if a["action"] == "rung down"]
    assert [a["workflow"] for a in down] == ["w3"]
    a = down[0]
    record = a["change_record"]
    assert (record["kind"], record["lever"], record["from"], record["to"], record["authority"]) == \
        ("emergency", "rung down", "manifest (3)", 2, "on-call lead")
    assert record["review"] == "the next board meeting" and record["document_by"] > record["at"]
    assert a["plan"]["rung"] == 2 and set(a["plan"]["dropped"]) == {"record_change", "restart_deployment",
                                                                      "scale_deployment"}
    # the override is what a harness would read before its next run
    plan = rungs.plan(registry.manifest("w3"), tmp_path / "rungs")
    assert plan.rung == 2 and "restart_deployment" not in plan.allowed
    assert (tmp_path / "changes.jsonl").read_text(encoding="utf-8").count("\n") == 1


def test_every_spent_budget_freezes_its_workflow_once(month):
    result = budget_policy.apply(month, slis.load(), budget_policy.load())
    freezes = [a for a in result["actions"] if a["action"] == "freeze"]
    assert len({a["workflow"] for a in freezes}) == len(freezes)
    for a in freezes:
        account = result["accounts"][a["workflow"]][a["sli"]]
        assert account["spent_at"] == a["at_s"] or round(account["spent_at"], 1) == a["at_s"]
        assert a["told"] == [registry.manifest(a["workflow"])["owner"], registry.manifest(a["workflow"])["sponsor"]]
    never = {w for w, acc in result["accounts"].items() if all(x["spent_at"] is None for x in acc.values())}
    assert never.isdisjoint({a["workflow"] for a in result["actions"]})


def test_w1_and_w2_have_no_rung_below_to_go_to_on_an_outcome():
    policy = yaml.safe_load((LAB / "slo" / "policy.yaml").read_text(encoding="utf-8"))
    rung_down = next(a for a in policy["actions"] if a["id"] == "rung-down")
    assert "W1 is at rung 0" in rung_down["no_rung_below"]
    assert registry.manifest("w1")["rung"] == 0
    assert not any(spec.get("writes") for spec in registry.manifest("w2")["tools"].values())
