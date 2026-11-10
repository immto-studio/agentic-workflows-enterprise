"""Step 7's scripts, offline: botocore's Stubber answers for AWS and no call is made.

The redaction every kept file goes through; the environment check; the budget read back; Transaction Search's
status and the three calls that turn it on; the gateway's requestMetadata hook, through LiteLLM's own Converse
transformation; the invocation record's shape; the tool role's session name, its AssumeRole request, and the
deny-all drill's timing on stubbed answers; the CloudWatch and Langfuse comparisons on fixtures; Cost Explorer's
rows and the reconciliation; and the sweep's names against the Terraform's.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import bedrock_calls
import botocore.session
import cloud_budget
import cloud_session
import cloudwatch_spans
import cost_explorer
import export_run
import langfuse_check
import leftovers
import pytest
import request_metadata_hooks
import tool_role
import transaction_search
import tunnel
from botocore.stub import Stubber

LAB = Path(__file__).resolve().parents[1]
ACCOUNT = "123456789012"
TRACE = "7d3e0c5f9a1b4c2e8f6a0b1c2d3e4f5a"
NOW = datetime(2026, 11, 9, 12, 0, 0, tzinfo=timezone.utc)


class FakeSession:
    """boto3.Session's `client`, answering with one stubbed client per service."""

    region_name = "us-east-2"

    def __init__(self, **clients: Any) -> None:
        self.clients = clients

    def client(self, name: str, **kwargs: Any) -> Any:
        return self.clients[name.replace("-", "_")]


def stubbed(service: str, region: str = "us-east-2") -> tuple[Any, Stubber]:
    client = botocore.session.get_session().create_client(
        service, region_name=region, aws_access_key_id="LARKSPURLABDUMMYKEY0", aws_secret_access_key="dummy-secret-for-the-stubber")
    return client, Stubber(client)


# --- redaction and the environment ------------------------------------------------------------------------

def test_redaction_replaces_what_must_never_be_kept_and_nothing_else():
    text = (f"arn:aws:iam::{ACCOUNT}:user/administrator made ASIAEXAMPLERUNA00001 and ASIAEXAMPLERUNB00002 for "
            f"AROAEXAMPLERESTART01:session from 203.0.113.9; owner tomasz.nowak@larkspur.example; trace {TRACE}; "
            "vpc 10.46.0.1 and 127.0.0.1; token FwoGZXIvYXdzEBYaDExampleExampleExampleExample")
    out = cloud_session.redact_text(text)
    assert "<account>" in out and ACCOUNT not in out
    assert "user/<user>" in out and "administrator" not in out
    assert "ASIAEXAMPLERUNA00001" not in out and "asia-" in out
    assert out.count("asia-") == 2 and len({w for w in out.split() if w.startswith("asia-")}) == 2  # distinct per key
    assert "<principal-id>" in out and "<ip>" in out and "203.0.113.9" not in out
    assert "10.46.0.1" in out and "127.0.0.1" in out
    assert "<address>" in out and "larkspur.example" not in out
    assert "<session-token>" in out
    assert TRACE in out
    assert cloud_session.redact_text(out) == out  # a second pass changes nothing


def test_the_same_key_gets_the_same_placeholder_so_join_still_matches_by_it():
    assert cloud_session.stable_key("ASIAEXAMPLERUNA00001") == cloud_session.stable_key("ASIAEXAMPLERUNA00001")
    assert cloud_session.stable_key("ASIAEXAMPLERUNA00001") != cloud_session.stable_key("ASIAEXAMPLERUNA00002")
    assert "EXAMPLE" not in cloud_session.stable_key("ASIAEXAMPLERUNA00001")


def test_redact_keeps_json_shapes():
    value = {"Arn": f"arn:aws:sts::{ACCOUNT}:assumed-role/w3-incident-get-pod-status/x.7d3e0c5f9a1b4c2e", "n": 3,
             "keys": ["ASIAEXAMPLERUNA00001"]}
    out = cloud_session.redact(value)
    assert out["n"] == 3 and out["Arn"].startswith("arn:aws:sts::<account>:assumed-role/")
    assert out["keys"] == [cloud_session.stable_key("ASIAEXAMPLERUNA00001")]


