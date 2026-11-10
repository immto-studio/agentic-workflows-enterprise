"""The facts a local model's answer must state, and how they are matched. No model needed."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run_local_golden as rlg  # noqa: E402

CASES = {case["id"]: case for case in rlg.run_golden.load_cases()}


def test_pod_facts_come_from_the_platform_not_the_sentence() -> None:
    assert rlg.key_facts(CASES["pods-claims-api"]) == [["claims-api"], ["2", "two"], ["3", "three"]]


def test_a_missing_service_must_be_reported_as_missing() -> None:
    facts = rlg.key_facts(CASES["pods-unknown-service"])
    assert facts[0] == ["payroll-service"] and "no deployment" in facts[1]
    assert rlg.states("I couldn’t find a deployment named payroll-service.", facts[1])


def test_alert_counts_accept_words_and_the_zero_and_one_phrasings() -> None:
    zero = rlg.key_facts(CASES["alerts-document-ocr-10"])[1]
    assert rlg.states("No alerts fired for document-ocr in the last 10 minutes.", zero)
    one = rlg.key_facts(CASES["alerts-fraud-scoring-hour"])[1]
    assert rlg.states("There was one alert in the last hour.", one)
    assert rlg.states("Yes, a warning fired 18 minutes ago.", one)


def test_the_window_from_the_question_is_not_a_fact() -> None:
    flat = [form for fact in rlg.key_facts(CASES["alerts-claims-api-default-window"]) for form in fact]
    assert "60" not in flat


def test_typographic_hyphens_match_but_are_recorded() -> None:
    answer = "Yes, all 4 replicas of billing‑worker are ready."
    assert rlg.states(answer, ["billing-worker"])
    result = rlg.LocalResult("x", "q", answer, [], [], [], [], 0.0)
    assert result.typographic


def test_numbers_match_as_whole_words_only() -> None:
    assert not rlg.states("claims-api-7d9f8b6c4-t8w2c restarted", ["7"])  # digits inside a pod name
    assert not rlg.states("12 pods", ["2"])
    assert rlg.states("2 of 3 pods ready", ["3", "three"])


def test_the_refusal_case_has_no_facts() -> None:
    assert rlg.key_facts(CASES["refuse-scale"]) == []
