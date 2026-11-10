"""Step 8's decision rule: a regression in the gate ends the path, too few runs extend the canary, a candidate below
the control on an SLI is remapped back, one not below it on every SLI is promoted, and the latency key it read is
recorded."""

from __future__ import annotations

import decision

HELD = [{"check": "deterministic.facts", "verdict": "held"}, {"check": "deterministic.planted", "verdict": "held"},
        {"check": "scorer", "verdict": "not gated"}]
REGRESSED = HELD + [{"check": "trajectory.order", "verdict": "regressed"}]


def arms(c_success=(60, 60), k_success=(40, 40), c_latency=(58, 60), k_latency=(39, 40), k_steady=(40, 40)):
    def ratio(good, valid):
        return {"good": good, "valid": valid, "value": None if not valid else good / valid}
    return {"control": {"runs_touched": {"success": ratio(*c_success), "latency": ratio(*c_latency),
                                         "latency_without_loads": ratio(*c_latency)}},
            "candidate": {"runs_touched": {"success": ratio(*k_success), "latency": ratio(*k_latency),
                                           "latency_without_loads": ratio(*k_steady)}}}


def test_a_regression_in_the_gate_ends_the_path():
    verdict = decision.decide(REGRESSED, arms())
    assert verdict["decision"] == decision.BACK and verdict["gate"]["regressed"] == ["trajectory.order"]
    assert verdict["because"][0].startswith("the gate")


def test_too_few_runs_extend_the_canary():
    verdict = decision.decide(HELD, arms(k_success=(5, 5), k_latency=(5, 5), k_steady=(5, 5)))
    assert verdict["decision"] == decision.EXTEND and "5 valid runs" in verdict["because"][0]


def test_a_candidate_below_the_control_is_remapped_back():
    verdict = decision.decide(HELD, arms(k_success=(38, 40)))
    assert verdict["decision"] == decision.BACK and verdict["because"][0].startswith("success")
    verdict = decision.decide(HELD, arms(k_latency=(30, 40)))  # as measured, the loads included
    assert verdict["decision"] == decision.BACK and verdict["because"][0].startswith("latency")


def test_not_below_on_every_sli_promotes_and_equal_is_enough():
    verdict = decision.decide(HELD, arms(k_latency=(39, 40)))
    assert verdict["decision"] == decision.PROMOTE
    assert verdict["gate"] == {"checks": 3, "regressed": [], "held": 2, "not_gated": 1}
    assert verdict["slis"]["success"]["candidate_not_below_control"] and verdict["slis"]["latency"]["candidate_not_below_control"]
    assert verdict["rule"]["latency_read_from"] == "latency"


def test_the_latency_key_is_the_callers_and_recorded():
    both = arms(k_latency=(30, 40), k_steady=(40, 40))
    measured = decision.decide(HELD, both, latency_key="latency")
    steady = decision.decide(HELD, both, latency_key="latency_without_loads")
    assert measured["decision"] == decision.BACK and steady["decision"] == decision.PROMOTE
    assert steady["slis"]["latency"]["read"] == "latency_without_loads" and steady["rule"]["latency_read_from"] == "latency_without_loads"
    assert measured["slis"]["latency"]["candidate"]["good"] == 30 and steady["slis"]["latency"]["candidate"]["good"] == 40