def test_the_environment_check_refuses_anything_but_the_briefs_shape(tmp_path):
    credentials = tmp_path / "aws-credentials"
    credentials.write_text("[book-lab]\n", encoding="utf-8")
    good = {"AWS_SHARED_CREDENTIALS_FILE": str(credentials), "AWS_CONFIG_FILE": str(tmp_path / "missing"),
            "AWS_PROFILE": "book-lab", "AWS_DEFAULT_REGION": "us-east-2"}
    assert cloud_session.require_environment(good) == good
    with pytest.raises(SystemExit):
        cloud_session.require_environment({k: v for k, v in good.items() if k != "AWS_PROFILE"})
    with pytest.raises(SystemExit):
        cloud_session.require_environment(good | {"AWS_PROFILE": "default"})
    with pytest.raises(SystemExit):
        cloud_session.require_environment(good | {"AWS_DEFAULT_REGION": "ca-central-1"})
    (tmp_path / "config").write_text("", encoding="utf-8")
    with pytest.raises(SystemExit):
        cloud_session.require_environment(good | {"AWS_CONFIG_FILE": str(tmp_path / "config")})
    env = cloud_session.aws_environment(good)
    assert env["AWS_REGION"] == "us-east-2" and env["AWS_EC2_METADATA_DISABLED"] == "true"
    assert "AWS_ACCESS_KEY_ID" not in env


# --- the budget ----------------------------------------------------------------------------------------------

def test_the_budget_read_back_names_the_sns_subscriber_and_never_an_address():
    client, stub = stubbed("budgets", "us-east-1")
    topic = f"arn:aws:sns:us-east-2:{ACCOUNT}:ch16-cloud-budget"
    stub.add_response("describe_budget", {"Budget": {
        "BudgetName": "ch16-cloud-session", "BudgetType": "COST", "TimeUnit": "MONTHLY",
        "BudgetLimit": {"Amount": "5.0", "Unit": "USD"},
        "CalculatedSpend": {"ActualSpend": {"Amount": "0.0", "Unit": "USD"}},
        "TimePeriod": {"Start": NOW, "End": NOW}}}, {"AccountId": ACCOUNT, "BudgetName": "ch16-cloud-session"})
    notifications = [{"NotificationType": "ACTUAL", "ComparisonOperator": "GREATER_THAN", "Threshold": t,
                      "ThresholdType": "PERCENTAGE", "NotificationState": "OK"} for t in (80.0, 100.0)]
    stub.add_response("describe_notifications_for_budget", {"Notifications": notifications},
                      {"AccountId": ACCOUNT, "BudgetName": "ch16-cloud-session"})
    for notification in notifications:
        stub.add_response("describe_subscribers_for_notification", {"Subscribers": [{"SubscriptionType": "SNS", "Address": topic}]},
                          {"AccountId": ACCOUNT, "BudgetName": "ch16-cloud-session", "Notification": notification})
    with stub:
        out = cloud_budget.read_back(client, ACCOUNT, "ch16-cloud-session")
        stub.assert_no_pending_responses()
    assert out["limit"] == {"Amount": "5.0", "Unit": "USD"} and out["time_unit"] == "MONTHLY"
    assert [n["threshold"] for n in out["notifications"]] == [80.0, 100.0]
    assert all(s == {"type": "SNS", "address_kind": "sns-topic"} for n in out["notifications"] for s in n["subscribers"])
    assert topic not in json.dumps(out, default=str)


# --- Transaction Search ------------------------------------------------------------------------------------

def destination(dest: str, status: str) -> dict[str, str]:
    return {"Destination": dest, "Status": status}


def rules(percent: float) -> dict[str, Any]:
    return {"IndexingRules": [{"Name": "Default", "Rule": {"Probabilistic": {"DesiredSamplingPercentage": percent}}}]}


def add_status(xray_stub: Stubber, logs_stub: Stubber, *, dest: str, percent: float, policies: list[str], groups: list[str]) -> None:
    xray_stub.add_response("get_trace_segment_destination", destination(dest, "ACTIVE"), {})
    xray_stub.add_response("get_indexing_rules", rules(percent), {})
    logs_stub.add_response("describe_resource_policies", {"resourcePolicies": [{"policyName": p} for p in policies]}, {})
    for name in (transaction_search.SPANS_GROUP, transaction_search.SIGNALS_GROUP):
        logs_stub.add_response("describe_log_groups", {"logGroups": [{"logGroupName": name, "storedBytes": 10}] if name in groups else []},
                               {"logGroupNamePrefix": name})


