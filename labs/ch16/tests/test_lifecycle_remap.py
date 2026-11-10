"""Step 8's remap: the alias moved to the candidate and back, every other alias kept, the written configuration whole
and accepted by chapter 5's rules for W2, the change record's fields, a remap to where the alias already is refused,
and the alias's tenants read from the manifests."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

import remap

LAB = Path(__file__).resolve().parents[1]
ROOT = LAB.parents[1]
LIFECYCLE = LAB / "lifecycle"
for folder in (ROOT / "labs" / "ch05" / "gateway", ROOT / "labs" / "ch05" / "manifest"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
import gateway_rules as rules  # noqa: E402
import manifest as manifests  # noqa: E402

CANARY, STAGING, CURRENT = (LIFECYCLE / f"litellm.{n}.yaml" for n in ("canary", "staging", "current"))
W2 = manifests.load_manifests(ROOT / "workflows" / "w2-ops-assistant" / "manifest")
AT = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
KW = dict(change="CH-TEST-1", by="platform.team@larkspur.example", reason="a test", evidence=["gate.json"], now=AT)


def test_a_promotion_moves_the_alias_to_the_candidate_alone_and_keeps_the_rest(tmp_path):
    path, record = remap.remap("promote", CANARY, STAGING, tmp_path / "promoted.yaml", **KW)
    written = yaml.safe_load(path.read_text(encoding="utf-8"))
    chat = [e for e in written["model_list"] if e["model_name"] == "larkspur-chat"]
    assert len(chat) == 1 and chat[0]["model_info"]["id"] == "candidate-gemma4-12b-chat"
    assert "weight" not in chat[0]["litellm_params"] and chat[0]["litellm_params"]["think"] is False
    restricted = [e for e in written["model_list"] if e["model_name"] == "larkspur-chat-restricted"]
    assert len(restricted) == 1 and restricted[0]["model_info"]["id"] == "local-gpt-oss-20b-restricted"
    assert written["litellm_settings"] == yaml.safe_load(CANARY.read_text(encoding="utf-8"))["litellm_settings"]
    assert written["router_settings"]["routing_strategy"] == "simple-shuffle"
    destinations, fallbacks = rules.read_config(path)
    ok = rules.decide("larkspur-chat", {"workflow": "w2-ops-assistant", "data_class": "internal"}, "1" * 32, W2, destinations, fallbacks)
    assert ok.refused is None
    assert record["kind"] == "planned" and record["lever"] == "alias remap, promotion" and record["alias"] == "larkspur-chat"
    assert [d["id"] for d in record["from"]] == ["local-gpt-oss-20b-chat", "candidate-gemma4-12b-chat"]
    assert [d["weight"] for d in record["from"]] == [3, 1] and record["to"] == [{"id": "candidate-gemma4-12b-chat", "model": "ollama_chat/gemma4:12b"}]
    assert record["at"] == "2026-11-09T12:00:00.000+00:00" and record["document_by"] == "2026-11-10T12:00:00.000+00:00"
    assert record["review"] == "the next board meeting" and record["evidence"] == ["gate.json"]
    assert "w2-ops-assistant" in record["workflows"] and len(record["workflows"]) >= 2
    lines = [json.loads(x) for x in (tmp_path / "changes.jsonl").read_text(encoding="utf-8").splitlines()]
    assert lines == [record]


def test_a_remap_back_writes_the_configuration_the_alias_served_before_whole(tmp_path):
    path, record = remap.remap("back", CANARY, CURRENT, tmp_path / "restored.yaml", **{**KW, "by": "oncall.lead@larkspur.example"})
    written = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert written == yaml.safe_load(CURRENT.read_text(encoding="utf-8"))  # the canary's router_settings included
    chat = [e for e in written["model_list"] if e["model_name"] == "larkspur-chat"]
    assert [e["model_info"]["id"] for e in chat] == ["local-gpt-oss-20b-chat"] and "weight" not in chat[0]["litellm_params"]
    assert "router_settings" not in written
    assert record["kind"] == "emergency" and record["authority"] == "on-call lead"
    assert [d["id"] for d in record["from"]] == ["local-gpt-oss-20b-chat", "candidate-gemma4-12b-chat"]
    assert record["to"] == [{"id": "local-gpt-oss-20b-chat", "model": "ollama_chat/gpt-oss:20b"}]


def test_two_remaps_append_two_lines_and_the_second_reads_the_first(tmp_path):
    first, _ = remap.remap("promote", CANARY, STAGING, tmp_path / "promoted.yaml", **KW)
    second, record = remap.remap("back", first, CURRENT, tmp_path / "restored.yaml", **{**KW, "change": "CH-TEST-2"})
    assert [d["id"] for d in record["from"]] == ["candidate-gemma4-12b-chat"]
    lines = (tmp_path / "changes.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and json.loads(lines[1])["change"] == "CH-TEST-2"


def test_a_remap_to_where_the_alias_already_is_is_refused(tmp_path):
    with pytest.raises(ValueError, match="already serves"):
        remap.remap("promote", STAGING, STAGING, tmp_path / "x.yaml", **KW)
    with pytest.raises(ValueError, match="promote or back"):
        remap.remap("sideways", CANARY, STAGING, tmp_path / "y.yaml", **KW)
    assert not (tmp_path / "changes.jsonl").exists()


def test_the_header_and_the_names_the_record_carries(tmp_path):
    path, record = remap.remap("promote", CANARY, STAGING, tmp_path / "promoted.yaml", header="# a header", **KW,
                               names_as=("lifecycle/litellm.canary.yaml", "litellm.promoted.yaml"))
    assert path.read_text(encoding="utf-8").startswith("# a header\n")
    assert record["config_before"] == "lifecycle/litellm.canary.yaml" and record["config_after"] == "litellm.promoted.yaml"


def test_the_tenants_are_the_workflows_whose_manifests_name_the_alias():
    tenants = remap.tenants_of("larkspur-chat", ROOT)
    assert "w2-ops-assistant" in tenants and "w1-knowledge" in tenants
    assert remap.tenants_of("no-such-alias", ROOT) == []
