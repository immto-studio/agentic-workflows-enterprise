"""Step 8's gateway configurations and the canary's arithmetic, with no gateway and no model: the staging map, the
canary's two weighted deployments, chapter 5's rules accepting each configuration for W2, the arms and groups read
from a synthetic gateway log, the SLIs three ways, the load a call paid for, and the server watcher's summary."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

import canary

LAB = Path(__file__).resolve().parents[1]
ROOT = LAB.parents[1]
LIFECYCLE = LAB / "lifecycle"
for folder in (ROOT / "labs" / "ch05" / "gateway", ROOT / "labs" / "ch05" / "manifest"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
import gateway_rules as rules  # noqa: E402  chapter 5's rules, pure functions
import manifest as manifests  # noqa: E402

CONFIGS = {name: yaml.safe_load((LIFECYCLE / f"litellm.{name}.yaml").read_text(encoding="utf-8"))
           for name in ("current", "staging", "canary")}
W2 = manifests.load_manifests(ROOT / "workflows" / "w2-ops-assistant" / "manifest")
TAGS = {"workflow": "w2-ops-assistant", "data_class": "internal"}
TRACE = "0" * 32


def by_alias(config: dict, alias: str) -> list[dict]:
    return [e for e in config["model_list"] if e["model_name"] == alias]


def test_the_current_map_is_w2s_on_the_portable_server():
    w2 = yaml.safe_load((ROOT / "workflows/w2-ops-assistant/gateway/litellm.config.yaml").read_text(encoding="utf-8"))
    mine = CONFIGS["current"]
    assert [e["model_info"]["id"] for e in mine["model_list"]] == [e["model_info"]["id"] for e in w2["model_list"]]
    assert all(e["litellm_params"]["model"] == "ollama_chat/gpt-oss:20b" for e in mine["model_list"])
    assert {e["litellm_params"]["api_base"] for e in mine["model_list"]} == {"http://127.0.0.1:11435"}


def test_the_staging_map_puts_the_candidate_behind_the_alias_alone():
    chat = by_alias(CONFIGS["staging"], "larkspur-chat")
    assert len(chat) == 1 and chat[0]["litellm_params"]["model"] == "ollama_chat/gemma4:12b"
    assert chat[0]["model_info"]["id"] == "candidate-gemma4-12b-chat" and chat[0]["litellm_params"]["think"] is False
    restricted = by_alias(CONFIGS["staging"], "larkspur-chat-restricted")
    assert len(restricted) == 1 and restricted[0]["litellm_params"]["model"] == "ollama_chat/gpt-oss:20b"
    assert "think" not in restricted[0]["litellm_params"]
    assert all(e["litellm_params"]["num_ctx"] == 16384 for e in CONFIGS["staging"]["model_list"])


def test_the_canary_has_two_weighted_deployments_on_one_server():
    arms = canary.arms_of()
    assert {a["arm"]: a["share"] for a in arms.values()} == {"control": 0.75, "candidate": 0.25}
    assert arms["local-gpt-oss-20b-chat"]["weight"] == 3 and arms["candidate-gemma4-12b-chat"]["weight"] == 1
    assert arms["candidate-gemma4-12b-chat"]["think"] is False and arms["local-gpt-oss-20b-chat"]["think"] == "model default"
    assert {a["api_base"] for a in arms.values()} == {"http://127.0.0.1:11435"}
    assert CONFIGS["canary"]["router_settings"]["routing_strategy"] == "simple-shuffle"
    assert len(by_alias(CONFIGS["canary"], "larkspur-chat-restricted")) == 1
    for e in CONFIGS["canary"]["model_list"]:
        assert e["model_info"]["region"] == "ca-central-1" and e["model_info"]["hosting"] == "self-hosted"


@pytest.mark.parametrize("name", ["current", "staging", "canary"])
def test_chapter_5s_rules_accept_each_configuration_for_w2_and_refuse_what_they_should(name):
    destinations, fallbacks = rules.read_config(LIFECYCLE / f"litellm.{name}.yaml")
    assert len(destinations["larkspur-chat"]) == (2 if name == "canary" else 1)
    ok = rules.decide("larkspur-chat", TAGS, TRACE, W2, destinations, fallbacks)
    assert ok.refused is None and ok.no_fallback is None
    above = rules.decide("larkspur-chat", {**TAGS, "data_class": "confidential"}, TRACE, W2, destinations, fallbacks)
    assert above.refused and "above the maximum" in above.refused
    other = rules.decide("larkspur-chat-fallback", TAGS, TRACE, W2, destinations, fallbacks)
    assert other.refused and "not a model in the manifest" in other.refused


def _log_line(ts: str, trace: str, deployment: str, latency_ms: int, event: str = "call") -> dict:
    model = {"local-gpt-oss-20b-chat": "gpt-oss:20b", "candidate-gemma4-12b-chat": "gemma4:12b"}[deployment]
    return {"ts": ts, "event": event, "trace_id": trace, "workflow": "w2-ops-assistant", "data_class": "internal",
            "requested_alias": "larkspur-chat", "served_alias": "larkspur-chat", "fallback": False, "deployment": deployment,
            "region": "ca-central-1", "served_model": model, "prompt_tokens": 900, "completion_tokens": 40, "latency_ms": latency_ms}


def _output(trace: str, case: str, answer: str, seconds: float, reads: int = 1, calls: int = 2, error: str | None = None) -> dict:
    return {"workflow": "w2", "model": "canary", "variant": "golden", "case": case, "trace_id": trace, "seconds": seconds,
            "error": error, "output": {"id": case, "answer": answer, "read_events": [{"tool": "get_pod_status", "ok": True}] * reads,
                                       "model_calls": [{"latency_s": 0.5}] * calls, "calls": [], "persona": "oncall.engineer",
                                       "trap": "none", "typography": {}}}


def test_arms_groups_ends_and_loads_from_a_synthetic_log(tmp_path):
    sentences = canary.slis.sentences()
    # Four runs: pure control, pure candidate, mixed, and a budget stop on the control; the candidate call of the
    # mixed run paid for a load the watcher saw.
    t = {"a": "a" * 32, "b": "b" * 32, "c": "c" * 32, "d": "d" * 32}
    lines = [_log_line("2026-11-09T12:00:01.000+00:00", t["a"], "local-gpt-oss-20b-chat", 800),
             _log_line("2026-11-09T12:00:02.000+00:00", t["a"], "local-gpt-oss-20b-chat", 900),
             _log_line("2026-11-09T12:00:20.000+00:00", t["b"], "candidate-gemma4-12b-chat", 15000),
             _log_line("2026-11-09T12:00:21.000+00:00", t["b"], "candidate-gemma4-12b-chat", 400),
             _log_line("2026-11-09T12:00:25.000+00:00", t["c"], "local-gpt-oss-20b-chat", 3500),
             _log_line("2026-11-09T12:00:31.000+00:00", t["c"], "candidate-gemma4-12b-chat", 5500),
             _log_line("2026-11-09T12:00:40.000+00:00", t["d"], "local-gpt-oss-20b-chat", 6000)]
    log = tmp_path / "gateway.jsonl"
    log.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    base = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc).timestamp()
    samples = [{"at": base + 0.5, "loaded": ["gpt-oss:20b"], "size_vram": 1}, {"at": base + 6.0, "loaded": [], "size_vram": 0},
               {"at": base + 19.0, "loaded": ["gemma4:12b"], "size_vram": 1}, {"at": base + 22.5, "loaded": [], "size_vram": 0},
               {"at": base + 24.5, "loaded": ["gpt-oss:20b"], "size_vram": 1}, {"at": base + 26.0, "loaded": [], "size_vram": 0},
               {"at": base + 30.0, "loaded": ["gemma4:12b"], "size_vram": 1}, {"at": base + 35.0, "loaded": ["gpt-oss:20b"], "size_vram": 1}]
    budget = sentences.w2_refusal
    (tmp_path / "pass-1").mkdir()
    outputs = [_output(t["a"], "w2-01", "claims-api has 2 of 3 pods ready.", 2.1),
               _output(t["b"], "w2-02", "No alerts fired for claims-api.", 15.9),
               _output(t["c"], "w2-03", "The pod is crash-looping.", 9.4),
               _output(t["d"], "w2-04", budget, 7.0, reads=sentences.w2_max_reads, calls=sentences.w2_max_reads + 1)]
    (tmp_path / "pass-1" / "outputs.jsonl").write_text("".join(json.dumps(o) + "\n" for o in outputs), encoding="utf-8")
    calls, runs = canary.collect(tmp_path, 1, log, canary.arms_of(), samples)
    groups = {r["case"]: r["group"] for r in runs}
    assert groups == {"w2-01": "control", "w2-02": "candidate", "w2-03": "mixed", "w2-04": "control"}
    assert {r["case"]: r["end"] for r in runs} == {"w2-01": "answer", "w2-02": "answer", "w2-03": "answer", "w2-04": "budget_stop"}
    mixed = next(c for c in calls if c["trace_id"] == t["c"] and c["arm"] == "candidate")
    assert mixed["swap_during"] is True and mixed["after_model_change"] is True
    assert mixed["load_s"] == pytest.approx(4.5, abs=0.01)  # began at 25.5, loaded at 30.0
    assert mixed["latency_ms_without_load"] == 1000
    # The mixed run's control call paid 3.0 s for gpt-oss's load (began at 21.5, loaded at 24.5) and its candidate
    # call 4.5 s for Gemma's, so 7.5 s of its 9.4 come out.
    assert next(r for r in runs if r["case"] == "w2-03")["seconds_without_loads"] == pytest.approx(9.4 - 7.5, abs=0.01)
    steady = next(c for c in calls if c["trace_id"] == t["a"])
    assert steady["swap_during"] is False and steady["load_s"] == 0.0

    result = canary.analyze(calls, runs, canary.arms_of(), True)
    assert result["runs"]["by_group"] == {"candidate": 1, "control": 2, "mixed": 1, "none": 0}
    assert result["calls"]["total"] == 7 and result["by_arm"]["candidate"]["calls"] == 3
    assert result["by_arm"]["candidate"]["share_of_calls"] == pytest.approx(3 / 7, abs=1e-4)
    touched = result["by_arm"]["candidate"]["runs_touched"]
    assert touched["runs"] == 2 and touched["success"] == {"good": 2, "valid": 2, "value": 1.0}
    control = result["by_arm"]["control"]["runs_touched"]
    assert control["runs"] == 3 and control["success"] == {"good": 2, "valid": 3, "value": pytest.approx(2 / 3, abs=1e-6)}
    assert touched["latency"]["good"] == 1 and touched["latency"]["valid"] == 2  # the 15.9 s run is over 10 s as measured
    assert touched["latency_without_loads"]["good"] == 2  # 15.9 less its 14 s load; the mixed run under 10 either way
    assert result["by_group"]["mixed"]["runs"] == 1 and result["by_group"]["candidate"]["runs"] == 1
    assert result["by_arm"]["candidate"]["load_s_total"] == pytest.approx(14.0 + 4.5, abs=0.02)
    assert result["by_arm"]["control"]["load_s_total"] == pytest.approx(3.0 + 1.0, abs=0.02)


def test_the_watcher_counts_loads_and_whether_both_models_were_ever_resident():
    watcher = canary.Loaded("http://127.0.0.1:1")
    watcher.samples = [{"at": 0.0, "loaded": ["gpt-oss:20b"], "size_vram": 5}, {"at": 10.0, "loaded": [], "size_vram": 0},
                       {"at": 12.0, "loaded": ["gemma4:12b"], "size_vram": 3}, {"at": 30.0, "loaded": ["gpt-oss:20b"], "size_vram": 5},
                       {"at": 31.0, "loaded": ["gemma4:12b", "gpt-oss:20b"], "size_vram": 8}]
    summary = watcher.summary()
    assert summary["loads"] == {"gemma4:12b": 2, "gpt-oss:20b": 1} and summary["changes"] == 5
    assert summary["resident_s"] == {"gpt-oss:20b": 11.0, "gemma4:12b": 18.0} and summary["both_at_once"] is True
    assert summary["max_size_vram"] == 8
