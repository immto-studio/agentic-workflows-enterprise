"""The policies written again in Python (collector/policies.py): the hash, the threshold, the share a span
records, and each policy's edge, with no Collector."""

from __future__ import annotations

from decimal import Decimal

import pytest

import policies
from collector_support import trace_id

BUDGETS = {"w1-knowledge": Decimal("0.20"), "w2-ops-assistant": Decimal("0.50")}


def flat(**overrides) -> dict:
    s = {"name": "s", "trace_id": "0" * 31 + "1", "span_id": "1" * 16, "parent_span_id": None, "status": "UNSET",
         "start_ns": 0, "end_ns": 1_000_000, "attributes": {}, "events": [], "resource": {}}
    return {**s, **overrides}


def test_fnv_1a_64_against_the_reference_vectors() -> None:
    assert policies.fnv1a64(b"") == 0xcbf29ce484222325
    assert policies.fnv1a64(b"a") == 0xaf63dc4c8601ec8c
    assert policies.fnv1a64(b"foobar") == 0x85944171f73967e8


def test_the_threshold_is_the_processor_s() -> None:
    assert policies.share_threshold(1.0) == policies.MASK
    assert policies.share_threshold(0.0) == 0
    assert policies.share_threshold(0.1) == 0x19999999999999FF  # MaxUint64 x 0.1, at 64 bits, truncated
    assert policies.share_threshold(0.5) == 0x7FFFFFFFFFFFFFFF


@pytest.mark.parametrize(("trace_state", "share"), [
    ("ot=th:0", 1.0), ("ot=th:e6666666666666", 0.1), ("ot=th:8", 0.5), ("ot=rv:abcdef01234567;th:c", 0.25),
    ("vendor=x,ot=th:0", 1.0), ("", None), ("ot=rv:abcdef01234567", None), (None, None)])
def test_the_share_a_span_records_in_its_tracestate(trace_state: str | None, share: float | None) -> None:
    assert policies.share_from_tracestate(trace_state) == share


def test_each_policy_at_its_edge() -> None:
    def hits(*spans: dict) -> list[str]:
        return policies.matched(policies.features(spans), BUDGETS, 10_000)

    assert hits(flat()) == []
    assert hits(flat(status="ERROR")) == ["failed"]
    assert hits(flat(attributes={"error.type": "tool_error"})) == ["failed"]
    assert hits(flat(attributes={"larkspur.refused": True})) == ["refused"]
    assert hits(flat(attributes={"larkspur.refused": False})) == []
    assert hits(flat(end_ns=10_000_000_000)) == []                 # exactly the threshold: not slow
    assert hits(flat(end_ns=10_001_000_000)) == ["slow"]
    assert hits(flat(end_ns=1), flat(start_ns=10_002_000_000, end_ns=10_002_000_001)) == ["slow"]  # across spans
    cost = {"larkspur.workflow": "w1-knowledge"}
    assert hits(flat(attributes={**cost, "larkspur.cost_usd": 0.2})) == ["over-budget"]  # at the budget
    assert hits(flat(attributes={**cost, "larkspur.cost_usd": 0.1999})) == []
    assert hits(flat(attributes={"larkspur.workflow": "w9-unknown", "larkspur.cost_usd": 99.0})) == []
    assert hits(flat(attributes={"larkspur.fallback": True})) == ["fallback"]
    assert hits(flat(resource={"larkspur.fallback": True})) == ["fallback"]


def test_the_recorded_policy_is_the_first_that_keeps_and_the_share_the_lowest() -> None:
    fallback_after_a_failure = policies.features([flat(attributes={"error.type": "ServiceUnavailableError"}),
                                                  flat(attributes={"larkspur.fallback": True})])
    salt = policies.settings()["salt"]
    decision = policies.decide("0" * 31 + "1", fallback_after_a_failure, per_run=BUDGETS, threshold_ms=10_000,
                               salt=salt, percent=10)
    assert decision["kept"] and decision["policy"] == "failed" and decision["matched"] == ["failed", "fallback"]
    assert decision["share"] == 1.0
    plain = policies.features([flat()])
    kept, dropped = trace_id(kept_by_share=True), trace_id(kept_by_share=False)
    assert policies.decide(kept, plain, per_run=BUDGETS, threshold_ms=10_000, salt=salt, percent=10) == {
        "kept": True, "policy": policies.SHARE, "share": 0.1, "matched": [], "share_keeps": True}
    assert policies.decide(dropped, plain, per_run=BUDGETS, threshold_ms=10_000, salt=salt, percent=10)["kept"] is False
    assert policies.decide(dropped, plain, per_run=BUDGETS, threshold_ms=10_000, salt=salt, percent=100)["share"] == 1.0


def test_the_hash_needs_random_trace_ids() -> None:
    """FNV-1a mixes the id's last bytes poorly: ids that differ only there land on the same side of the share."""
    salt = policies.settings()["salt"]
    assert sum(policies.share_keeps(f"{i:032x}", salt, 10) for i in range(1000)) in (0, 1000)
    first_bytes = sum(policies.share_keeps(f"{i:04x}" + "0" * 28, salt, 10) for i in range(1000))
    assert 60 <= first_bytes <= 140
    random_ids = sum(policies.share_keeps(trace_id(), salt, 10) for _ in range(20_000))
    assert 1_800 <= random_ids <= 2_200  # about ten percent, as W3C's random trace ids give


def test_the_settings_come_from_config_yaml() -> None:
    settings = policies.settings()
    assert settings["threshold_ms"] == 10_000 and settings["salt"] == "larkspur-ch16" and settings["percent"] == 10.0
    assert policies.settings(percent=100.0)["percent"] == 100.0


def test_a_template_attribute_is_matched_by_its_prefix() -> None:
    assert policies.is_content("gen_ai.prompt.variable.user_name")
    assert policies.is_content("gen_ai.tool.call.arguments")
    assert not policies.is_content("gen_ai.prompt.variable")      # the template itself is never a key
    assert not policies.is_content("gen_ai.tool.description")     # recommended, not opt-in
    assert not policies.is_content("gen_ai.usage.input_tokens")
