"""The table against LiteLLM 1.106.6's built-in map, in a fresh process with the wheel's map and no network:
section 8.1's probe reproduced, and every difference the summary lists."""

from __future__ import annotations

import pytest

import report

KINDS = {
    ("nova-lite-ca", "bedrock/ca.amazon.nova-lite-v1:0"): "missing",
    ("nova-lite-ca", "bedrock/us.amazon.nova-lite-v1:0"): "different",
    ("nova-lite-us", "bedrock/us.amazon.nova-lite-v1:0"): "equal",
    ("nova-lite-us", "bedrock/amazon.nova-lite-v1:0"): "equal",
    ("nova-lite-ca", "bedrock/ca-central-1/amazon.nova-lite-v1:0"): "base price",
    ("nova-lite-us", "bedrock/us-east-2/amazon.nova-lite-v1:0"): "base price",
    ("vllm-gpt-oss-20b", "hosted_vllm/gpt-oss-20b"): "missing",
    ("titan-embed-v2-ca", "bedrock/amazon.titan-embed-text-v2:0"): "different",
    ("gpt-4o-canada-east", "azure/gpt-4o-2024-11-20"): "different",
    ("gemini-3.5-flash-montreal", "vertex_ai/gemini-3.5-flash"): "no table price",
    ("bedrock-gpt-oss-120b-use1", "bedrock/openai.gpt-oss-120b-1:0"): "equal",
}


@pytest.fixture(scope="module")
def compared() -> dict:
    return report.child("litellm_map.py")


def test_the_map_is_the_wheels_own(compared) -> None:
    assert compared["litellm"] == "1.106.6"
    assert compared["local_map"] == "True" and compared["map_in_use_is_the_wheels"] is True


def test_nova_lites_names_come_first_and_every_difference_is_the_listed_one(compared) -> None:
    rows = compared["rows"]
    assert [r["name"] for r in rows[:4]] == ["bedrock/ca.amazon.nova-lite-v1:0", "bedrock/us.amazon.nova-lite-v1:0",
                                             "bedrock/us.amazon.nova-lite-v1:0", "bedrock/amazon.nova-lite-v1:0"]
    assert {(r["deployment"], r["name"]): r["kind"] for r in rows} == KINDS


def test_section_8_1s_probe_reproduced(compared) -> None:
    """No ca. entry, so ModelNotMappedError; Region-prefixed names at the base entry's rate."""
    by = {r["name"]: r for r in compared["rows"]}
    ca = by["bedrock/ca.amazon.nova-lite-v1:0"]
    assert ca["map_entry"] is None and ca["litellm"] == {"error": "ModelNotMappedError"}
    for name in ("bedrock/us.amazon.nova-lite-v1:0", "bedrock/ca-central-1/amazon.nova-lite-v1:0",
                 "bedrock/us-east-2/amazon.nova-lite-v1:0", "bedrock/amazon.nova-lite-v1:0"):
        assert by[name]["litellm"] == {"input_per_million": 0.06, "output_per_million": 0.24}, name
    assert by["bedrock/ca-central-1/amazon.nova-lite-v1:0"]["map_entry"] is None


def test_the_canadian_price_is_the_one_the_map_cant_hold(compared) -> None:
    ratios = {(r["deployment"], r["name"]): r["table_over_litellm"] for r in compared["rows"]}
    assert ratios[("nova-lite-ca", "bedrock/us.amazon.nova-lite-v1:0")] == 1.0667
    assert ratios[("nova-lite-ca", "bedrock/ca-central-1/amazon.nova-lite-v1:0")] == 1.0667
    assert ratios[("titan-embed-v2-ca", "bedrock/amazon.titan-embed-text-v2:0")] == 5.0
    assert ratios[("gpt-4o-canada-east", "azure/gpt-4o-2024-11-20")] == 1.21
