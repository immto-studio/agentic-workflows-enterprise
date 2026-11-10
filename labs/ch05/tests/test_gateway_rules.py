"""Part 3: the gateway's rules as pure functions, without a proxy or a backend.

The integration tests in test_gateway.py prove LiteLLM calls these rules; these prove the rules
themselves: chapter 2's grid per deployment, the manifest, the fallback chain, the limits, and
the fallback flag on the cost line.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

LAB = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(LAB / "gateway"))
sys.path.insert(0, str(LAB / "manifest"))

import gateway_rules as gw  # noqa: E402
import manifest as mf  # noqa: E402

MANIFESTS = mf.load_manifests(LAB / "manifest")
DESTINATIONS, FALLBACKS = gw.read_config(LAB / "gateway" / "litellm.config.yaml")
TRACE = "0af7651916cd43dd8448eb211c80319c"


def tags(workflow: str, data_class: str) -> dict[str, str]:
    return {"workflow": workflow, "data_class": data_class}


def decide(alias: str, workflow: str, data_class: str) -> gw.Decision:
    return gw.decide(alias, tags(workflow, data_class), TRACE, MANIFESTS, DESTINATIONS, FALLBACKS)


# --- the config -----------------------------------------------------------------------------------

def test_every_deployment_says_where_it_serves() -> None:
    for alias, deployments in DESTINATIONS.items():
        for dest in deployments:
            assert "unknown" not in (dest.region, dest.jurisdiction, dest.hosting), dest
            assert dest.hosting in {"managed", "self-hosted"}, dest


def test_every_manifest_model_is_a_gateway_alias() -> None:
    for name, manifest in MANIFESTS.items():
        assert set(manifest["models"]) <= set(DESTINATIONS), name


def test_fallback_chain_is_read_from_the_config() -> None:
    assert FALLBACKS == {"larkspur-chat": ["larkspur-chat-fallback"]}
    assert gw.chain("larkspur-chat", FALLBACKS) == ["larkspur-chat", "larkspur-chat-fallback"]
    assert gw.chain("a", {"a": ["b"], "b": ["c", "a"]}) == ["a", "b", "c"]  # a cycle ends


# --- chapter 2's grid -----------------------------------------------------------------------------

@pytest.mark.parametrize("data_class, managed_home, managed_abroad, self_hosted_home", [
    ("public", True, True, True),
    ("internal", True, True, True),         # may cross regions; the serving Region is logged
    ("confidential", True, False, True),    # stays in the jurisdiction
    ("restricted", False, False, True),     # self-hosted in the jurisdiction only
    ("secret", False, False, False),        # not a class at all
])
def test_grid_by_row(data_class: str, managed_home: bool, managed_abroad: bool, self_hosted_home: bool) -> None:
    home = gw.Destination("a", "d1", "ca-central-1", "CA", "managed")
    abroad = gw.Destination("b", "d2", "us-east-2", "US", "managed")
    own = gw.Destination("c", "d3", "ca-central-1", "CA", "self-hosted")
    assert gw.may_receive(data_class, home) is managed_home
    assert gw.may_receive(data_class, abroad) is managed_abroad
    assert gw.may_receive(data_class, own) is self_hosted_home


# --- the decision ---------------------------------------------------------------------------------

def test_missing_metadata_is_refused() -> None:
    d = gw.decide("larkspur-chat", {}, None, MANIFESTS, DESTINATIONS, FALLBACKS)
    assert d.refused == "request refused: missing workflow, data_class, trace_id in metadata"


def test_workflow_without_a_manifest_is_refused() -> None:
    assert "no manifest for workflow 'w9-shadow-it'" in decide("larkspur-chat", "w9-shadow-it", "public").refused


def test_alias_outside_the_manifest_is_refused() -> None:
    assert "'larkspur-chat-fallback' is not a model in the manifest" in \
        decide("larkspur-chat-fallback", "w2-ops-assistant", "internal").refused


def test_data_class_above_the_manifest_maximum_is_refused() -> None:
    assert "above the maximum of 'w2-ops-assistant' ('internal')" in \
        decide("larkspur-chat", "w2-ops-assistant", "confidential").refused


def test_restricted_is_refused_by_the_managed_alias_and_taken_by_the_self_hosted_one() -> None:
    assert "may not go to 'larkspur-chat' (managed, ca-central-1, CA)" in \
        decide("larkspur-chat", "w3-incident", "restricted").refused
    assert decide("larkspur-chat-restricted", "w3-incident", "restricted") == gw.Decision()


def test_internal_may_fail_over_across_the_border_when_the_manifest_allows_the_region() -> None:
    assert decide("larkspur-chat", "w2-ops-assistant", "internal") == gw.Decision()


def test_failover_that_leaves_the_manifest_regions_is_disabled_not_refused() -> None:
    d = decide("larkspur-chat", "w3-incident", "internal")
    assert d.refused is None
    assert d.no_fallback == ("fallback to 'larkspur-chat-fallback' disabled for this request: "
                             "'larkspur-chat-fallback' serves from us-east-2, outside the regions of 'w3-incident'")


def test_failover_that_breaks_the_grid_is_disabled() -> None:
    d = decide("larkspur-chat", "w3-incident", "confidential")
    assert d.refused is None
    assert "data class 'confidential' may not go to 'larkspur-chat-fallback' (managed, us-east-2, US)" in d.no_fallback


def test_primary_outside_the_manifest_regions_is_refused() -> None:
    narrow = {**MANIFESTS["w2-ops-assistant"], "regions": ["us-east-2"]}
    d = gw.decide("larkspur-chat", tags("w2-ops-assistant", "internal"), TRACE,
                  {"w2-ops-assistant": narrow}, DESTINATIONS, FALLBACKS)
    assert d.refused == ("request refused: 'larkspur-chat' serves from ca-central-1, "
                         "outside the regions of 'w2-ops-assistant'")


# --- limits ---------------------------------------------------------------------------------------

class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_run_budget_is_summed_by_trace_id_and_fails_closed() -> None:
    limits = gw.Limits()
    manifest = {"budget": {"per_run_usd": 0.01, "per_month_usd": 1}}
    assert limits.check("w", "run-1", manifest) is None
    limits.record("run-1", 0.006)
    assert limits.check("w", "run-1", manifest) is None
    limits.record("run-1", 0.006)  # the call that crossed the line was already made
    assert "run run-1 has spent $0.0120 of its $0.01 budget" in limits.check("w", "run-1", manifest)
    assert limits.check("w", "run-2", manifest) is None  # another run, its own budget


def test_requests_per_minute_per_workflow() -> None:
    clock = Clock()
    limits = gw.Limits(clock)
    manifest = {"budget": {"per_run_usd": 1, "per_month_usd": 1, "requests_per_minute": 2}}
    assert limits.check("w", "r", manifest) is None
    assert limits.check("w", "r", manifest) is None
    assert "over 2 requests per minute" in limits.check("w", "r", manifest)
    assert limits.check("other", "r", manifest) is None  # per workflow
    clock.now += 60
    assert limits.check("w", "r", manifest) is None


# --- the cost line ----------------------------------------------------------------------------------

def kwargs_for(requested: str, served: str, deployment: str, region: str) -> dict:
    return {"model": "fake-model", "litellm_params": {"metadata": {
        "tags": ["workflow:w2-ops-assistant", "data_class:internal"], "trace_id": TRACE,
        "requested_alias": requested, "model_group": served,
        "model_info": {"id": deployment, "region": region}}}}


def test_fallback_flag_compares_the_serving_alias_with_the_requested_one() -> None:
    # The old hook compared the deployment id with "primary", so every call to the self-hosted
    # alias was logged as a fallback. It is a fallback only when another alias served it.
    own = gw.describe(kwargs_for("larkspur-chat-restricted", "larkspur-chat-restricted", "self-hosted", "ca-central-1"))
    assert own["fallback"] is False
    moved = gw.describe(kwargs_for("larkspur-chat", "larkspur-chat-fallback", "fallback", "us-east-2"))
    assert moved["fallback"] is True and moved["region"] == "us-east-2" and moved["served_alias"] == "larkspur-chat-fallback"


def test_every_kind_of_fallback_in_either_section_is_part_of_the_chain(tmp_path: Path) -> None:
    config = tmp_path / "c.yaml"
    config.write_text("""
