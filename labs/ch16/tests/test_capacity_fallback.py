"""Step 5b's fallback inside Canada: chapter 5's rules turn W3's chain off and leave W2's on, chapter 2's grid lets
W3's Confidential call reach the self-hosted alias, and `fallback_hooks.py` gives W3 that hop and nothing else, on
chapter 16's outage config, with chapter 5's config and code unchanged."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import fallback_hooks
import gateway_rules as rules
import manifest as manifests
import yaml

LAB = Path(__file__).resolve().parents[1]
CAPACITY = LAB / "capacity"
CANADA = CAPACITY / "litellm.outage-canada.yaml"
KNOWN = manifests.load_manifests(LAB.parent / "ch05" / "manifest")
W2_TAGS = {"workflow": "w2-ops-assistant", "data_class": "internal"}
W3_TAGS = {"workflow": "w3-incident", "data_class": "confidential"}


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_the_canada_config_is_step_5s_outage_config_with_the_section_and_the_hook():
    cfg, step5 = load(CANADA), load(CAPACITY / "litellm.outage.yaml")
    ch05 = load(LAB.parent / "ch05" / "gateway" / "litellm.config.yaml")
    assert cfg["model_list"] == step5["model_list"] and cfg["router_settings"] == step5["router_settings"]
    assert cfg["litellm_settings"]["fallbacks"] == step5["litellm_settings"]["fallbacks"] == \
        ch05["litellm_settings"]["fallbacks"], "W2's chain is chapter 5's, one hop to us-east-2"
    assert cfg["litellm_settings"]["callbacks"] == ["ch05_hooks.hooks", "fallback_hooks.hooks"]
    assert cfg[fallback_hooks.SECTION] == {"larkspur-chat": ["larkspur-chat-restricted"]}
    assert set(cfg) - set(step5) == {fallback_hooks.SECTION}
    assert fallback_hooks.SECTION not in ch05, "chapter 5's config is unchanged"


def test_chapter_5s_rules_turn_w3s_chain_off_and_leave_w2s_on():
    destinations, fallbacks = rules.read_config(CANADA)
    w3 = rules.decide("larkspur-chat", W3_TAGS, "t3", KNOWN, destinations, fallbacks)
    assert w3.refused is None and "larkspur-chat-fallback" in w3.no_fallback and "us-east-2" in w3.no_fallback
    assert rules.decide("larkspur-chat", W2_TAGS, "t2", KNOWN, destinations, fallbacks) == rules.Decision()


def test_the_grid_lets_a_confidential_call_reach_the_self_hosted_alias_in_canada():
    destinations, _ = rules.read_config(CANADA)
    (self_hosted,) = destinations["larkspur-chat-restricted"]
    assert (self_hosted.region, self_hosted.jurisdiction, self_hosted.hosting) == ("ca-central-1", "CA", "self-hosted")
    assert rules.may_receive("confidential", self_hosted) and rules.may_receive("restricted", self_hosted)
    (abroad,) = destinations["larkspur-chat-fallback"]
    assert not rules.may_receive("confidential", abroad)


def test_a_request_gets_only_the_named_hops_its_class_and_regions_allow():
    destinations, _ = rules.read_config(CANADA)
    inside = fallback_hooks.read_section(CANADA)
    assert fallback_hooks.hops_for("larkspur-chat", W3_TAGS, KNOWN, destinations, inside) == ["larkspur-chat-restricted"]
    both = {"larkspur-chat": ["larkspur-chat-fallback", "larkspur-chat-restricted"]}
    assert fallback_hooks.hops_for("larkspur-chat", W3_TAGS, KNOWN, destinations, both) == ["larkspur-chat-restricted"]
    assert fallback_hooks.hops_for("larkspur-chat-restricted", {**W3_TAGS, "data_class": "restricted"}, KNOWN,
                                   destinations, inside) == [], "no fallback rescues a Restricted call"
    assert fallback_hooks.hops_for("larkspur-chat", {"workflow": "nobody", "data_class": "internal"}, KNOWN,
                                   destinations, inside) == []


def test_the_hook_gives_w3_its_hop_and_leaves_w2_alone(tmp_path):
    hooks = fallback_hooks.InJurisdiction()
    hooks.log = tmp_path / "gateway.log"

    def request(tags: dict, disabled: bool) -> dict:
        return {"model": "larkspur-chat", "disable_fallbacks": disabled,
                "metadata": {"tags": [f"{k}:{v}" for k, v in tags.items()], "trace_id": "t", "fallbacks_disabled": disabled}}

    w3 = asyncio.run(hooks.async_pre_call_hook(None, None, request(W3_TAGS, True), "acompletion"))
    assert w3["fallbacks"] == [{"larkspur-chat": ["larkspur-chat-restricted"]}] and w3["disable_fallbacks"] is False
    assert w3["metadata"]["fallbacks_disabled"] is False
    assert w3["metadata"]["fallback_in_jurisdiction"] == ["larkspur-chat-restricted"]
    w2 = asyncio.run(hooks.async_pre_call_hook(None, None, request(W2_TAGS, False), "acompletion"))
    assert "fallbacks" not in w2 and w2["disable_fallbacks"] is False, "chapter 5's chain, untouched"
    (line,) = [json.loads(x) for x in hooks.log.read_text(encoding="utf-8").splitlines()]
    assert line["event"] == "fallback_in_jurisdiction" and line["tags"] == W3_TAGS
    assert line["fallbacks"] == ["larkspur-chat-restricted"]


def test_the_new_hooks_load_as_litellm_loads_them(tmp_path):
    """By file, from this folder, in a process of their own, as test_capacity_configs loads step 5's."""
    script = (
        "import importlib.util, sys\n"
        "for name in ('fallback_hooks', 'store_hooks', 'census_hooks'):\n"
        f"    spec = importlib.util.spec_from_file_location(name, r'{CAPACITY}' + '/' + name + '.py')\n"
        "    module = importlib.util.module_from_spec(spec)\n"
        "    spec.loader.exec_module(module)\n"
        "    print(name, type(module.hooks).__name__)\n")
    env = {"GATEWAY_CONFIG": str(CANADA), "GATEWAY_LOG_FILE": str(tmp_path / "gateway.log"), "PYTHONDONTWRITEBYTECODE": "1",
           "LITELLM_LOCAL_MODEL_COST_MAP": "True", "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")}
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env, timeout=180)
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.splitlines() == ["fallback_hooks InJurisdiction", "store_hooks StoreWatch", "census_hooks Census"]
