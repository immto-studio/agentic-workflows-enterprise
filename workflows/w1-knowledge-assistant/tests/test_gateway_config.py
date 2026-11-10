"""The gateway's rules read the config the proxy was started with, and the managed alias stays managed."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

W1 = Path(__file__).resolve().parents[1]
GATEWAY = W1 / "gateway"
CH05_GATEWAY = W1.parents[1] / "labs" / "ch05" / "gateway"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses look their module up while the class is built
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


paths = _load("w1_gateway_config_path_test", GATEWAY / "config_path.py")
DEFAULT = GATEWAY / "litellm.config.yaml"
BEDROCK = GATEWAY / "litellm.bedrock.yaml"


def worker(config: str) -> str:
    return json.dumps({"config": config, "port": 4012})


def test_default_without_either_variable():
    assert paths.gateway_config({}, DEFAULT) == str(DEFAULT)


def test_the_proxy_config_wins_when_gateway_config_is_unset():
    assert paths.gateway_config({"WORKER_CONFIG": worker(str(BEDROCK))}, DEFAULT) == str(BEDROCK)


def test_gateway_config_alone_is_used():
    assert paths.gateway_config({"GATEWAY_CONFIG": str(BEDROCK)}, DEFAULT) == str(BEDROCK)


def test_agreeing_paths_pass():
    environ = {"GATEWAY_CONFIG": str(BEDROCK), "WORKER_CONFIG": worker(str(BEDROCK))}
    assert paths.gateway_config(environ, DEFAULT) == str(BEDROCK)


def test_disagreeing_paths_stop_the_proxy():
    environ = {"GATEWAY_CONFIG": str(DEFAULT), "WORKER_CONFIG": worker(str(BEDROCK))}
    with pytest.raises(paths.ConfigMismatch):
        paths.gateway_config(environ, DEFAULT)


@pytest.mark.parametrize("saved", ["", "not json", "[]", json.dumps({"port": 4012}), json.dumps({"config": 7})])
def test_a_missing_or_odd_worker_config_is_ignored(saved):
    assert paths.gateway_config({"WORKER_CONFIG": saved}, DEFAULT) == str(DEFAULT)


def test_the_bedrock_config_keeps_the_managed_alias_managed():
    """The lab's failure: rules reading the Ollama config salted a call bound for Amazon Bedrock."""
    if str(CH05_GATEWAY) not in sys.path:
        sys.path.insert(0, str(CH05_GATEWAY))
    rules = _load("ch05_gateway_rules_for_w1_test", CH05_GATEWAY / "gateway_rules.py")
    destinations, _ = rules.read_config(BEDROCK)
    chat = destinations["larkspur-chat"]
    assert [d.hosting for d in chat] == ["managed"]
    assert [d.jurisdiction for d in chat] == ["CA"]
    data = {"model": "larkspur-chat", "extra_body": {"cache_salt": "caller"}}
    rules.set_cache_salt(data, "w1-knowledge", chat)
    assert "extra_body" not in data  # nothing extra reaches Bedrock
    restricted = {"model": "larkspur-chat-restricted"}
    rules.set_cache_salt(restricted, "w1-knowledge", destinations["larkspur-chat-restricted"])
    assert restricted["extra_body"] == {"cache_salt": "w1-knowledge"}  # the self-hosted route keeps its salt


def test_the_canada_profile_is_allowed_its_tools():
    """LiteLLM 1.106.6 doesn't know the ca. geography and drops the tools; the config allows them."""
    import yaml

    config = yaml.safe_load(BEDROCK.read_text(encoding="utf-8"))
    chat = [m for m in config["model_list"] if m["model_name"] == "larkspur-chat"]
    assert [m["litellm_params"]["model"] for m in chat] == ["bedrock/converse/ca.amazon.nova-lite-v1:0"]
    assert all("tools" in m["litellm_params"].get("allowed_openai_params", []) for m in chat)
