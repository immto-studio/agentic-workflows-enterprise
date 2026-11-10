"""Step 5's gateway configs and its continuity table: the settings the drills depend on, written out; chapter 5's
aliases and stand-in prices; the callbacks loaded by name from this folder; and a row, with evidence that resolves,
for every component the plan names."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

LAB = Path(__file__).resolve().parents[1]
CAPACITY = LAB / "capacity"
CH05_CONFIG = LAB.parent / "ch05" / "gateway" / "litellm.config.yaml"
STEP4_CONFIG = LAB / "budget" / "litellm.config.yaml"
RESULTS = LAB / "results" / "2026-11-03" / "capacity"


def config(name: str) -> dict:
    return yaml.safe_load((CAPACITY / name).read_text(encoding="utf-8"))


def by_alias(cfg: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for entry in cfg["model_list"]:
        out.setdefault(entry["model_name"], []).append(entry)
    return out


def test_the_outage_config_sets_the_cooldown_explicitly_and_keeps_chapter_5s_routes():
    cfg, ch05 = config("litellm.outage.yaml"), yaml.safe_load(CH05_CONFIG.read_text(encoding="utf-8"))
    router = cfg["router_settings"]
    assert router["allowed_fails"] != 3 and router["allowed_fails"] == 2, "1.106.6 treats an explicit 3 as unset"
    assert router["cooldown_time"] == 30
    assert cfg["litellm_settings"]["fallbacks"] == ch05["litellm_settings"]["fallbacks"]
    assert cfg["litellm_settings"]["num_retries"] == 0
    assert cfg["litellm_settings"]["callbacks"] == "ch05_hooks.hooks"
    mine, theirs = by_alias(cfg), by_alias(ch05)
    assert mine.keys() == theirs.keys()
    for alias in mine:
        (a,), (b,) = mine[alias], theirs[alias]
        assert a["model_info"] == b["model_info"], alias
        for key in ("input_cost_per_token", "output_cost_per_token", "timeout", "model"):
            assert a["litellm_params"][key] == b["litellm_params"][key], (alias, key)


def test_the_deployment_config_enforces_its_limits_and_writes_the_parallel_cap_out():
    cfg, step4 = config("litellm.deployment.yaml"), yaml.safe_load(STEP4_CONFIG.read_text(encoding="utf-8"))
    assert cfg["router_settings"]["optional_pre_call_checks"] == ["enforce_model_rate_limits"]
    (primary,) = by_alias(cfg)["larkspur-chat"]
    params = primary["litellm_params"]
    assert params["tpm"] == 100_000 and params["rpm"] == 300 and params["max_parallel_requests"] == 4
    assert cfg["litellm_settings"]["callbacks"] == ["binding_hooks.hooks", "ch05_hooks.hooks"]
    for key in ("timezone", "budget_exceeded_status_code", "num_retries"):
        assert cfg["litellm_settings"][key] == step4["litellm_settings"][key], key
    assert cfg["general_settings"] == step4["general_settings"]
    (theirs,) = by_alias(step4)["larkspur-chat"]
    for key in ("input_cost_per_token", "output_cost_per_token", "timeout", "model"):
        assert params[key] == theirs["litellm_params"][key], key


def test_the_retry_config_puts_one_deployment_in_one_group_and_two_in_order_in_the_other():
    cfg = config("litellm.retry.yaml")
    groups = by_alias(cfg)
    assert len(groups["larkspur-chat-single"]) == 1
    assert [d["litellm_params"]["order"] for d in groups["larkspur-chat-pair"]] == [1, 2]
    assert cfg["router_settings"]["num_retries"] == 2 and "litellm_settings" not in cfg


def test_the_census_configs_are_step_4s_with_the_census_callback_and_one_has_no_alerts():
    step4 = yaml.safe_load(STEP4_CONFIG.read_text(encoding="utf-8"))
    census, quiet = config("litellm.census.yaml"), config("litellm.census-no-alerts.yaml")
    assert census["model_list"] == quiet["model_list"] == step4["model_list"]
    assert census["litellm_settings"]["callbacks"] == ["binding_hooks.hooks", "ch05_hooks.hooks", "census_hooks.hooks"]
    others = {k: v for k, v in step4["litellm_settings"].items() if k != "callbacks"}
    assert {k: v for k, v in census["litellm_settings"].items() if k != "callbacks"} == others
    assert quiet["litellm_settings"] == census["litellm_settings"]
    assert census["general_settings"] == step4["general_settings"] and census["general_settings"]["alerting"]
    alerts = ("alerting", "alert_types")
    assert quiet["general_settings"] == {k: v for k, v in step4["general_settings"].items() if k not in alerts}
    assert set(census) == set(quiet) == set(step4)


def test_the_hooks_this_folder_names_are_the_other_steps_objects(tmp_path):
    """Loaded as LiteLLM loads them, by file from this folder, in a process of their own: chapter 5's callback sets
    environment defaults when it is imported, which no other test's processes should inherit."""
    import os
    import subprocess
    import sys

    script = (
        "import importlib.util, sys\n"
        "for name in ('ch05_hooks', 'binding_hooks'):\n"
        f"    spec = importlib.util.spec_from_file_location(name, r'{CAPACITY}' + '/' + name + '.py')\n"
        "    module = importlib.util.module_from_spec(spec)\n"
        "    spec.loader.exec_module(module)\n"
        "    print(name, type(module.hooks).__module__, type(module.hooks).__name__)\n")
    env = {**os.environ, "GATEWAY_LOG_FILE": str(tmp_path / "gateway.log"), "TRACE_FILE": str(tmp_path / "traces.jsonl"),
           "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.splitlines() == ["ch05_hooks gateway_hooks GatewayHooks",
                                        "binding_hooks budget_key_binding KeyBinding"]