def test_the_policy_names_the_two_groups_and_the_xray_principal():
    document = transaction_search.policy_document(ACCOUNT, "us-east-2")
    statement = document["Statement"][0]
    assert statement["Principal"] == {"Service": "xray.amazonaws.com"} and statement["Action"] == "logs:PutLogEvents"
    assert statement["Resource"] == [f"arn:aws:logs:us-east-2:{ACCOUNT}:log-group:aws/spans:*",
                                     f"arn:aws:logs:us-east-2:{ACCOUNT}:log-group:/aws/application-signals/data:*"]
    assert statement["Condition"]["StringEquals"] == {"aws:SourceAccount": ACCOUNT}
    assert transaction_search.indexing_percent(rules(1.0)["IndexingRules"]) == 1.0
    assert transaction_search.indexing_percent([]) is None


def test_status_reads_the_four_settings():
    xray, xray_stub = stubbed("xray")
    logs, logs_stub = stubbed("logs")
    add_status(xray_stub, logs_stub, dest="XRay", percent=0.0, policies=[], groups=[])
    with xray_stub, logs_stub:
        out = transaction_search.status(FakeSession(xray=xray, logs=logs))
    assert out["destination"] == "XRay" and out["indexing_percent"] == 0.0
    assert out["resource_policy_present"] is False
    assert out["log_groups"]["aws/spans"] == {"exists": False, "stored_bytes": None}


def test_on_makes_the_pages_three_calls_and_waits_for_active(monkeypatch):
    monkeypatch.setattr(transaction_search, "POLL_EVERY", 0.0)
    xray, xray_stub = stubbed("xray")
    logs, logs_stub = stubbed("logs")
    sts, sts_stub = stubbed("sts")
    add_status(xray_stub, logs_stub, dest="XRay", percent=0.0, policies=[], groups=[])
    sts_stub.add_response("get_caller_identity", {"Account": ACCOUNT, "Arn": f"arn:aws:iam::{ACCOUNT}:user/lab", "UserId": "AIDAEXAMPLE"}, {})
    logs_stub.add_response("put_resource_policy", {"resourcePolicy": {"policyName": transaction_search.POLICY_NAME}},
                           {"policyName": transaction_search.POLICY_NAME,
                            "policyDocument": json.dumps(transaction_search.policy_document(ACCOUNT, "us-east-2"))})
    xray_stub.add_response("update_trace_segment_destination", destination("CloudWatchLogs", "PENDING"), {"Destination": "CloudWatchLogs"})
    xray_stub.add_response("get_trace_segment_destination", destination("CloudWatchLogs", "PENDING"), {})
    xray_stub.add_response("get_trace_segment_destination", destination("CloudWatchLogs", "ACTIVE"), {})
    xray_stub.add_response("get_indexing_rules", rules(0.0), {})
    xray_stub.add_response("update_indexing_rule", {"IndexingRule": {"Name": "Default", "Rule": {"Probabilistic": {"DesiredSamplingPercentage": 1.0}}}},
                           {"Name": "Default", "Rule": {"Probabilistic": {"DesiredSamplingPercentage": 1.0}}})
    add_status(xray_stub, logs_stub, dest="CloudWatchLogs", percent=1.0, policies=[transaction_search.POLICY_NAME], groups=[])
    with xray_stub, logs_stub, sts_stub:
        out = transaction_search.on(FakeSession(xray=xray, logs=logs, sts=sts))
        xray_stub.assert_no_pending_responses()
        logs_stub.assert_no_pending_responses()
    assert out["update_destination"]["status"] == "PENDING"
    assert out["active"]["reached"] is True and len(out["active"]["readings"]) == 2
    assert out["indexing_percent_after_switch"] == 0.0 and out["update_indexing_rule"]["set_to"] == 1.0
    assert out["after"]["destination"] == "CloudWatchLogs" and out["after"]["resource_policy_present"] is True


def test_off_reverses_the_three_and_restores_the_rule(monkeypatch):
    monkeypatch.setattr(transaction_search, "POLL_EVERY", 0.0)
    xray, xray_stub = stubbed("xray")
    logs, logs_stub = stubbed("logs")
    add_status(xray_stub, logs_stub, dest="CloudWatchLogs", percent=1.0, policies=[transaction_search.POLICY_NAME],
               groups=[transaction_search.SPANS_GROUP])
    xray_stub.add_response("update_trace_segment_destination", destination("XRay", "PENDING"), {"Destination": "XRay"})
    xray_stub.add_response("get_trace_segment_destination", destination("XRay", "ACTIVE"), {})
    logs_stub.add_response("delete_resource_policy", {}, {"policyName": transaction_search.POLICY_NAME})
    logs_stub.add_response("delete_log_group", {}, {"logGroupName": transaction_search.SPANS_GROUP})
    logs_stub.add_client_error("delete_log_group", "ResourceNotFoundException", "no such group",
                               expected_params={"logGroupName": transaction_search.SIGNALS_GROUP})
    xray_stub.add_response("get_indexing_rules", rules(1.0), {})
    xray_stub.add_response("update_indexing_rule", {"IndexingRule": {"Name": "Default"}},
                           {"Name": "Default", "Rule": {"Probabilistic": {"DesiredSamplingPercentage": 0.0}}})
    add_status(xray_stub, logs_stub, dest="XRay", percent=0.0, policies=[], groups=[])
    with xray_stub, logs_stub:
        out = transaction_search.off(FakeSession(xray=xray, logs=logs), 0.0)
        xray_stub.assert_no_pending_responses()
        logs_stub.assert_no_pending_responses()
    assert out["xray_again"]["reached"] is True
    assert out["log_groups"]["aws/spans"]["deleted"] is True
    assert out["log_groups"]["/aws/application-signals/data"] == {"deleted": False, "why": "no such group"}
    assert out["update_indexing_rule"]["set_to"] == 0.0 and out["after"]["destination"] == "XRay"


