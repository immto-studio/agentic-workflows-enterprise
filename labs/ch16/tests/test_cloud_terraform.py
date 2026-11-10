"""Step 7's Terraform and the Langfuse files, read as text: the budget first, the tags, us-east-2 alone, no port open
to the internet, the tool role's trust policy in the amended O-D2's shape, text delivery off to start, the pinned
Compose file, and the markers the user data leaves. `terraform validate` runs when the folder has been initialized.
"""

from __future__ import annotations

import fnmatch
import hashlib
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import tool_role

LAB = Path(__file__).resolve().parents[1]
TF = LAB / "cloud" / "terraform"
LANGFUSE = LAB / "cloud" / "langfuse"
COMPOSE_SHA256 = "0f34f0fa6c039b2ba1951d69eba073ed5d75c8a908aa1ca8ef822e83507cec5f"  # v4.74.0's file, saved at step 1


def text(name: str) -> str:
    return (TF / name).read_text(encoding="utf-8")


def blocks(source: str, kind: str = "resource") -> dict[str, str]:
    """Each top-level `resource "type" "name" {...}` block's body, by type.name."""
    out: dict[str, str] = {}
    pattern = re.compile(rf'^{kind} "([^"]+)" "([^"]+)" \{{$(.*?)^\}}$', re.M | re.S)
    for match in pattern.finditer(source):
        out[f"{match.group(1)}.{match.group(2)}"] = match.group(3)
    return out


def all_resources() -> dict[str, str]:
    out: dict[str, str] = {}
    for path in TF.glob("*.tf"):
        out |= blocks(path.read_text(encoding="utf-8"))
    return out


def test_the_provider_is_pinned_and_tags_every_resource_as_the_sessions():
    versions = text("versions.tf")
    assert 'version = "6.71.0"' in versions and 'source  = "hashicorp/aws"' in versions
    assert 'purpose  = "ch16-cloud-session"' in versions and 'data     = "synthetic"' in versions


def test_the_region_can_only_be_us_east_2():
    variables = text("variables.tf")
    assert 'condition     = var.region == "us-east-2"' in variables
    assert 'default     = "us-east-2"' in variables


def test_the_budget_comes_first_with_an_sns_subscriber_and_no_address():
    budget = blocks(text("budget.tf"))["aws_budgets_budget.session"]
    assert 'budget_type  = "COST"' in budget and 'time_unit    = "MONTHLY"' in budget
    assert "subscriber_sns_topic_arns = [aws_sns_topic.budget.arn]" in budget
    assert "subscriber_email_addresses" not in text("budget.tf")
    assert "@" not in text("budget.tf")
    assert "budgets.amazonaws.com" in text("budget.tf")
    resources = all_resources()
    roots = ["aws_vpc.lab", "aws_instance.langfuse", "aws_iam_role.tool", "aws_cloudwatch_log_group.invocations",
             "aws_iam_role.invocation_logging"]
    for name in roots:
        assert "aws_budgets_budget.session" in resources[name], f"{name} doesn't wait for the budget"


def test_no_security_group_rule_opens_a_port_to_the_internet():
    network = text("network.tf")
    ingress = {k: v for k, v in blocks(network).items() if k.startswith("aws_vpc_security_group_ingress_rule.")}
    assert len(ingress) == 2
    for name, body in ingress.items():
        assert "referenced_security_group_id = aws_security_group.endpoint.id" in body, name
        assert "cidr_ipv4" not in body, name
    assert network.count("0.0.0.0/0") == 2  # the default route and the VM's outbound rule
    assert 'ip_protocol                  = "-1"' not in network.split('resource "aws_vpc_security_group_egress_rule" "vm_out"')[0]
    endpoint = blocks(network)["aws_ec2_instance_connect_endpoint.lab"]
    assert "preserve_client_ip = false" in endpoint


def test_the_vm_is_ubuntu_from_canonicals_parameter_with_imdsv2_and_a_disk_that_goes_with_it():
    vm = text("vm.tf")
    assert '/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id' in vm
    instance = blocks(vm)["aws_instance.langfuse"]
    assert 'http_tokens   = "required"' in instance
    assert "delete_on_termination = true" in instance and 'volume_type           = "gp3"' in instance
    assert "instance_type               = var.instance_type" in instance
    assert 'default     = "t3.xlarge"' in text("variables.tf")