def test_no_module_of_this_step_shares_a_name_with_another_folder_on_the_tests_path():
    mine = {p.stem for p in CAPACITY.glob("*.py")}
    for folder in ("ledger", "collector", "budget"):
        assert not mine & {p.stem for p in (LAB / folder).glob("*.py")}, folder


# --- the continuity table ---------------------------------------------------------------------------------

COMPONENTS = ("the gateway", "its database", "Redis", "Langfuse", "the audit log", "the self-hosted path",
              "W5's ledger in its fork", "the trace pipeline")


@pytest.fixture(scope="module")
def continuity() -> list[dict]:
    return yaml.safe_load((CAPACITY / "continuity.yaml").read_text(encoding="utf-8"))["components"]


def resolve(data, path: str):
    """`outage[0].cycles[1].first_failure_s` inside the drills' JSON."""
    value = data
    for part in path.replace("]", "").replace("[", ".").split("."):
        value = value[int(part)] if part.isdigit() else value[part]
    return value


def test_every_component_the_plan_names_has_a_row(continuity):
    assert tuple(r["component"] for r in continuity) == COMPONENTS
    for row in continuity:
        for key in ("failure_mode", "recovery_objective", "evidence"):
            assert row[key] and len(row[key]) > 20, (row["component"], key)
        assert row["sources"], row["component"]


def test_every_number_the_evidence_cites_from_a_drill_is_the_drills(continuity):
    import summary

    files = {"drills": json.loads((RESULTS / "drills.json").read_text(encoding="utf-8")),
             "calculator": json.loads((RESULTS / "calculator.json").read_text(encoding="utf-8")),
             "limiter cache": json.loads((RESULTS / "limiter-cache.json").read_text(encoding="utf-8"))}
    budget = json.loads((LAB / "results" / "2026-11-03" / "budget" / "drills.json").read_text(encoding="utf-8"))
    collector = json.loads((LAB / "results" / "2026-11-03" / "collector" / "collector.json").read_text(encoding="utf-8"))
    files["step 4"], files["step 3"] = budget, collector
    checked = 0
    for row in continuity:
        for source in row["sources"]:
            if "drill" not in source:
                continue
            value = resolve(files[source["drill"]], source["path"])
            shown = source.get("shown") or summary.num(value)
            assert shown in row["evidence"], (row["component"], source, value)
            checked += 1
    assert checked >= 10


def test_each_fact_sheet_source_names_its_section_and_quotes_it_and_each_code_quote_is_in_its_file(continuity):
    companion = LAB.parents[1]
    for row in continuity:
        for source in row["sources"]:
            if "code" in source:
                text = (companion / source["code"]).read_text(encoding="utf-8")
                assert " ".join(source["quote"].split()) in " ".join(text.split()), row["component"]
            if "fact_sheet" in source:
                assert source["fact_sheet"] in ("section 3", "section 4", "section 5", "section 8.1", "section 8.2",
                                                "section 8.4", "section 8.5")
                assert source["quote"] and source["date"], row["component"]