model_list: []
litellm_settings:
  fallbacks: [{"a": ["b"]}]
  context_window_fallbacks: [{"a": ["c"]}]
router_settings:
  content_policy_fallbacks: [{"b": ["d"]}]
  default_fallbacks: ["e"]
""", encoding="utf-8")
    _, fallbacks = gw.read_config(config)
    assert gw.chain("a", fallbacks) == ["a", "b", "c", "e", "d"]
    assert gw.chain("z", {"*": ["e"]}) == ["z", "e"]


@pytest.mark.parametrize("trace_id", [None, "", "   ", {"not": "a string"}, ["0af7"]])
def test_a_trace_id_must_be_a_non_empty_string(trace_id) -> None:
    d = gw.decide("larkspur-chat", tags("w2-ops-assistant", "internal"), trace_id, MANIFESTS, DESTINATIONS, FALLBACKS)
    assert d.refused == "request refused: missing trace_id in metadata"


# --- the cache salt for self-hosted replicas -------------------------------------------------------

def test_a_self_hosted_alias_gets_the_workflow_as_its_cache_salt() -> None:
    data = {"model": "larkspur-chat-restricted", "cache_salt": "w2-ops-assistant",
            "extra_body": {"cache_salt": "someone-else", "keep": 1}}
    gw.set_cache_salt(data, "w3-incident", DESTINATIONS["larkspur-chat-restricted"])
    assert "cache_salt" not in data  # the caller's own value is gone
    assert data["extra_body"] == {"keep": 1, "cache_salt": "w3-incident"}


def test_a_managed_alias_gets_no_cache_salt() -> None:
    data = {"model": "larkspur-chat", "extra_body": {"cache_salt": "w2-ops-assistant"}}
    gw.set_cache_salt(data, "w2-ops-assistant", DESTINATIONS["larkspur-chat"])
    assert "extra_body" not in data and "cache_salt" not in data


# --- the guardrail's verdicts on the log line ----------------------------------------------------------

CARD = "4111 1111 1111 1111"  # what a PII filter matched: it must never reach a log


def test_a_guardrails_verdict_goes_on_the_line_without_what_it_matched() -> None:
    response = {
        "action": "NONE",  # detect mode: nothing blocked
        "assessments": [{
            "contentPolicy": {"filters": [{"type": "PROMPT_ATTACK", "confidence": "HIGH", "action": "NONE",
                                           "detected": True}]},
            "sensitiveInformationPolicy": {"piiEntities": [{"type": "CREDIT_DEBIT_CARD_NUMBER", "match": CARD,
                                                            "action": "NONE", "detected": True}],
                                           "regexes": [{"name": "policy-number", "match": "LM-2026-0042",
                                                        "regex": "LM-[0-9]{4}-[0-9]{4}", "action": "NONE"}]},
            "invocationMetrics": {"guardrailProcessingLatency": 212},
        }],
        "outputs": [{"text": f"card {CARD}"}],
    }
    kwargs = {"standard_logging_object": {"guardrail_information": [
        {"guardrail_name": "larkspur-aws", "guardrail_status": "success", "guardrail_response": response}]}}
    verdicts = gw.guardrail_verdicts(kwargs)
    assert verdicts == [{"guardrail": "larkspur-aws", "status": "success", "action": "NONE", "findings": [
        {"policy": "contentPolicy", "type": "PROMPT_ATTACK", "action": "NONE", "detected": True, "confidence": "HIGH"},
        {"policy": "sensitiveInformationPolicy", "type": "CREDIT_DEBIT_CARD_NUMBER", "action": "NONE", "detected": True},
        {"policy": "sensitiveInformationPolicy", "name": "policy-number", "action": "NONE"},
    ]}]
    assert CARD not in repr(verdicts) and "LM-2026-0042" not in repr(verdicts)


@pytest.mark.parametrize("kwargs", [
    {}, {"standard_logging_object": None}, {"standard_logging_object": {"guardrail_information": None}},
    {"standard_logging_object": {"guardrail_information": ["not a mapping"]}},
])
def test_a_call_without_guardrail_information_has_no_verdicts(kwargs: dict) -> None:
    assert gw.guardrail_verdicts(kwargs) == []


def test_a_guardrail_that_answered_in_text_still_has_its_status() -> None:
    kwargs = {"standard_logging_object": {"guardrail_information": {
        "guardrail_name": "presidio", "guardrail_status": "guardrail_intervened", "guardrail_response": "masked"}}}
    assert gw.guardrail_verdicts(kwargs) == [
        {"guardrail": "presidio", "status": "guardrail_intervened", "action": None, "findings": []}]