# --- the gateway's requestMetadata ---------------------------------------------------------------------------

def test_the_hook_puts_the_trace_id_and_the_workflow_into_request_metadata_and_owns_the_field():
    data = {"model": "larkspur-chat", "messages": [{"role": "user", "content": "hi"}], "requestMetadata": {"team": "x"},
            "metadata": {"tags": ["workflow:w3-incident", "data_class:confidential"], "trace_id": TRACE}}
    out = asyncio.run(request_metadata_hooks.hooks.async_pre_call_hook(None, None, data, "completion"))
    assert out["requestMetadata"] == {"trace_id": TRACE, "workflow": "w3-incident"}
    bad = {"model": "x", "messages": [], "metadata": {"tags": ["workflow:w2-ops-assistant"], "trace_id": "not-a-trace"}}
    assert asyncio.run(request_metadata_hooks.hooks.async_pre_call_hook(None, None, bad, "completion"))["requestMetadata"] == {"workflow": "w2-ops-assistant"}
    none = {"model": "x", "messages": [], "metadata": {}, "requestMetadata": {"team": "x"}}
    assert "requestMetadata" not in asyncio.run(request_metadata_hooks.hooks.async_pre_call_hook(None, None, none, "completion"))


def test_litellm_carries_the_pairs_into_the_converse_body():
    from litellm.llms.bedrock.chat.converse_transformation import AmazonConverseConfig
    from litellm.utils import get_optional_params

    pairs = {"trace_id": TRACE, "workflow": "w3-incident"}
    optional = get_optional_params(model="amazon.nova-lite-v1:0", custom_llm_provider="bedrock", requestMetadata=pairs,
                                   temperature=0, drop_params=True)
    body = AmazonConverseConfig().transform_request("amazon.nova-lite-v1:0", [{"role": "user", "content": "hi"}],
                                                    dict(optional), {}, {})
    assert body["requestMetadata"] == pairs
    dropped = get_optional_params(model="gpt-4o", custom_llm_provider="openai", requestMetadata=pairs, drop_params=True)
    assert "requestMetadata" not in dropped  # the fakes' deployments never see it


def test_the_two_bedrock_configs_name_the_hook_first_and_chapter_6s_deployments():
    import yaml

    ca = yaml.safe_load((LAB / "cloud" / "litellm.bedrock-ca.yaml").read_text(encoding="utf-8"))
    us = yaml.safe_load((LAB / "cloud" / "litellm.bedrock-us.yaml").read_text(encoding="utf-8"))
    for config in (ca, us):
        assert config["litellm_settings"]["callbacks"] == ["request_metadata_hooks.hooks", "ch05_bedrock_callback.hooks"]
        assert config["litellm_settings"]["num_retries"] == 0 and config["litellm_settings"]["drop_params"] is True
    by_id = {d["model_info"]["id"]: d for d in ca["model_list"]}
    assert by_id["nova-lite-ca"]["litellm_params"]["model"] == "bedrock/converse/ca.amazon.nova-lite-v1:0"
    assert by_id["nova-lite-ca"]["model_info"]["serves_from"] == ["ca-central-1", "ca-west-1"]
    assert by_id["nova-lite-us"]["litellm_params"]["aws_region_name"] == "us-east-2"
    assert us["model_list"][0]["model_name"] == "larkspur-chat" and us["model_list"][0]["model_info"]["region"] == "us-east-2"
    text = (LAB / "cloud" / "litellm.bedrock-ca.yaml").read_text(encoding="utf-8")
    assert "aws_access_key" not in text and "guardrail" not in text.split("model_list")[1].split("litellm_settings")[0].lower().replace("# ", "")


