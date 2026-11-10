"""The cloud session's committed results (results/2026-11-09/cloud): the summary is what cloud_summary.py writes from
them, the README's step 7 tables are the summary's, join.py prints join.txt again from the kept stores and events,
the measurements the README cites are in the files, and nothing in them names the account, a key, a principal, an
address, a public IP address, or a path of this machine.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import cloud_session
import cloud_summary
import join

LAB = Path(__file__).resolve().parents[1]
RESULTS = LAB / "results" / "2026-11-09" / "cloud"
STEP7 = "## The cloud session (step 7)"
FILES = ("budget.json", "transaction-search.json", "export-run.json", "langfuse-vm.json", "bedrock.json", "tool-role.json",
         "cloudtrail-events.json", "join.txt", "cost-explorer.json", "teardown.json", "leftovers.json",
         "terraform-apply-1-errors.txt", "summary.md", "export-run/harness.jsonl", "export-run/server.jsonl",
         "export-run/gateway.jsonl", "export-run/spans.jsonl", "export-run/runs.jsonl", "export-run/sink-times.json",
         "export-run/langfuse-observations.json", "export-run/cloudwatch-sample-record.json", "export-run/collector-metrics.txt")


def load(name: str) -> dict:
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def test_every_file_of_the_session_is_there():
    for name in FILES:
        assert (RESULTS / name).is_file(), name


def test_the_summary_is_what_the_generator_writes_from_the_committed_files():
    assert cloud_summary.render(RESULTS) == (RESULTS / "summary.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert cloud_summary.render(RESULTS) == cloud_summary.render(RESULTS)


def test_the_readmes_step_7_tables_are_the_summarys():
    readme = (LAB / "README.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    summary = (RESULTS / "summary.md").read_text(encoding="utf-8").replace("\r\n", "\n").splitlines()
    section, rows = "", []
    for line in readme.splitlines():
        if line.startswith("## "):
            section = line
        if section == STEP7 and line.startswith("|") and not line.startswith("|---"):
            rows.append(line)
    assert len(rows) >= 30
    for row in rows:
        assert row in summary, row


def test_nothing_kept_names_the_account_a_key_a_principal_an_address_or_this_machine():
    for path in RESULTS.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\b[0-9]{12}\b", text), path.name
        assert not re.search(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b", text), path.name
        assert not re.search(r"\b(AIDA|AROA)[A-Z0-9]{16,}\b", text), path.name
        assert not cloud_session._EMAIL.search(text), path.name
        assert not re.search(r"(?<![A-Za-z])[A-Za-z]:[\\/]|AppData|Users[\\/]|/tmp/", text), path.name  # a drive, never http://
        assert "pk-lf-" not in text and "sk-lf-" not in text, path.name
        assert ":user/<user>" in text or ":user/" not in text, path.name
        assert not re.search(r'"userName":\s*"(?!<user>")', text), path.name  # CloudTrail's user names, the role's included
        for ip in re.findall(r"(?<![\w:.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])", text):
            assert ip.startswith(("127.", "10.", "0.0.0.0", "169.254.")), (path.name, ip)


def test_join_prints_the_run_again_from_the_kept_stores_and_events():
    run = load("tool-role.json")["run"]
    trail = join.CloudTrail(RESULTS / "cloudtrail-events.json")
    stores = [*join.local_stores(RESULTS / "export-run"), trail]
    joined = join.join(run["trace_id"], stores)
    assert cloud_session.redact_text(join.render(run["trace_id"], joined)) == (RESULTS / "join.txt").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert {r["matched_by"] for r in joined["CloudTrail"]} == {"AssumeRole, session tag trace_id", "role session name in userIdentity.arn"}
    assert len(joined["spans"]) == 11 and len(joined["gateway cost lines"]) == 2
    read = next(e for e in trail.events if e.get("eventName") == "DescribeInstances" and not e.get("errorCode"))
    assert join.trace_for_event(read, stores, trail) == [run["trace_id"]]


def test_the_live_run_reached_both_stores_whole():
    export = load("export-run.json")
    run, cw, lf = export["run"], export["cloudwatch"], export["langfuse"]
    assert run["runs"] == 25 and run["spans_sent"] == run["spans_left_collector"] == run["spans_in_file"] == 257
    assert run["traces_with_every_span_left"] == 25
    assert cw["traces_complete"] == 25 and sum(cw["spans_found"].values()) == 257 and cw["trace_id_key"] == "traceId"
    assert cw["xray"]["ours_indexed"] == 0 and cw["xray"]["indexing_percent"] == 1.0
    assert cw["application_signals"]["services"] == []
    assert cw["insights"]["status"] == "Complete" and cw["insights"]["rows"] == 25
    comparison = lf["comparison"]
    assert lf["traces_complete"] == 25 and comparison["traces_with_every_span"] == 25
    assert comparison["cost_rows"] == 45 == comparison["cost_read_from_gen_ai_usage_cost"]
    assert all(r["tokens_equal"] for r in comparison["gateway_spans_with_cost"])
    assert comparison["tracestate_anywhere"] is False and comparison["span_attributes_kept_as_metadata"] is True
    assert lf["health"]["body"]["version"] == "4.74.0"
    sample = load("export-run/cloudwatch-sample-record.json")
    assert "traceState" not in sample and sample["scope"]["attributes"]["tailsampling.policy"] == "share-of-the-rest"


def test_the_bedrock_records_carry_the_trace_id_and_the_profiles_serving_region():
    bedrock = load("bedrock.json")
    calls, trail = bedrock["calls"], bedrock["cloudtrail"]
    attempts = calls["canada"]["attempts"]
    assert attempts[0]["call"]["ok"] is False and "ca-west-1" in attempts[0]["call"]["body"]
    assert attempts[1]["call"]["ok"] is True and attempts[1]["gateway"]["cost_lines"][-1]["region"] == "ca-central-1"
    for name in ("us_text_off", "us_text_on", "us_profile"):
        shape = calls[name]["record_shape"]
        assert shape["request_metadata"]["trace_id"] == calls["trace_ids"][name]
        assert shape["request_metadata"]["workflow"] == "w2-ops-assistant"
        assert trail["ours"][name]["found"] and trail["ours"][name]["request_id_matches_log"]
    assert calls["us_text_off"]["record_shape"]["text_fields_present"] == []
    assert calls["us_text_on"]["record_shape"]["text_fields_present"] == ["inputBodyJson", "outputBodyJson"]
    assert calls["us_profile"]["record_shape"]["inference_region"] == "us-west-2" == trail["ours"]["us_profile"]["inference_region_cloudtrail"]
    assert calls["us_text_off"]["record_shape"]["inference_region"] is None
    assert all(not v["ok"] for v in calls["canada_side"].values())


def test_the_tool_role_and_the_deny_all_as_measured():
    run = load("tool-role.json")["run"]
    assert run["assume"]["ok"] and run["read"]["ok"]
    assert len(run["refusals"]) == 4 and all(r["refused"] and r["code"] == "AccessDenied" for r in run["refusals"])
    deny = run["deny_all"]
    assert deny["first_denied_code"] == "UnauthorizedOperation" and deny["first_denied_s"] == 8.232
    assert deny["later_session"]["ok"] and deny["later_session_first_success_s"] == 8.197
    assert deny["calls_that_passed_after_pull"] == 9 and deny["later_session_refusals_before_success"] == 7
    assert deny["issued_before_release_after"]["ok"] is False and deny["later_session_after_purge"]["ok"] is True
    assert deny["purge"]["results"][0]["action"] == "deleted"
    trail = load("tool-role.json")["cloudtrail"]
    assert trail["by_name"]["AssumeRole"] == 2 and trail["assume_role_with_tags"] == 2 and trail["with_access_key_id"] == trail["events"]


def test_the_teardown_left_nothing_and_the_budget_was_first_and_last():
    teardown = load("teardown.json")
    assert teardown["destroy"]["resources_destroyed"] == 22
    left = teardown["leftovers"]
    assert left["instances_not_terminated"] == [] and left["vpcs"] == 0 and left["budgets"] == [] and left["sns_topics"] == []
    assert all(not v["exists"] for v in left["iam_roles"].values())
    assert all(v == "absent" for v in left["log_groups"].values()) and left["invocation_logging"] is False
    assert left["logs_resource_policies"] == [] and left["xray_destination"]["Destination"] == "XRay"
    assert "EC2 instances not terminated: 0" in teardown["aws_sweep"]["lines"]
    budget = load("budget.json")
    assert budget["start"]["budget"]["limit"]["Amount"] == "5.0" and budget["end"]["budget"]["limit"]["Amount"] == "5.0"
    assert all(s["address_kind"] == "sns-topic" for n in budget["start"]["budget"]["notifications"] for s in n["subscribers"])
    assert budget["start"]["plan"]["remaining_credits"]["amount"] == 139.38
    assert budget["end"]["plan"]["remaining_credits"]["amount"] == 159.38
    off = load("transaction-search.json")["off"]["after"]
    assert off["destination"] == "XRay" and off["resource_policy_present"] is False
    assert not off["log_groups"]["aws/spans"]["exists"]


def test_cost_explorer_answered_and_the_days_are_aligned_in_tokens():
    ce = load("cost-explorer.json")
    assert ce["answers"] and ce["filter"] == "product attribute model = Nova Lite" and ce["requests"] == 1
    aligned = ce["aligned"]
    assert aligned["ledger_calls"] == 48 and aligned["bill_input_tokens"] > aligned["ledger_input_tokens"]
    assert aligned["bill_cost_usd"] == 0.0 and aligned["bill_at_the_tables_price_usd"] > 0
    assert (aligned["input_ratio_bill_over_ledger"], aligned["output_ratio_bill_over_ledger"], aligned["cost_ratio_at_list_price"]) == (1.084, 1.927, 1.229)
    assert aligned["bill_input_tokens"] - aligned["ledger_input_tokens"] == 6801
    assert aligned["bill_output_tokens"] - aligned["ledger_output_tokens"] == 3951
    assert {r["usage_type"] for r in ce["rows"]} >= {"CAN1-NovaLite-input-tokens", "USE2-NovaLite-input-tokens"}
