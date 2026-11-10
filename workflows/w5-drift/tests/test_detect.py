"""W5's detectors (step 3): the drift comparison and the four waste detectors over the fakes, the Karpenter
exclusion, the one suppression, the attribution of the three drift cases, the keys stable across two nights,
the findings per fixture workspace, the templates and their validation with terraform when it is at hand, and
the planted texts at the structural layer."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

# conftest.py puts servers/ and detect/ on the path before the fakes and the detectors are imported.
import cloud_fake
import cost_fake
import policy_fake
import state_fake
from common import NIGHT, mask_value

import attribution
import drift
import fixture_night
import render
import validate
import waste
from findings import KINDS, MASK_PREFIX, Finding, Scope, sort_findings

IDS = cloud_fake.IDS
ROUTE_ID = f"{IDS['rtb_private_a']}_10.251.0.0/24"
# The expected findings of the fixture night, by workspace: (kind, type, id). The README's table says the same.
EXPECTED: dict[str, set[tuple[str, str, str]]] = {
    "network-live": {
        ("unmanaged", "aws_route", ROUTE_ID),
    },
    "claims-api-prod": {
        ("changed", "aws_instance", IDS["claims_instance"]),
        ("changed", "aws_security_group", IDS["sg_billing_worker"]),
        ("graviton_candidate", "aws_instance", IDS["claims_instance"]),
    },
    "sandbox-quill": {
        ("unmanaged", "aws_ebs_volume", IDS["orphan_volume"]),
        ("missing", "aws_ebs_volume", IDS["scratch_volume"]),
        ("untagged", "aws_instance", IDS["notebook_instance"]),
        ("untagged", "aws_ebs_volume", IDS["notebook_root_volume"]),
        ("untagged", "aws_ebs_volume", IDS["orphan_volume"]),
        ("untagged", "aws_ebs_snapshot", IDS["recent_snapshot"]),
        ("idle", "aws_instance", IDS["batch_instance"]),
        ("unattached_volume", "aws_ebs_volume", IDS["orphan_volume"]),
        ("unattached_volume", "aws_ebs_volume", IDS["archive_volume"]),
        ("old_snapshot", "aws_ebs_snapshot", IDS["old_snapshot"]),
        ("graviton_candidate", "aws_instance", IDS["notebook_instance"]),
    },
}
KARPENTER = {IDS[f"karpenter_node_{n}"] for n in (1, 2, 3)} | {IDS[f"karpenter_root_{n}"] for n in (1, 2, 3)}
PLANTED = {cloud_fake.PLANTED["tag"]: "quill-notebook", cloud_fake.PLANTED["user_agent"]: "aws-cli/2.27.0 Python/3.12.9",
           state_fake.PLANTED["output"]: "see the runbook", cost_fake.PLANTED["line_item"]: "ocr-addon monthly fee"}


@pytest.fixture(scope="module")
def nights() -> dict[str, list[Finding]]:
    return {workspace: fixture_night.findings_for(workspace) for workspace in fixture_night.PAIRS}


def one(findings: list[Finding], kind: str, resource_id: str) -> Finding:
    hits = [f for f in findings if f.kind == kind and f.resource_id == resource_id]
    assert len(hits) == 1, (kind, resource_id, [f.key for f in hits])
    return hits[0]


# --- the night's findings -------------------------------------------------------------------------------------

def test_the_fixture_night_finds_the_expected_set_per_workspace(nights):
    for workspace, found in nights.items():
        assert {(f.kind, f.resource_type, f.resource_id) for f in found} == EXPECTED[workspace], workspace
        assert len(found) == len(EXPECTED[workspace])
        assert found == sort_findings(found) and len({f.key for f in found}) == len(found)
        for f in found:
            assert f.workspace == workspace and f.account == fixture_night.PAIRS[workspace] and f.region == cloud_fake.REGION
            assert f.key == f"{workspace}:{f.address or f.resource_id}:{f.kind}" and f.kind in KINDS
            assert f.template in render.TEMPLATES and f.template == render.template_for(f)
            assert (f.estimated_monthly_saving is None) == (f.kind in ("unmanaged", "changed", "missing", "untagged"))
    assert [len(nights[w]) for w in ("network-live", "claims-api-prod", "sandbox-quill")] == [1, 3, 11]


def test_compare_finds_the_three_drift_kinds_and_nothing_else(nights):
    route = one(nights["network-live"], "unmanaged", ROUTE_ID)
    assert route.address is None and route.resource_type == "aws_route" and route.template == "revert"
    assert route.evidence["destination"] == "10.251.0.0/24" and route.evidence["target"] == IDS["tgw"]
    assert route.evidence["route_table_address"] == "aws_route_table.private_a" and route.evidence["origin"] == "CreateRoute"
    # The local route AWS made and the identical routes of private_b are not drift; the mq_bridge group's rule
    # description is not a mapped attribute; the private tables' tags match the renumbered cost centre.
    assert [f.kind for f in nights["network-live"]] == ["unmanaged"]
    typed = one(nights["claims-api-prod"], "changed", IDS["claims_instance"])
    assert typed.address == "aws_instance.api" and typed.template == "adopt"
    assert typed.evidence == {"attributes": {"instance_type": {"state": "t3.large", "live": "m5.large"}}}
    jenkins = one(nights["claims-api-prod"], "changed", IDS["sg_billing_worker"])
    assert jenkins.address == "aws_security_group.billing_worker" and jenkins.template == "revert"
    ingress = jenkins.evidence["attributes"]["ingress"]
    assert ingress["added"] == [["tcp", 8080, 8080, "0.0.0.0/0"]] and ingress["removed"] == []
    assert ingress["state"] == [["tcp", 443, 443, "10.44.0.0/16"]] and len(ingress["live"]) == 2
    assert list(ingress["descriptions"].values()) == ["temp: jenkins smoke test"]  # author text, as data
    assert "egress" not in jenkins.evidence["attributes"]  # the egress rule matches
    gone = one(nights["sandbox-quill"], "missing", IDS["scratch_volume"])
    assert gone.address == "aws_ebs_volume.scratch" and gone.template == "removed" and gone.evidence["state"]["size"] == 200
    # The data volume's attachment, size, and type match; the load balancer's scheme and type match.
    assert not [f for f in nights["claims-api-prod"] if f.resource_id in (IDS["claims_data_volume"], IDS["claims_alb"])]
    # A volume that is an instance's root device and a snapshot of a managed volume are managed through
    # their parent, not unmanaged.
    unmanaged = {f.resource_id for found in nights.values() for f in found if f.kind == "unmanaged"}
    assert unmanaged == {ROUTE_ID, IDS["orphan_volume"]}


def test_the_karpenter_nodes_are_excluded_by_their_manager_tag(nights):
    assert not [f for found in nights.values() for f in found if f.resource_id in KARPENTER]
    inputs = fixture_night.gather("claims-api-prod")
    without = drift.compare(inputs.state, inputs.inventory, inputs.tags, exclusions=())
    reported = {f.resource_id for f in without if f.kind == "unmanaged"}
    assert reported == KARPENTER  # without the exclusion, the six would be reported: the tag is what decides
    assert drift.is_excluded({"karpenter.sh/nodepool": "claims-general"}, drift.MANAGER_TAGS) == "karpenter.sh/nodepool"
    assert drift.is_excluded({"Name": "x"}, drift.MANAGER_TAGS) is None


def test_masked_state_values_compare_as_opaque_markers_and_never_unmask():
    assert drift.mask_live("m5.large") == mask_value("m5.large") and drift.mask_live({"a": 1}) == mask_value({"a": 1})
    scope = Scope("w", "a", "1", "r")
    state = {"workspace": "w", "state": {"values": {"outputs": {}, "root_module": {"resources": [
        {"address": "aws_instance.x", "mode": "managed", "type": "aws_instance", "name": "x",
         "values": {"id": "i-1", "instance_type": mask_value("m5.large"), "ami": "ami-1", "tags": {}}, "sensitive_values": {}}]}}}}
    inventory = {"instances": {"account": "a", "account_id": "1", "region": "r", "kind": "instances", "response": {"Reservations": [
        {"Instances": [{"InstanceId": "i-1", "InstanceType": "m5.large", "ImageId": "ami-1", "Tags": []}]}]}}}
    assert drift.compare(state, inventory) == []  # the live value's marker equals the state's: no drift
    inventory["instances"]["response"]["Reservations"][0]["Instances"][0]["InstanceType"] = "m5.xlarge"
    found = drift.compare(state, inventory)
    assert len(found) == 1 and found[0].kind == "changed"
    change = found[0].evidence["attributes"]["instance_type"]
    assert change["state"].startswith(MASK_PREFIX) and change["live"] == mask_value("m5.xlarge")
    assert "m5.xlarge" not in json.dumps(found[0].evidence) and "m5.large" not in json.dumps(found[0].evidence)
    assert drift.scope_of(state, inventory) == scope


# --- the attribution ------------------------------------------------------------------------------------------

def test_the_three_drift_cases_are_attributed_from_the_trail(nights):
    jenkins = one(nights["claims-api-prod"], "changed", IDS["sg_billing_worker"]).attribution
    assert jenkins["event_name"] == "AuthorizeSecurityGroupIngress" and jenkins["username"] == "jenkins-deploy-prod"
    assert jenkins["user_agent"] == "Jenkins/2.479.2 (job billing-worker-deploy-prod; build 4471)"
    assert jenkins["identity_type"] == "IAMUser" and jenkins["event_time"] == "2026-10-29T03:12:47Z"
    assert jenkins["lookup"] == {"AttributeKey": "ResourceName", "AttributeValue": IDS["sg_billing_worker"]}
    route = one(nights["network-live"], "unmanaged", ROUTE_ID).attribution
    assert route["event_name"] == "CreateRoute" and route["username"] == "rosa.delgado"  # a network engineer, in the console
    assert route["user_agent"] == "console.ec2.amazonaws.com" and route["lookup"]["AttributeValue"] == IDS["rtb_private_a"]
    typed = one(nights["claims-api-prod"], "changed", IDS["claims_instance"]).attribution
    assert typed["event_name"] == "ModifyInstanceAttribute" and typed["username"] == "sam.okafor"  # not the StartInstances after it
    assert typed["event_time"] == "2026-10-24T15:05:31Z"
    gone = one(nights["sandbox-quill"], "missing", IDS["scratch_volume"]).attribution
    assert gone["event_name"] == "DeleteVolume" and gone["username"] == "quill-svc-notebooks" and gone["user_agent"].startswith("aws-cli/")
    assert one(nights["sandbox-quill"], "idle", IDS["batch_instance"]).attribution is None  # no event explains quiet
    assert one(nights["sandbox-quill"], "untagged", IDS["notebook_root_volume"]).attribution is None  # nothing in ninety days


def test_the_lookup_falls_back_to_the_event_name_when_the_resource_is_not_indexed():
    calls: list[tuple[str, str]] = []

    def lookup(account, region, attribute_key, attribute_value, days):
        calls.append((attribute_key, attribute_value))
        page = cloud_fake.lookup_events(account, region, attribute_key, attribute_value, days)
        if attribute_key == "ResourceName":
            return {**page, "response": {"Events": []}}  # the trail did not index the resource
        return page

    typed = one(fixture_night.findings_for("claims-api-prod"), "changed", IDS["claims_instance"])
    attributed = attribution.attribute(replace(typed, attribution=None), lookup)
    assert attributed.attribution["event_name"] == "ModifyInstanceAttribute" and attributed.attribution["username"] == "sam.okafor"
    assert attributed.attribution["lookup"] == {"AttributeKey": "EventName", "AttributeValue": "ModifyInstanceAttribute"}
    assert calls == [("ResourceName", IDS["claims_instance"]), ("EventName", "ModifyInstanceAttribute")]
    # An event of the right name about another instance does not explain this one.
    other = replace(typed, resource_id="i-0123456789abcdef0", attribution=None)
    assert attribution.attribute(other, lookup).attribution is None
    assert attribution.explaining_events(typed) == ("ModifyInstanceAttribute",)
    assert attribution.lookup_ids(one(fixture_night.findings_for("network-live"), "unmanaged", ROUTE_ID)) == [IDS["rtb_private_a"]]


# --- the waste detectors -----------------------------------------------------------------------------------

def test_the_four_waste_detectors_with_their_figures(nights):
    sandbox = nights["sandbox-quill"]
    orphan = one(sandbox, "untagged", IDS["orphan_volume"])
    assert orphan.evidence["missing"] == policy_fake.TAGGING_STANDARD["required_tags"] and orphan.evidence["present"] == {}
    assert orphan.address is None and orphan.template == "note" and orphan.estimated_monthly_saving is None
    root = one(sandbox, "untagged", IDS["notebook_root_volume"])  # both missing tags excused (see the suppression test)
    assert root.evidence["missing"] == [] and root.evidence["bad"] == {} and set(root.evidence["excused"]) == {"cost_center", "data_classification"}
    assert root.suppressed_by == "RITM0045233"
    snapshot = one(sandbox, "untagged", IDS["recent_snapshot"])
    assert snapshot.evidence["missing"] == ["cost_center", "service", "data_classification"]
    assert not [f for f in nights["claims-api-prod"] + nights["network-live"] if f.kind == "untagged"]  # fully tagged, the ALB by GetResources
    idle = one(sandbox, "idle", IDS["batch_instance"])
    assert idle.address == "aws_instance.batch" and idle.evidence["window_days"] == waste.IDLE_WINDOW_DAYS == 7
    assert idle.evidence["average"] < waste.IDLE_AVERAGE_PCT and idle.evidence["maximum"] < waste.IDLE_MAXIMUM_PCT
    assert len(idle.evidence["datapoints"]) == 7 and idle.evidence["suggested_type"] == "t4g.small"
    assert idle.evidence["cost"] == {"period": "2026-10", "monthly": 25.0, "fraction": 0.5, "unit": "synthetic"}
    assert idle.estimated_monthly_saving == 12.5 and idle.template == "instance_type"
    assert not [f for f in nights["claims-api-prod"] if f.kind == "idle"]  # the API instance runs at thirty percent
    archive = one(sandbox, "unattached_volume", IDS["archive_volume"])
    assert archive.address == "aws_ebs_volume.archive" and archive.template == "remove_block" and archive.evidence["age_days"] == 73
    assert archive.estimated_monthly_saving == 96.0 and archive.evidence["cost"]["fraction"] == 1.0
    stray = one(sandbox, "unattached_volume", IDS["orphan_volume"])
    assert stray.evidence["age_days"] == 13 >= waste.UNATTACHED_MIN_DAYS and stray.estimated_monthly_saving == 20.2  # thirteen billed days
    old = one(sandbox, "old_snapshot", IDS["old_snapshot"])
    assert old.evidence["age_days"] == 145 > waste.SNAPSHOT_MAX_AGE_DAYS and old.estimated_monthly_saving == 50.0
    assert old.evidence["volume_id"] == IDS["archive_volume"] and old.template == "note"
    assert not [f for found in nights.values() for f in found if f.kind == "old_snapshot" and f.resource_id != IDS["old_snapshot"]]
    notebook = one(sandbox, "graviton_candidate", IDS["notebook_instance"])
    assert notebook.evidence["suggested_type"] == "m7g.xlarge" and notebook.evidence["code_instance_type"] == "m5.xlarge"
    assert notebook.estimated_monthly_saving == round(142.80 * waste.GRAVITON_SAVING_FRACTION, 2) == 28.56
    api = one(nights["claims-api-prod"], "graviton_candidate", IDS["claims_instance"])
    assert api.evidence["suggested_type"] == "m7g.large" and api.evidence["code_instance_type"] == "t3.large"
    assert api.estimated_monthly_saving == round((61.30 + 24.60) * 0.2, 2)  # both of the month's rows
    assert not [f for f in sandbox if f.kind == "graviton_candidate" and f.resource_id == IDS["batch_instance"]]  # t4g is Graviton
    costs = waste.cost_index(cost_fake.read_cost_export("lm-sandbox", "2026-10"))
    assert costs.period == "2026-10" and costs.of("i-0123456789abcdef0") is None and costs.of(IDS["batch_instance"]) == 25.0


def test_an_exception_excuses_a_tag_and_only_a_fully_excused_finding_is_suppressed(nights):
    suppressed = [f for found in nights.values() for f in found if f.suppressed_by]
    assert len(suppressed) == 1
    volume = suppressed[0]  # the notebook host's root volume: both missing tags excused, nothing remains
    assert volume.kind == "untagged" and volume.resource_id == IDS["notebook_root_volume"] and volume.suppressed_by == "RITM0045233"
    assert volume.evidence["excused"] == {"cost_center": "RITM0045233", "data_classification": "RITM0045234"}
    assert volume.evidence["missing"] == [] and volume.evidence["bad"] == {}
    notebook = one(nights["sandbox-quill"], "untagged", IDS["notebook_instance"])  # partly excused: raised for what remains
    assert notebook.suppressed_by is None
    assert notebook.evidence["excused"] == {"cost_center": "RITM0045021"} and notebook.evidence["missing"] == ["data_classification"]
    assert notebook.key == "sandbox-quill:aws_instance.notebook:untagged"  # the key does not change
    assert sum(len(found) for found in nights.values()) == 15
    # The expired exception (the archive volume) and the pending one (the orphan) excuse nothing.
    orphan = one(nights["sandbox-quill"], "untagged", IDS["orphan_volume"])
    assert orphan.suppressed_by is None and "excused" not in orphan.evidence
    # From the detectors' own output, with all five records (three approved, one expired, one pending): the approved ones act.
    inputs = fixture_night.gather("sandbox-quill")
    raw = waste.detect_waste(drift.scope_of(inputs.state, inputs.inventory), inputs.inventory, inputs.tags, inputs.standard,
                             inputs.cpu, inputs.export, NIGHT, waste.managed_by_id(inputs.state))
    assert not [f for f in raw if f.suppressed_by or "excused" in f.evidence]
    assert one(raw, "untagged", IDS["notebook_instance"]).evidence["missing"] == ["cost_center", "data_classification"]
    assert one(raw, "untagged", IDS["notebook_root_volume"]).evidence["missing"] == ["cost_center", "data_classification"]
    everything = policy_fake.list_policy_exceptions("all")
    assert everything["count"] == 5
    again = waste.suppress(raw, everything, NIGHT)
    assert [f.suppressed_by for f in again if f.suppressed_by] == ["RITM0045233"]
    assert one(again, "untagged", IDS["notebook_instance"]) == notebook and one(again, "untagged", IDS["notebook_root_volume"]) == volume
    # Past the exceptions' expiry, nothing is excused or suppressed.
    later = waste.suppress(raw, everything, NIGHT.replace(year=2027, month=1, day=1))
    assert not [f for f in later if f.suppressed_by] and later == raw


def test_keys_are_stable_across_two_nights_and_two_runs(nights):
    for workspace, found in nights.items():
        tomorrow = fixture_night.findings_for(workspace, NIGHT + timedelta(days=1))
        assert [f.key for f in tomorrow] == [f.key for f in found], workspace
        assert fixture_night.findings_for(workspace) == found  # the same inputs, the same findings


# --- the templates -------------------------------------------------------------------------------------------

def test_the_templates_render_the_documented_hcl(nights):
    rendered = {f.key: render.render(f) for found in nights.values() for f in found}
    imported = rendered[f"sandbox-quill:{IDS['orphan_volume']}:unmanaged"]
    assert imported.template == "import" and imported.edits == ()
    assert f"import {{\n  to = aws_ebs_volume.vol_0d2b2c3d4e5f60402\n  id = \"{IDS['orphan_volume']}\"\n}}" in imported.blocks
    assert 'resource "aws_ebs_volume" "vol_0d2b2c3d4e5f60402" {' in imported.blocks and "size              = 500" in imported.blocks
    assert all(line.startswith("+") for line in imported.fragment.split("\n"))
    removed = rendered["sandbox-quill:aws_ebs_volume.scratch:missing"]
    assert "removed {\n  from = aws_ebs_volume.scratch\n\n  lifecycle {\n    destroy = false\n  }\n}" in removed.blocks
    assert removed.edits == (render.Edit("remove", "aws_ebs_volume.scratch"),) and '-resource "aws_ebs_volume" "scratch" {' in removed.fragment
    revert = rendered["claims-api-prod:aws_security_group.billing_worker:changed"]
    assert revert.template == "revert" and revert.blocks == "" and revert.edits[0].op == "comment"
    added = [line for line in revert.fragment.split("\n") if line.startswith("+")]
    assert added and all(line.startswith("+#") for line in added)  # a comment: the code is kept, the plan reverts
    assert 'tcp 8080-8080 from 0.0.0.0/0 ("temp: jenkins smoke test")' in revert.fragment and "Kept:" in revert.fragment
    assert ' resource "aws_security_group" "billing_worker" {' in revert.fragment
    route = rendered[f"network-live:{ROUTE_ID}:unmanaged"]
    assert route.template == "revert" and route.edits[0].address == "aws_route_table.private_a"
    assert "#   route {\n+#     cidr_block         = \"10.251.0.0/24\"\n+#     transit_gateway_id = \"tgw-0a1b2c3d4e5f60030\"\n+#   }" in route.fragment
    adopt = rendered["claims-api-prod:aws_instance.api:changed"]
    assert adopt.fragment == ' resource "aws_instance" "api" {\n-  instance_type = "t3.large"\n+  instance_type = "m5.large"\n }'
    assert adopt.edits == (render.Edit("set", "aws_instance.api", "instance_type", '"m5.large"'),)
    tags = rendered["sandbox-quill:aws_instance.notebook:untagged"]
    assert tags.fragment == (' resource "aws_instance" "notebook" {\n   tags = {\n'
                             '+    data_classification = "TODO: set by quill-data"\n   }\n }')  # cost_center is excused
    assert tags.edits == (render.Edit("tags", "aws_instance.notebook", "tags", {"data_classification": "TODO: set by quill-data"}),)
    graviton = rendered["sandbox-quill:aws_instance.notebook:graviton_candidate"]
    assert graviton.fragment.split("\n")[1:3] == ['-  instance_type = "m5.xlarge"', '+  instance_type = "m7g.xlarge"']
    idle = rendered["sandbox-quill:aws_instance.batch:idle"]
    assert idle.edits == (render.Edit("set", "aws_instance.batch", "instance_type", '"t4g.small"'),)
    assert rendered["sandbox-quill:aws_ebs_volume.archive:unattached_volume"].edits == (render.Edit("remove", "aws_ebs_volume.archive"),)
    note = rendered[f"sandbox-quill:{IDS['orphan_volume']}:unattached_volume"]
    assert note.template == "note" and note.edits == () and note.blocks.startswith("# W5 finding ")
    assert "W5 proposes no code for it and changes nothing itself." in note.blocks
    # Every rendering is comments or HCL from the finding: no fragment carries an `apply`.
    assert not any("terraform apply" in r.fragment for r in rendered.values())


def test_hcl_strings_and_keys_are_quoted_so_text_cannot_escape():
    assert render.quote('a"b\\c\nd${x}%{y}') == '"a\\"b\\\\c\\nd$${x}%%{y}"'
    assert render.hcl({"karpenter.sh/nodepool": "p", "env": "prod"}) == '{\n  "karpenter.sh/nodepool" = "p"\n  env                     = "prod"\n}'
    assert render.hcl(["a", 1, True, None]) == '["a", 1, true, null]' and render.hcl({}) == "{}" and render.hcl([]) == "[]"
    assert render.hcl_key("owner_team") == "owner_team" and render.hcl_key("aws:backup") == '"aws:backup"'
    lb = Finding(key="w:x:unmanaged", kind="unmanaged", workspace="w", account="a", region="r", resource_type="aws_lb",
                 address=None, resource_id="arn:aws:elasticloadbalancing:r:1:loadbalancer/app/x/0", evidence={"name": "claims-api"})
    assert render.import_address(lb) == "aws_lb.claims_api"
    assert render.import_address(replace(lb, resource_type="aws_instance", resource_id="i-0abc")) == "aws_instance.i_0abc"
    rule = Finding(key="w:aws_security_group.x:changed", kind="changed", workspace="w", account="a", region="r",
                   resource_type="aws_security_group", address="aws_security_group.x", resource_id="sg-1",
                   evidence={"attributes": {"ingress": {"state": [], "live": [["tcp", 22, 22, "0.0.0.0/0"]],
                                                        "added": [["tcp", 22, 22, "0.0.0.0/0"]], "removed": [],
                                                        "descriptions": {json.dumps(["tcp", 22, 22, "0.0.0.0/0"]): "x\n# not a comment"}}}})
    # A description with a line break fails what the field allows (fields.text_fails), so it stays out of the comment
    # altogether since the follow-up to chapter 15's red-team; one on one line is quoted inside it, where it closes nothing.
    held = render.render(rule)
    assert "not a comment" not in held.fragment and "held out of the diff" in held.fragment
    assert [(h.field, h.value) for h in held.held] == [("description", "x\n# not a comment")]
    rule.evidence["attributes"]["ingress"]["descriptions"] = {json.dumps(["tcp", 22, 22, "0.0.0.0/0"]): "x # still a comment"}
    fragment = render.render(rule).fragment
    assert 'from 0.0.0.0/0 ("x # still a comment")' in fragment and "\n+# still" not in fragment and "\n# still" not in fragment


def test_apply_writes_the_renderings_into_the_fixture_module(nights):
    files = validate.apply(validate.module_files("sandbox-quill"), [render.render(f) for f in nights["sandbox-quill"]])
    main = files["main.tf"]
    assert 'resource "aws_ebs_volume" "scratch"' not in main and 'resource "aws_ebs_volume" "archive"' not in main
    assert '  instance_type          = "t4g.small"' in main and '  instance_type          = "m7g.xlarge"' in main
    assert ('  tags = {\n    owner_team          = "quill-data"\n    env                 = "sandbox"\n'
            '    service             = "quill-notebooks"\n    data_classification = "TODO: set by quill-data"\n  }') in main
    new = files[validate.NEW_FILE]
    assert "import {" in new and "removed {" in new and new.count("# W5 finding ") == 5  # the five notes
    assert "no model wrote a line" in new
    claims = validate.apply(validate.module_files("claims-api-prod"), [render.render(f) for f in nights["claims-api-prod"]])
    assert "# Kept: the code below is not changed" in claims["main.tf"]
    assert claims["main.tf"].index("# W5 drift claims-api-prod:aws_security_group.billing_worker:changed") \
        < claims["main.tf"].index('resource "aws_security_group" "billing_worker" {')
    assert validate.NEW_FILE not in claims  # edits and comments only
    # A tags map that is not there is added; a module resource is found in its module's file.
    text = 'resource "aws_thing" "a" {\n  name = "x"\n}\n'
    edited = validate.apply({"main.tf": text, "modules/m/main.tf": text},
                            [render.Rendered("tags", "", "", (render.Edit("tags", "module.m.aws_thing.a", "tags", {"env": "lab"}),))])
    assert edited["main.tf"] == text and edited["modules/m/main.tf"] == 'resource "aws_thing" "a" {\n  name = "x"\n\n  tags = {\n    env = "lab"\n  }\n}\n'
    with pytest.raises(ValueError):
        validate.apply({"main.tf": text}, [render.Rendered("adopt", "", "", (render.Edit("set", "aws_thing.b", "name", '"y"'),))])


PLUGIN_DIR = Path(os.environ["TF_PLUGIN_CACHE_DIR"]) if os.environ.get("TF_PLUGIN_CACHE_DIR") else None
needs_terraform = pytest.mark.skipif(shutil.which("terraform") is None or PLUGIN_DIR is None or not PLUGIN_DIR.exists(),
                                     reason="needs terraform and TF_PLUGIN_CACHE_DIR with hashicorp/aws 6.71.0")


@needs_terraform
@pytest.mark.parametrize("workspace", validate.WORKSPACES)
def test_the_templates_validate_with_terraform(nights, workspace, tmp_path):
    result = validate.validate_workspace(workspace, nights[workspace], PLUGIN_DIR, tmp_path)
    assert result.ok, {name: output for name, (code, output) in result.steps.items() if code != 0}
    assert set(result.steps) == {"init", "validate", "fmt"} and "Success!" in result.steps["validate"][1]
    assert not (tmp_path / workspace / "plan.out").exists() and not (tmp_path / workspace / "terraform.tfstate").exists()


# --- everything read is untrusted, at the structural layer (W5-D12) ------------------------------------------

def test_the_planted_texts_change_no_key_kind_evidence_saving_suppression_or_template():
    for workspace in fixture_night.PAIRS:
        planted = fixture_night.gather(workspace)
        neutral = fixture_night.with_strings_replaced(planted, PLANTED)
        assert json.dumps(neutral.inventory) != json.dumps(planted.inventory) or workspace != "sandbox-quill"
        with_plants = fixture_night.findings_from(planted)
        without = fixture_night.findings_from(neutral)
        strip = [replace(f, attribution=None if f.attribution is None else {**f.attribution, "user_agent": None}) for f in with_plants]
        bare = [replace(f, attribution=None if f.attribution is None else {**f.attribution, "user_agent": None}) for f in without]
        assert strip == bare, workspace  # the same keys, kinds, evidence, savings, suppressions, templates
        assert [render.render(f) for f in with_plants] == [render.render(f) for f in without], workspace
        # The user agent is the one difference, recorded as data.
        agents = {f.key: f.attribution["user_agent"] for f in with_plants if f.attribution}
        others = {f.key: f.attribution["user_agent"] for f in without if f.attribution}
        differing = {k for k in agents if agents[k] != others[k]}
        if workspace == "sandbox-quill":
            assert agents[f"sandbox-quill:{IDS['orphan_volume']}:unmanaged"] == cloud_fake.PLANTED["user_agent"]
            assert others[f"sandbox-quill:{IDS['orphan_volume']}:unmanaged"] == PLANTED[cloud_fake.PLANTED["user_agent"]]
            assert differing == {k for k in agents if IDS["orphan_volume"] in k}
        else:
            assert not differing
        # No planted text is in any key, evidence, saving, or rendering.
        text = json.dumps([{**f.__dict__, "attribution": None} for f in with_plants]) + "".join(r.fragment + r.blocks for r in map(render.render, with_plants))
        for plant in PLANTED:
            assert plant not in text, (workspace, plant[:40])