def test_the_gateway_request_is_chapter_5s_shape_without_a_tool_list():
    request = bedrock_calls.gateway_request("larkspur-chat", "w3-incident", "confidential", TRACE)
    assert request["model"] == "larkspur-chat" and "tools" not in request
    assert request["metadata"]["tags"] == ["workflow:w3-incident", "data_class:confidential"]
    assert request["metadata"]["trace_id"] == TRACE and request["temperature"] == 0


# --- the invocation record and CloudTrail's Converse events --------------------------------------------------

def record(text: bool) -> dict[str, Any]:
    out = {"schemaType": "ModelInvocationLog", "schemaVersion": "1.0", "timestamp": "2026-11-09T10:00:00Z",
           "accountId": ACCOUNT, "identity": {"arn": f"arn:aws:iam::{ACCOUNT}:user/lab"}, "region": "us-east-2",
           "inferenceRegion": "us-east-2", "requestId": "a4acf4b0-76a8-4814-bac3-65bff3098f50", "operation": "Converse",
           "modelId": "amazon.nova-lite-v1:0", "requestMetadata": {"trace_id": TRACE, "workflow": "w2-ops-assistant"},
           "input": {"inputContentType": "application/json", "inputTokenCount": 9},
           "output": {"outputContentType": "application/json", "outputTokenCount": 2}}
    if text:
        out["input"]["inputBodyJson"] = {"messages": []}
        out["output"]["outputBodyJson"] = {"output": {}}
    return out


def test_the_record_shape_tells_text_off_from_text_on():
    off = bedrock_calls.record_shape(record(False))
    assert off["request_metadata"] == {"trace_id": TRACE, "workflow": "w2-ops-assistant"}
    assert off["inference_region"] == "us-east-2" and off["text_fields_present"] == []
    assert off["input_keys"] == ["inputContentType", "inputTokenCount"] and off["input_token_count"] == 9
    on = bedrock_calls.record_shape(record(True))
    assert on["text_fields_present"] == ["inputBodyJson", "outputBodyJson"]
    assert bedrock_calls.by_trace(TRACE)(record(False)) and not bedrock_calls.by_trace("0" * 32)(record(False))


def test_converse_events_mark_ours_and_read_the_inference_region():
    trail, stub = stubbed("cloudtrail")
    event = {"eventTime": "2026-11-09T10:00:01Z", "eventName": "Converse", "awsRegion": "us-east-2",
             "requestID": "a4acf4b0-76a8-4814-bac3-65bff3098f50", "requestParameters": {"modelId": "us.amazon.nova-lite-v1:0"},
             "additionalEventData": {"inferenceRegion": "us-west-2"}, "userIdentity": {"type": "IAMUser"}}
    other = dict(event, requestID="other", additionalEventData={"inferenceRegion": "us-east-2"})
    stub.add_response("lookup_events", {"Events": [{"CloudTrailEvent": json.dumps(e)} for e in (event, other)]},
                      {"LookupAttributes": [{"AttributeKey": "EventName", "AttributeValue": "Converse"}], "StartTime": NOW, "MaxResults": 50})
    stub.add_response("lookup_events", {"Events": []},
                      {"LookupAttributes": [{"AttributeKey": "EventName", "AttributeValue": "InvokeModel"}], "StartTime": NOW, "MaxResults": 50})
    with stub:
        out = bedrock_calls.converse_events(trail, NOW, ["a4acf4b0-76a8-4814-bac3-65bff3098f50"])
    assert [e["ours"] for e in out] == [True, False]
    assert out[0]["additional_event_data"]["inferenceRegion"] == "us-west-2" and out[0]["model_id"] == "us.amazon.nova-lite-v1:0"


# --- the tool role and the deny-all --------------------------------------------------------------------------

def credentials(key: str) -> dict[str, Any]:
    return {"AccessKeyId": key, "SecretAccessKey": "dummy-secret", "SessionToken": "dummy-token", "Expiration": NOW}


