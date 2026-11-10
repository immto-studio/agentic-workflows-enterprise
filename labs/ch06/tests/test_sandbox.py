"""The sandbox's stand-ins stay stand-ins: no way to the internet, nothing that outlives a destroy.

They read sandbox/main.tf and sandbox.py; nothing here calls AWS.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import hcl2

LAB = Path(__file__).resolve().parent.parent
SANDBOX = LAB / "sandbox"


def clean(value):
    if isinstance(value, dict):
        return {clean(k): clean(v) for k, v in value.items() if k not in ("__is_block__", "__comments__")}
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, str) and len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    return value


with (SANDBOX / "main.tf").open(encoding="utf-8") as handle:
    PARSED = clean(hcl2.load(handle))
RESOURCES: dict[str, dict] = {}
for block in PARSED.get("resource", []):
    for kind, named in block.items():
        RESOURCES.setdefault(kind, {}).update(named)


def test_nothing_reaches_the_internet() -> None:
    assert not {"aws_internet_gateway", "aws_nat_gateway", "aws_eip", "aws_egress_only_internet_gateway"} & set(RESOURCES)
    (table,) = RESOURCES["aws_route_table"].values()
    assert "route" not in table  # the local route only


def test_everything_goes_with_a_destroy() -> None:
    assert RESOURCES["aws_secretsmanager_secret"]["gateway_key"]["recovery_window_in_days"] == 0
    assert RESOURCES["aws_ecr_repository"]["harness"]["force_delete"] is True
    assert all(bucket["force_destroy"] is True for bucket in RESOURCES["aws_s3_bucket"].values())


def test_the_secret_and_the_root_are_stand_ins() -> None:
    version = RESOURCES["aws_secretsmanager_secret_version"]["gateway_key"]
    assert "not-a-key" in json.dumps(version["secret_string"])
    root = RESOURCES["tls_self_signed_cert"]["root"]
    assert root["is_ca_certificate"] is True and root["validity_period_hours"] <= 48


def test_the_image_builds_for_arm64() -> None:
    project = RESOURCES["aws_codebuild_project"]["harness"]
    environment = project["environment"][0]
    assert environment["type"] == "ARM_CONTAINER" and environment["privileged_mode"] is True
    assert "--platform linux/arm64" in (SANDBOX / "buildspec.yml").read_text(encoding="utf-8")


def _sandbox_module():
    spec = importlib.util.spec_from_file_location("ch06_sandbox", SANDBOX / "sandbox.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["ch06_sandbox"] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_the_build_context_holds_what_the_dockerfile_copies() -> None:
    files = {path.as_posix() for path in _sandbox_module().context_files()}
    assert "ch06/image/Dockerfile" in files and "ch06/image/private-ca.pem" in files
    assert "ch05/requirements.txt" in files and "ch07/image/entrypoint.py" in files
    assert all(not name.startswith("/") for name in files)  # sources, never the image's paths
