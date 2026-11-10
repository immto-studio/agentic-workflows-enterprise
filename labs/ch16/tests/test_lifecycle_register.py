"""Step 8's register: its shape, the three source registers inside it with their dates, the pins (a digest on a named
server for a local model, an unversioned ID for Claude, said so), and the check that the register and the gateways
name the same deployments, both ways, with the Terraform files read as chapters 7 and 8 read them."""

from __future__ import annotations

import copy
import re
import shutil
from pathlib import Path

import yaml

import register as reg

LAB = Path(__file__).resolve().parents[1]
ROOT = LAB.parents[1]
REGISTER = reg.load()
MODELS = {m["id"]: m for m in reg.models(REGISTER)}


def test_the_register_has_the_shape_the_loader_asks_for():
    assert reg.shape_problems(REGISTER) == []
    for m in reg.models(REGISTER):
        assert m["source"]["read"].isoformat() <= REGISTER["read_on"].isoformat(), m["id"]
        assert m["stage"] in REGISTER["stages"][m["stage_scheme"]]["values"], m["id"]


def test_the_register_and_the_gateways_name_the_same_deployments():
    assert reg.check(REGISTER) == []


def test_models_per_cloud_and_what_larkspur_runs_on():
    counts = {c: sum(1 for m in reg.models(REGISTER) if m["cloud"] == c) for c in reg.CLOUDS}
    assert counts == {"aws": 6, "google": 2, "azure": 2, "local": 3}
    pinned = sorted(m["id"] for m in reg.models(REGISTER) if m["pinned"])
    assert pinned == ["aws-nova-lite", "azure-gpt-4o", "google-gemini-3-5-flash", "google-text-multilingual-embedding-002",
                      "local-gpt-oss-20b", "local-qwen3-embedding-0-6b"]
    assert MODELS["local-gemma4-12b"]["stage"] == "candidate" and not MODELS["local-gemma4-12b"]["pinned"]
    assert MODELS["aws-claude-haiku-5-5"]["larkspur_stage"] == "candidate"
    assert len(reg.register_deployments(REGISTER)) == 14


def test_every_model_of_chapters_6_7_and_8_is_in_it_with_its_dates_and_stage():
    assert reg.source_registers_problems(REGISTER) == []
    six = yaml.safe_load((ROOT / "labs/ch06/models.yaml").read_text(encoding="utf-8"))
    seven = yaml.safe_load((ROOT / "labs/ch07/models.yaml").read_text(encoding="utf-8"))
    eight = yaml.safe_load((ROOT / "labs/ch08/models.yaml").read_text(encoding="utf-8"))
    names = {m["model"] for m in reg.models(REGISTER)}
    assert set(six) <= names and set(seven) <= names and set(eight) <= names
    assert len(six) == 5 and len(seven) == 2 and len(eight) == 2
    assert MODELS["aws-claude-3-haiku"]["retires"].isoformat() == "2026-11-13"
    assert MODELS["azure-gpt-4o"]["retires"].isoformat() == "2027-04-14" and MODELS["azure-gpt-4o"]["stage"] == "Legacy"
    assert MODELS["google-text-multilingual-embedding-002"]["retires"].isoformat() == "2027-04-01"


def test_the_claude_pins_carry_no_version_and_say_so():
    for name in ("aws-claude-sonnet-5-5", "aws-claude-haiku-5-5"):
        pin = MODELS[name]["pin"]
        assert pin["versioned"] is False and "no version" in pin["note"], name
        assert not re.search(r"-v\d+:\d+$|\d{8}", pin["value"]), pin["value"]
    for name in ("aws-nova-lite", "aws-claude-3-haiku", "aws-llama3-70b", "aws-mistral-large"):
        assert MODELS[name]["pin"]["versioned"] is True, name


def test_a_local_pin_is_a_digest_on_a_named_server():
    for name in ("local-gpt-oss-20b", "local-gemma4-12b", "local-qwen3-embedding-0-6b"):
        pin = MODELS[name]["pin"]
        assert pin["kind"] == "ollama digest" and reg.HEX64.match(pin["value"]), name
        assert pin["server"] == "Ollama 0.40.13", name
    vllm = next(d for d in MODELS["local-gpt-oss-20b"]["deployments"] if d["id"].startswith("vllm-"))
    assert vllm["pin"]["value"] == "6cee5e81ee83917806bbde320786a8fb61efebee"
    assert (ROOT / vllm["pin"]["files"]).exists()
    # The same tag reported another digest on the other server, which the register says beside the pin.
    assert "a0b38d0b19f7" in MODELS["local-gpt-oss-20b"]["pin"]["note"]


def test_an_unregistered_or_misnamed_deployment_is_reported(tmp_path):
    relative = "workflows/w2-ops-assistant/gateway/litellm.config.yaml"
    target = tmp_path / relative
    target.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / relative, target)
    config = yaml.safe_load(target.read_text(encoding="utf-8"))
    config["model_list"].append({"model_name": "larkspur-chat", "litellm_params": {"model": "ollama_chat/other:1b"},
                                 "model_info": {"id": "nobody-registered-this", "region": "ca-central-1", "hosting": "self-hosted"}})
    config["model_list"][0]["model_name"] = "larkspur-chat-fallback"  # the control's alias, misnamed
    target.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    register = copy.deepcopy(REGISTER)
    register["gateways"]["litellm"] = [relative]
    problems = reg.litellm_problems(register, tmp_path)
    assert any("nobody-registered-this" in p and "not in the register" in p for p in problems)
    assert any("local-gpt-oss-20b-chat" in p and "larkspur-chat-fallback" in p for p in problems)
    missing = copy.deepcopy(register)
    missing["models"][0]["deployments"][0]["configs"] = [relative]  # Nova Lite's Canada profile, which W2's config lacks
    assert any("nova-lite-ca" in p and "is not in it" in p for p in reg.litellm_problems(missing, tmp_path))


def test_the_terraform_files_deploy_what_the_register_says():
    assert reg.terraform_problems(REGISTER) == []
    assert reg.google_models(ROOT / "labs/ch07/terraform/runtime.tf") == {"gemini-3.5-flash", "text-multilingual-embedding-002"}
    assert reg.azure_chat_model(ROOT / "labs/ch08/terraform/variables.tf") == {"name": "gpt-4o", "version": "2024-11-20"}


def test_the_identifier_is_what_follows_the_provider_prefix():
    assert reg.identifier_of("bedrock/converse/ca.amazon.nova-lite-v1:0") == "ca.amazon.nova-lite-v1:0"
    assert reg.identifier_of("ollama_chat/gpt-oss:20b") == "gpt-oss:20b"
    assert reg.identifier_of("hosted_vllm/gpt-oss-20b") == "gpt-oss-20b"


def test_the_excluded_configurations_hold_fakes_and_nothing_the_register_lists():
    excluded = {e["path"] for e in REGISTER["gateways"]["excluded"]}
    assert excluded == {"labs/ch05/gateway/litellm.config.yaml", "labs/ch16/budget/litellm.config.yaml", "labs/ch16/capacity/"}
    for d in (d for _, d in reg.register_deployments(REGISTER)):
        for config in d.get("configs") or []:
            assert not any(config.startswith(e) for e in excluded), config
    fakes = yaml.safe_load((ROOT / "labs/ch05/gateway/litellm.config.yaml").read_text(encoding="utf-8"))
    assert all(e["litellm_params"]["model"].startswith("openai/fake-") for e in fakes["model_list"])