def test_assume_sends_the_two_tags_and_the_session_name_and_keeps_the_credentials_out_of_the_record():
    sts, stub = stubbed("sts")
    role_arn = f"arn:aws:iam::{ACCOUNT}:role/w3-incident-get-pod-status"
    name = tool_role.session_name(tool_role.OBJECT_ID, TRACE)
    stub.add_response("assume_role", {"Credentials": credentials("ASIAEXAMPLERUNA00001"),
                                      "AssumedRoleUser": {"AssumedRoleId": "AROAEXAMPLE:" + name, "Arn": f"arn:aws:sts::{ACCOUNT}:assumed-role/w3-incident-get-pod-status/{name}"}},
                      {"RoleArn": role_arn, "RoleSessionName": name, "DurationSeconds": 900,
                       "Tags": [{"Key": "workflow", "Value": "w3-incident"}, {"Key": "trace_id", "Value": TRACE}]})
    with stub:
        out = tool_role.assume(sts, role_arn, TRACE)
    assert out["ok"] and out["session"] == name and out["tags"] == ["workflow", "trace_id"]
    kept = cloud_session.redact({k: v for k, v in out.items() if k != "credentials"})
    assert "ASIAEXAMPLERUNA00001" not in json.dumps(kept) and kept["returned_access_key_id"].startswith("asia-")


def test_refusals_report_each_shape_the_trust_policy_must_refuse():
    sts, stub = stubbed("sts")
    for _ in range(4):
        stub.add_client_error("assume_role", "AccessDenied", "not authorized to perform: sts:AssumeRole")
    with stub:
        out = tool_role.refusals(sts, f"arn:aws:iam::{ACCOUNT}:role/w3-incident-get-pod-status", TRACE)
    assert [r["refused"] for r in out] == [True] * 4 and all(r["code"] == "AccessDenied" for r in out)
    assert out[1]["case"].startswith("chapter 6's session name")


def test_the_deny_all_drill_times_the_first_refusal_and_the_later_sessions_first_success(monkeypatch):
    monkeypatch.setattr(tool_role.time, "sleep", lambda s: None)
    iam, iam_stub = stubbed("iam", "us-east-1")
    sts, sts_stub = stubbed("sts")
    ec2, ec2_stub = stubbed("ec2")
    role_name = "w3-incident-get-pod-status"
    role_arn = f"arn:aws:iam::{ACCOUNT}:role/{role_name}"
    role = {"Role": {"Path": "/", "RoleName": role_name, "RoleId": "AROAEXAMPLERESTART01", "Arn": role_arn,
                     "CreateDate": NOW, "Tags": [{"Key": "workflow", "Value": "w3-incident"}]}}
    # pull: get_role, put_role_policy; two reads pass, the third is denied
    iam_stub.add_response("get_role", role, {"RoleName": role_name})
    iam_stub.add_response("put_role_policy", {}, None)
    ec2_stub.add_response("describe_instances", {"Reservations": []}, {"MaxResults": 5})
    ec2_stub.add_response("describe_instances", {"Reservations": []}, {"MaxResults": 5})
    ec2_stub.add_client_error("describe_instances", "UnauthorizedOperation", "explicit deny", expected_params={"MaxResults": 5})
    # release: get_role, put_role_policy; the later session: one refusal, then success; the earlier one still refused
    iam_stub.add_response("get_role", role, {"RoleName": role_name})
    iam_stub.add_response("put_role_policy", {}, None)
    sts_stub.add_response("assume_role", {"Credentials": credentials("ASIAEXAMPLERUNB00002"),
                                          "AssumedRoleUser": {"AssumedRoleId": "AROAEXAMPLE:x", "Arn": f"arn:aws:sts::{ACCOUNT}:assumed-role/{role_name}/x"}}, None)
    ec2_stub.add_client_error("describe_instances", "UnauthorizedOperation", "explicit deny", expected_params={"MaxResults": 5})
    ec2_stub.add_response("describe_instances", {"Reservations": [{}]}, {"MaxResults": 5})
    ec2_stub.add_client_error("describe_instances", "UnauthorizedOperation", "explicit deny", expected_params={"MaxResults": 5})
    # purge: get_role, delete_role_policy; the later session works on
    iam_stub.add_response("get_role", role, {"RoleName": role_name})
    iam_stub.add_response("delete_role_policy", {}, {"RoleName": role_name, "PolicyName": "larkspur-kill-switch"})
    ec2_stub.add_response("describe_instances", {"Reservations": [{}]}, {"MaxResults": 5})
    session = FakeSession(iam=iam, sts=sts, ec2=ec2)
    with iam_stub, sts_stub, ec2_stub:
        out = tool_role.deny_all(session, iam, sts, role_name, role_arn, {"credentials": credentials("ASIAEXAMPLERUNA00001")}, every=0.0)
        for stub in (iam_stub, sts_stub, ec2_stub):
            stub.assert_no_pending_responses()
    assert out["calls_that_passed_after_pull"] == 2 and out["first_denied_code"] == "UnauthorizedOperation"
    assert out["first_denied_s"] is not None and out["first_denied_s"] >= out["pull_answered_s"]
    assert out["later_session_refusals_before_success"] == 1 and out["later_session_first_success_s"] is not None
    assert out["issued_before_release_after"]["ok"] is False
    assert out["purge"]["results"][0]["action"] == "deleted" and out["later_session_after_purge"]["ok"] is True
    assert "credentials" not in json.dumps(out)