def test_the_tool_roles_trust_policy_requires_the_run():
    iam = text("iam.tf")
    assert 'variable = "aws:RequestTag/trace_id"' in iam and "range(32)" in iam
    assert 'variable = "sts:RoleSessionName"' in iam and "range(16)" in iam
    assert 'values   = ["workflow", "trace_id"]' in iam and 'test     = "ForAllValues:StringEquals"' in iam
    assert 'variable = "aws:RequestTag/workflow"' in iam
    assert 'substr("${var.workflow}-${replace(var.tool, "_", "-")}", 0, 64)' in iam  # chapter 6's name
    assert 'actions   = ["ec2:DescribeInstances"]' in iam
    # the session name the script makes fits the policy's pattern; chapter 6's alone doesn't
    trace_id = "7d3e0c5f9a1b4c2e8f6a0b1c2d3e4f5a"
    assert fnmatch.fnmatchcase(tool_role.session_name(tool_role.OBJECT_ID, trace_id), "*." + "?" * 16)
    assert not fnmatch.fnmatchcase(tool_role.OBJECT_ID, "*." + "?" * 16)
    assert fnmatch.fnmatchcase(trace_id, "?" * 32) and not fnmatch.fnmatchcase(trace_id[:31], "?" * 32)
    assert len(tool_role.session_name(tool_role.OBJECT_ID, trace_id)) <= 64


def test_invocation_logging_starts_with_text_delivery_off_in_us_east_2():
    logging = text("logging.tf")
    assert "text_data_delivery_enabled      = false" in logging
    assert "retention_in_days = 1" in logging
    assert '"/aws/bedrock/model-invocations-ch16"' in logging


def test_the_compose_file_is_the_pinned_release_and_the_override_pins_its_floating_images():
    compose = LANGFUSE / "docker-compose.yml"
    # The pin is the release file's bytes with LF endings (.gitattributes asks for LF); a Windows checkout may hold CRLF.
    assert hashlib.sha256(compose.read_bytes().replace(b"\r\n", b"\n")).hexdigest() == COMPOSE_SHA256
    body = compose.read_text(encoding="utf-8")
    for image in ("docker.langfuse.com/langfuse/langfuse:4", "docker.langfuse.com/langfuse/langfuse-worker:4",
                  "docker.io/clickhouse/clickhouse-server:26.3.62.3", "cgr.dev/chainguard/minio", "docker.io/redis:7"):
        assert image in body, image  # the images fact sheet 8.5 lists
    override = (LANGFUSE / "docker-compose.override.yml.tftpl").read_text(encoding="utf-8")
    assert "langfuse-worker:${version}" in override and "langfuse/langfuse:${version}" in override
    assert 'default     = "4.74.0"' in text("variables.tf")


def test_the_user_data_writes_the_files_and_leaves_the_markers_the_session_reads():
    script = (TF / "templates" / "user-data.sh.tftpl").read_text(encoding="utf-8")
    for needle in ("docker-compose.yml", "docker-compose.override.yml", ".env", "apt-get install -y -q docker.io docker-compose-v2",
                   "health.json", "digests.txt", "versions.txt", "pin.txt", "> ready"):
        assert needle in script, needle
    assert "%{" not in script  # nothing Terraform's template engine would misread
    env = (TF / "templates" / "langfuse.env.tftpl").read_text(encoding="utf-8")
    for name in ("LANGFUSE_INIT_PROJECT_PUBLIC_KEY", "LANGFUSE_INIT_PROJECT_SECRET_KEY", "ENCRYPTION_KEY", "TELEMETRY_ENABLED=false"):
        assert name in env, name
    import cloud_session

    assert cloud_session._EMAIL.search(env) is None  # the address comes from a variable, never from the repository


def test_the_outputs_carry_no_arn():
    assert ".arn" not in text("outputs.tf")


@pytest.mark.skipif(not shutil.which("terraform") or not (TF / ".terraform").exists(),
                    reason="terraform and an initialized folder are needed")
def test_terraform_validates_and_is_formatted():
    run = subprocess.run(["terraform", "validate", "-no-color"], cwd=TF, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0 and "Success" in run.stdout, run.stdout + run.stderr
    fmt = subprocess.run(["terraform", "fmt", "-check", "-recursive"], cwd=TF, capture_output=True, text=True, timeout=60)
    assert fmt.returncode == 0, fmt.stdout
