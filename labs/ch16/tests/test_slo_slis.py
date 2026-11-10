"""Step 6's SLIs: what is valid, good and bad for each; the controls outside every budget; the kept runs measured."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import budget_policy
import burn
import registry
import slis

LAB = Path(__file__).resolve().parents[1]
KEPT = LAB / "results" / "2026-11-09" / "slo" / "kept.json"


def ev(end: str = "answer", seconds: float | None = 1.0, at: float = 10.0, **more) -> slis.RunEvent:
    return slis.RunEvent(more.pop("workflow", "w2"), more.pop("run_id", f"r{at}"), end, seconds, at=at, **more)


def test_a_run_of_an_unknown_end_or_decision_or_control_is_refused():
    with pytest.raises(ValueError):
        ev("finished")
    with pytest.raises(ValueError):
        ev(decision="liked")
    with pytest.raises(ValueError):
        ev(violation="everything")
    with pytest.raises(ValueError):
        ev(unit="night")


def test_success_counts_answers_refusals_and_proposals_good_and_stops_bad_and_own_limits_not_at_all():
    assert [slis.classify(ev(end), "success") for end in slis.GOOD] == [True, True, True]
    assert [slis.classify(ev(end), "success") for end in slis.BAD] == [False] * 4
    assert slis.classify(ev("own_limit"), "success") is None  # the workflow's own budget or rate holding (ch05:498)
    assert slis.classify(ev("proposal", None, decision="accepted", unit="decision"), "success") is None


def test_latency_counts_only_the_runs_good_for_success_against_the_threshold():
    assert slis.classify(ev("answer", 9.9), "latency", 10) is True
    assert slis.classify(ev("answer", 10.1), "latency", 10) is False
    assert slis.classify(ev("budget_stop", 1.0), "latency", 10) is None  # a failure is not counted twice
    assert slis.classify(ev("answer", None), "latency", 10) is None
    with pytest.raises(ValueError):
        slis.classify(ev(), "latency")


def test_outcome_counts_what_a_person_decided_and_nothing_undecided():
    assert slis.classify(ev("proposal", decision="accepted"), "outcome") is True
    assert slis.classify(ev("proposal", decision="rejected"), "outcome") is False
    assert slis.classify(ev("proposal", decision="reverted"), "outcome") is False
    assert slis.classify(ev("proposal"), "outcome") is None


def test_a_breached_control_is_an_incident_and_never_budget_spent():
    """The controls hold every time and get no error budget (O-D12): a breach is an incident, whatever the run's end,
    and no SLI, no burn rate and no budget account reads it."""
    clean = [ev("answer", 1.0, at=float(i), run_id=f"r{i}") for i in range(50)]
    clean += [ev("error", 1.0, at=100.0, run_id="bad")]
    breached = [slis.with_violation(e, "residency") if i % 5 == 0 else e for i, e in enumerate(clean)]
    breached[1] = slis.with_violation(breached[1], "never_list")
    breached[2] = slis.with_violation(breached[2], "budget")
    assert [e.run_id for e in slis.incidents(breached)][:3] == ["r0", "r1", "r2"]
    assert len(slis.incidents(breached)) == 13 and slis.incidents(clean) == []
    for sli in ("success", "latency"):
        assert slis.ratio(breached, sli, 10) == slis.ratio(clean, sli, 10)
        a = burn.Stream.of("w2", sli, 0.995, breached, 10)
        b = burn.Stream.of("w2", sli, 0.995, clean, 10)
        assert a.bad == b.bad and a.burn(200, 1) == b.burn(200, 1)
        assert (budget_policy.spent(breached, sli, 0.5, 10)["bad"] == budget_policy.spent(clean, sli, 0.5, 10)["bad"]
                == (1 if sli == "success" else 0))


def test_the_probes_runs_never_spend_a_budget():
    probes = [ev("error", 1.0, at=float(i), run_id=f"p{i}", probe=True) for i in range(5)]
    assert budget_policy.spent(probes, "success", 1, None)["bad"] == 0


def test_the_sentences_are_the_harnesses_own(kept_slo):
    s = slis.sentences()
    with registry.isolated(("workflows/w2-ops-assistant/harness",)):
        import answer
        assert (s.w2_budget, s.w2_read_failed, s.w2_max_reads) == (answer.BUDGET_EXHAUSTED, answer.READ_FAILED,
                                                                   answer.MAX_READS)
        assert s.w2_refusal == answer.REFUSAL
    assert s.w3_budget == s.w2_budget  # W3's loop takes W2's sentence
    assert s.w3_unavailable.startswith("W3 couldn't reach the model")


def test_w2s_step_budget_stops_are_its_refusal_after_the_read_budget_and_one_more_call(kept_slo):
    stops = [e for e in slis.pooled(kept_slo, "w2") if e.end == "budget_stop"]
    assert [e.run_id.rsplit(":", 1)[1] for e in stops] == ["w2-01", "w2-05", "w2-08", "w2-09", "w2-18"]
    assert {e.source for e in stops} == {"workflows/w2-ops-assistant/eval/results/2026-11-02/answers-gpt-oss-20b-run1.json"}
    s = slis.sentences()
    record = {"answer": s.w2_refusal, "read_events": [{}] * 4, "model_calls": [{}] * 5}
    assert slis.w2_budget_stop(record, s)
    assert not slis.w2_budget_stop({**record, "model_calls": [{}] * 4}, s)
    assert not slis.w2_budget_stop({**record, "answer": "Nothing the assistant can read answers it."}, s)


def test_w1s_search_limit_is_its_refusal_and_w3s_stops_are_its_own_sentence(kept_slo):
    w1 = slis.pooled(kept_slo, "w1")
    assert {e.end for e in w1} == {"answer", "refusal"}
    w3 = slis.pooled(kept_slo, "w3")
    assert sum(1 for e in w3 if e.end == "budget_stop") == 8
    assert {e.reason for e in w3 if e.end == "budget_stop"} == {"the step-budget sentence"}
    assert sorted(e.decision for e in w3 if e.decision) == ["accepted", "accepted"]  # the eval's scripted approver


def test_w5s_decisions_are_its_ledgers_and_never_runs(kept_slo):
    w5 = slis.pooled(kept_slo, "w5")
    decisions = [e for e in w5 if e.unit == "decision"]
    assert len(decisions) == 11 and {e.decision for e in decisions} == {"accepted"}
    assert all("sandbox-quill:aws_ebs_volume.archive" in e.run_id for e in decisions)  # the eval's one merge, before golden night 2
    assert slis.ratio(w5, "success").valid == 33


def test_the_committed_measurement_is_the_kept_runs(kept_slo):
    committed = json.loads(KEPT.read_text(encoding="utf-8"))
    assert committed["measured"] is True and committed["simulated"] is False
    fresh = slis.measured_table(kept_slo, slis.load())
    assert committed["pooled"] == json.loads(json.dumps(fresh["pooled"]))
    assert committed["rows"] == json.loads(json.dumps(fresh["rows"]))
    pooled = committed["pooled"]
    assert [pooled[w]["slis"]["success"]["good"] for w in slis.WORKFLOWS] == [75, 129, 40, 48, 33]
    assert [pooled[w]["slis"]["success"]["valid"] for w in slis.WORKFLOWS] == [75, 135, 48, 48, 33]


def test_every_sli_says_where_its_events_come_from_and_what_the_kept_runs_lack():
    slos = slis.load()
    assert slos["window_days"] == 30 and set(slos["controls"]) - {"breach"} == set(slis.CONTROLS)
    for workflow, spec in slos["workflows"].items():
        assert spec["rung"] == registry.manifest(workflow)["rung"], workflow
        for sli in slis.SLI_NAMES:
            body = spec["slis"][sli]
            assert body["reason"] and body["kept_runs_lack"], (workflow, sli)
            if body.get("target") is not None:
                assert 0 < body["target"] < 1 and body["sources"], (workflow, sli)
    assert [w for w, s in slos["workflows"].items() if s["slis"]["outcome"]["target"] is None] == ["w1", "w2"]