def test_our_events_are_found_by_the_session_name_in_the_arn():
    name = tool_role.session_name(tool_role.OBJECT_ID, TRACE)
    mine = {"eventName": "DescribeInstances", "userIdentity": {"type": "AssumedRole",
            "arn": f"arn:aws:sts::{ACCOUNT}:assumed-role/w3-incident-get-pod-status/{name}"}}
    other = {"eventName": "DescribeInstances", "userIdentity": {"type": "IAMUser", "arn": f"arn:aws:iam::{ACCOUNT}:user/lab"}}
    assert tool_role.ours([mine, other], {name}) == [mine]


# --- CloudWatch and Langfuse on fixtures -------------------------------------------------------------------------

def test_the_trace_id_is_found_wherever_the_record_holds_it():
    message = {"traceId": TRACE, "spanId": "0011223344556677", "attributes": {"service.name": "harness"}}
    assert cloudwatch_spans.find_trace_id(message, {TRACE}) == (TRACE, "traceId")
    nested = {"resource": {"attributes": {"ids": [{"trace": TRACE}]}}}
    assert cloudwatch_spans.find_trace_id(nested, {TRACE}) == (TRACE, "resource.attributes.ids[0].trace")
    assert cloudwatch_spans.find_trace_id(message, {"0" * 32}) is None
    events = [{"timestamp_ms": 1, "ingestion_ms": 2, "message": message}, {"timestamp_ms": 1, "ingestion_ms": 2, "message": {"traceId": "0" * 32}}]
    by_trace, key = cloudwatch_spans.count_by_trace(events, {TRACE})
    assert len(by_trace[TRACE]) == 1 and key == "traceId"
    assert cloudwatch_spans.shape(message)["keys"] == ["attributes", "spanId", "traceId"]


def span(span_id: str, name: str, **attributes: Any) -> dict[str, Any]:
    return {"trace_id": TRACE, "span_id": span_id, "parent_span_id": "", "name": name, "attributes": attributes,
            "resource": {"service.name": "gateway"}, "scope_attributes": {}, "trace_state": "ot=th:0", "start_ns": 0, "end_ns": 1, "status": "UNSET"}


def test_langfuse_comparison_counts_the_same_span_ids_and_reads_the_cost():
    spans = {TRACE: [span("a" * 16, "invoke_agent harness"),
                     span("b" * 16, "chat larkspur-chat", **{"gen_ai.usage.cost": 0.000372, "gen_ai.usage.input_tokens": 74,
                                                              "gen_ai.usage.output_tokens": 10})]}
    observations = {TRACE: [{"id": "a" * 16, "type": "SPAN", "parentObservationId": None},
                            {"id": "b" * 16, "type": "GENERATION", "parentObservationId": "a" * 16, "model": "fake-primary",
                             "usageDetails": {"input": 74, "output": 10}, "costDetails": {"total": 0.000372}}]}
    out = langfuse_check.compare(spans, observations)
    assert out["traces"][0]["same_span_ids"] == 2 and out["traces_with_every_span"] == 1
    assert out["gateway_spans_with_cost"][0]["cost_equal"] and out["gateway_spans_with_cost"][0]["tokens_equal"]
    assert out["cost_read_from_gen_ai_usage_cost"] == 1 and out["tracestate_anywhere"] is False
    missing = langfuse_check.compare(spans, {})
    assert missing["traces"][0]["observations"] == 0 and missing["gateway_spans_with_cost"][0]["found"] is False


# --- Cost Explorer --------------------------------------------------------------------------------------------

