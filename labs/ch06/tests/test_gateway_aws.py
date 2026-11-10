"""Chapter 5's gateway rules on the AWS gateway pair's deployments (gateway/litellm.aws.yaml).

The Confidential alias on AWS is Amazon Nova Lite through the Canada profile, which serves from
ca-central-1 and ca-west-1. The rules compare every Region a deployment can serve from with the
manifest, so the incident workflow's AWS manifest lists both, and chapter 5's lab manifest, which
lists ca-central-1 alone, would be refused.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

LAB = Path(__file__).resolve().parent.parent
CH05 = LAB.parent / "ch05"
for folder in (CH05 / "gateway", CH05 / "manifest"):
    sys.path.insert(0, str(folder))

pytest.importorskip("jsonschema", reason="chapter 5's rules load manifests with its schema")
import gateway_rules as rules  # noqa: E402

DESTINATIONS, FALLBACKS = rules.read_config(LAB / "gateway" / "litellm.aws.yaml")
W3_AWS = LAB / "manifests" / "w3-incident.yaml"
W3_LAB = CH05 / "manifest" / "w3-incident.yaml"
W2_LAB = CH05 / "manifest" / "w2-ops-assistant.yaml"


def load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def decide(manifest: dict[str, Any], alias: str, data_class: str) -> rules.Decision:
    return rules.decide(alias, {"workflow": manifest["workflow"], "data_class": data_class}, "4bf92f3577b34da6a3ce929d0e0e4736",
                        {manifest["workflow"]: manifest}, DESTINATIONS, FALLBACKS)


def test_the_confidential_alias_is_the_canada_profile_and_its_fallback_the_same_model_in_ohio() -> None:
    (primary,) = DESTINATIONS["larkspur-chat"]
    (fallback,) = DESTINATIONS["larkspur-chat-fallback"]
    assert (primary.region, primary.regions, primary.jurisdiction) == ("ca-central-1", ("ca-central-1", "ca-west-1"), "CA")
    assert (fallback.regions, fallback.jurisdiction) == (("us-east-2",), "US")
    config = load(LAB / "gateway" / "litellm.aws.yaml")
    models = {entry["model_name"]: entry["litellm_params"]["model"] for entry in config["model_list"]}
    assert models["larkspur-chat"] == "bedrock/converse/ca.amazon.nova-lite-v1:0"
    assert models["larkspur-chat-fallback"] == "bedrock/converse/amazon.nova-lite-v1:0"
    assert FALLBACKS == {"larkspur-chat": ["larkspur-chat-fallback"]}


def test_the_incident_workflow_on_aws_gets_the_profile_and_never_a_transfer_to_ohio() -> None:
    decision = decide(load(W3_AWS), "larkspur-chat", "confidential")
    assert decision.refused is None
    assert decision.no_fallback == ("fallback to 'larkspur-chat-fallback' disabled for this request: data class "
                                    "'confidential' may not go to 'larkspur-chat-fallback' (managed, us-east-2, US)")


def test_chapter_5s_lab_manifest_is_refused_because_calgary_isnt_in_it() -> None:
    decision = decide(load(W3_LAB), "larkspur-chat", "confidential")
    assert decision.refused == ("request refused: 'larkspur-chat' serves from ca-west-1, "
                                "outside the regions of 'w3-incident'")


def test_internal_data_may_fail_over_to_ohio_once_the_manifest_lists_calgary() -> None:
    w2 = load(W2_LAB)
    assert decide(w2, "larkspur-chat", "internal").refused  # [ca-central-1, us-east-2] alone isn't enough
    w2["regions"].append("ca-west-1")
    assert decide(w2, "larkspur-chat", "internal") == rules.Decision()


def test_litellm_sends_the_tools_on_the_canada_profile_only_because_the_config_allows_them() -> None:
    """LiteLLM 1.106.6 doesn't know Bedrock's ca. profiles and refuses a request with tools on one.

    The router counts that refusal as a failure, so without the config's line every call with tools
    would fail or go to Ohio. If an upgrade makes the second assertion fail, LiteLLM has learned the
    ca. profiles and the line can go.
    """
    litellm = pytest.importorskip("litellm", reason="needs chapter 5's environment")
    from litellm.utils import get_optional_params

    config = load(LAB / "gateway" / "litellm.aws.yaml")
    (entry,) = [e for e in config["model_list"] if e["model_name"] == "larkspur-chat"]
    params = entry["litellm_params"]
    model = params["model"].removeprefix("bedrock/converse/")
    tool = {"type": "function", "function": {"name": "search_docs", "description": "Search the wiki.",
                                             "parameters": {"type": "object", "properties": {}}}}
    sent = get_optional_params(model=model, custom_llm_provider="bedrock", tools=[tool], drop_params=False,
                               allowed_openai_params=params["allowed_openai_params"])
    assert "tools" in sent or "toolConfig" in sent
    with pytest.raises(litellm.UnsupportedParamsError):
        get_optional_params(model=model, custom_llm_provider="bedrock", tools=[tool], drop_params=False)


def test_the_bedrock_guardrail_screens_the_managed_aliases_and_never_the_self_hosted_one() -> None:
    """A Restricted prompt goes to the self-hosted model, and must not reach a managed service on the way."""
    config = load(LAB / "gateway" / "litellm.aws.yaml")
    (guardrail,) = config["guardrails"]
    params = guardrail["litellm_params"]
    assert (params["guardrail"], params["default_on"], params["mode"]) == ("bedrock", False, ["pre_call", "post_call"])
    attached = {entry["model_name"]: entry["litellm_params"].get("guardrails", []) for entry in config["model_list"]}
    hosting = {entry["model_name"]: entry["model_info"]["hosting"] for entry in config["model_list"]}
    for alias, names in attached.items():
        assert names == ([guardrail["guardrail_name"]] if hosting[alias] == "managed" else []), alias


def test_litellm_runs_no_guardrail_on_a_request_for_the_self_hosted_alias() -> None:
    pytest.importorskip("litellm", reason="needs chapter 5's environment")
    from litellm import Router
    from litellm.proxy.utils import check_and_merge_model_level_guardrails

    config = load(LAB / "gateway" / "litellm.aws.yaml")
    router = Router(model_list=config["model_list"])
    merged = {alias: check_and_merge_model_level_guardrails({"model": alias}, router, trust_client_model_info=False)
              for alias in ("larkspur-chat", "larkspur-chat-restricted")}
    assert "larkspur-aws" in repr(merged["larkspur-chat"])
    assert "larkspur-aws" not in repr(merged["larkspur-chat-restricted"])


def test_restricted_data_goes_to_the_self_hosted_alias_only() -> None:
    w3 = load(W3_AWS)
    refused = decide(w3, "larkspur-chat", "restricted").refused
    assert refused and refused.startswith("request refused: data class 'restricted' may not go to 'larkspur-chat'")
    assert decide(w3, "larkspur-chat-restricted", "restricted") == rules.Decision()