def test_cost_explorers_rows_and_the_reconciliation_against_the_ledger():
    answer = {"ResultsByTime": [{"TimePeriod": {"Start": "2026-10-29", "End": "2026-10-30"}, "Groups": [
        {"Keys": ["CAN1-NovaLite-input-tokens"], "Metrics": {"UnblendedCost": {"Amount": "0.0031", "Unit": "USD"}, "UsageQuantity": {"Amount": "48", "Unit": "1K tokens"}}},
        {"Keys": ["CAN1-NovaLite-output-tokens"], "Metrics": {"UnblendedCost": {"Amount": "0.0013", "Unit": "USD"}, "UsageQuantity": {"Amount": "5", "Unit": "1K tokens"}}},
        {"Keys": ["USE2-TitanEmbed"], "Metrics": {"UnblendedCost": {"Amount": "0.01", "Unit": "USD"}, "UsageQuantity": {"Amount": "1", "Unit": "N/A"}}}]}]}
    rows = cost_explorer.rows(answer)
    assert len(rows) == 3 and rows[0]["usage"] == 48.0 and rows[0]["unit"] == "1K tokens"
    ledger = cost_explorer.ledger_nova_lite()
    assert ledger["days"]["2026-10-29"]["calls"] == 48  # W1's run on the Canadian profile
    assert ledger["price"]["id"] == "nova-lite-ca" and ledger["price"]["input_per_million"] == 0.064
    out = cost_explorer.reconcile(rows, ledger)
    day = next(r for r in out if r["day"] == "2026-10-29")
    assert day["bill_usage_types"] == ["CAN1-NovaLite-input-tokens", "CAN1-NovaLite-output-tokens"]
    assert day["ledger_calls"] == 48 and day["bill_cost_usd"] == 0.0044
    assert day["bill_input_tokens"] == 48_000  # the usage types are metered in thousands of tokens
    aligned = cost_explorer.align(rows, ledger, "2026-10-29", "2026-10-29")
    assert aligned["input_ratio_bill_over_ledger"] == round(48_000 / 81439, 3)
    assert aligned["bill_at_the_tables_price_usd"] == round(48_000 / 1e6 * 0.064 + 5_000 / 1e6 * 0.256, 6)
    assert "product attribute model = Nova Lite" in cost_explorer.FILTERS


# --- the run's Collector settings, the tunnel, the sweep -----------------------------------------------------

def test_the_live_runs_overlay_keeps_the_real_exporters_and_adds_the_sink():
    overlay = export_run.overlay(otlp_port=4318, metrics_port=8888, tap_url="http://127.0.0.1:1", sink_url="http://127.0.0.1:2")
    assert overlay["service"]["pipelines"]["traces/stores"]["exporters"] == ["file", "otlp_http/cloudwatch", "otlp_http/sink"]
    assert "otlp_http/cloudwatch" not in overlay["exporters"]  # config.yaml's endpoint and signer stay
    env = export_run.collector_environment(span_file=Path("spans.jsonl"), langfuse_endpoint="http://127.0.0.1:3000/api/public/otel",
                                           public_key="pk", secret_key="sk")
    assert env["LANGFUSE_PUBLIC_KEY"] == "pk" and env["LARKSPUR_TRACE_SHARE_PERCENT"] == "100"
    assert "AWS_ACCESS_KEY_ID" not in env and env["AWS_EC2_METADATA_DISABLED"] == "true"


def test_the_tunnel_command_names_the_instance_the_ports_and_the_region():
    t = tunnel.Tunnel("i-0123456789abcdef0", 3000, 3000, Path("."), endpoint_id="eice-0123456789abcdef0", max_duration=1800)
    assert t.args[:3] == ["aws", "ec2-instance-connect", "open-tunnel"]
    assert "--remote-port" in t.args and "--region" in t.args and "us-east-2" in t.args
    assert "--instance-connect-endpoint-id" in t.args and "1800" in t.args
    options = tunnel.ssh_options(Path("key"), 2222, Path("work"))
    assert "StrictHostKeyChecking=no" in options and "-p" in options and "IdentitiesOnly=yes" in options


def test_the_sweep_looks_for_the_terraforms_names_and_catches_a_refusal():
    tf = "".join(p.read_text(encoding="utf-8") for p in (LAB / "cloud" / "terraform").glob("*.tf"))
    assert f'"{leftovers.LOG_GROUPS[0]}"' in tf
    assert leftovers.ROLES[0] == "w3-incident-get-pod-status"
    assert f'purpose  = "{leftovers.PURPOSE}"' in tf and f'default     = "{leftovers.NAME}"' in tf
    assert leftovers.ask(lambda: 1 / 0).startswith("ZeroDivisionError")
    assert "<account>" in leftovers.ask(lambda: (_ for _ in ()).throw(RuntimeError(f"arn:aws:iam::{ACCOUNT}:role/x")))


def test_no_module_of_step_7_shares_a_name_with_another_folder_on_the_tests_path():
    mine = {p.stem for p in (LAB / "cloud").glob("*.py")}
    for folder in ("ledger", "collector", "budget", "capacity", "slo"):
        assert not mine & {p.stem for p in (LAB / folder).glob("*.py")}, folder
