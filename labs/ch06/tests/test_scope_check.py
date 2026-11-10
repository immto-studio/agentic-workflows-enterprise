"""The pipeline's scope check: growth needs a change record, narrowing doesn't.

Chapter 6, the other half of chapter 4's promise. Each test starts from the incident workflow's
AWS manifest and the catalog, changes one thing, and runs pipeline/scope_check.py as the pipeline
does, with the main branch's versions as the base.
"""

from __future__ import annotations

import copy
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

LAB = Path(__file__).resolve().parent.parent
SCRIPT = LAB / "pipeline" / "scope_check.py"
W3 = LAB / "manifests" / "w3-incident.yaml"
CH05_W3 = LAB.parent / "ch05" / "manifest" / "w3-incident.yaml"
CATALOG = LAB / "catalog" / "tools.yaml"

pytest.importorskip("jsonschema", reason="the check validates manifests with chapter 5's schema")


def load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def check(tmp: Path, *, manifest: dict[str, Any] | None = None, catalog: dict[str, Any] | None = None,
          base: Path | None = W3, record: str = "") -> subprocess.CompletedProcess[str]:
    head_manifest, head_catalog = tmp / "manifest.yaml", tmp / "catalog.yaml"
    head_manifest.write_text(yaml.safe_dump(manifest or load(W3)), encoding="utf-8")
    head_catalog.write_text(yaml.safe_dump(catalog or load(CATALOG)), encoding="utf-8")
    args = [sys.executable, str(SCRIPT), "--manifest", str(head_manifest), "--catalog", str(head_catalog),
            "--base-catalog", str(CATALOG), "--change-record", record]
    if base is not None:
        args += ["--base-manifest", str(base)]
    return subprocess.run(args, capture_output=True, text=True, timeout=60, env={"PYTHONUTF8": "1", "SYSTEMROOT": "C:\\Windows"})


def changed(change: Callable[[dict[str, Any]], None], source: Path = W3) -> dict[str, Any]:
    data = copy.deepcopy(load(source))
    change(data)
    return data


def test_the_aws_manifest_grows_chapter_5s_by_a_region_and_a_tool(tmp_path: Path) -> None:
    refused = check(tmp_path, base=CH05_W3)
    assert refused.returncode == 1
    assert refused.stdout.splitlines() == [
        "grown: regions added: ca-west-1",
        "grown: tool added: search_runbooks",
        "grown: search_runbooks: IAM bedrock:Retrieve on ${knowledge_base_arn}",
        "narrowed: restart_deployment: service only claims-api, billing-worker",
    ]
    assert "refused: 3 grown scope(s) for w3-incident, no change record" in refused.stderr
    approved = check(tmp_path, base=CH05_W3, record="CHG-20431")
    assert approved.returncode == 0 and "3 grown scope(s) for w3-incident, under CHG-20431" in approved.stdout


GROWTH = {
    "a write tool": (lambda m: m["tools"].update({"scale_deployment": {"args": ["service", "replicas"], "writes": True}}),
                     "tool added: scale_deployment (writes)"),
    "a read tool turned writer": (lambda m: m["tools"]["get_pod_status"].update({"writes": True}),
                                  "get_pod_status now writes"),
    "an argument": (lambda m: m["tools"]["get_recent_alerts"]["args"].append("severity"),
                    "get_recent_alerts arguments added: severity"),
    "a value in an allow list": (lambda m: m["tools"]["restart_deployment"]["allow"]["service"].append("quote-engine"),
                                 "restart_deployment: allowed service values added: quote-engine"),
    "the allow list removed": (lambda m: m["tools"]["restart_deployment"].pop("allow"),
                               "restart_deployment: allow list on service removed"),
    "a model alias": (lambda m: m["models"].append("larkspur-chat-us"), "model aliases added: larkspur-chat-us"),
    "a Region": (lambda m: m["regions"].append("us-east-2"), "regions added: us-east-2"),
    "a higher rung": (lambda m: m.update({"rung": 4}), "rung raised from 3 to 4"),
    "a never-list entry dropped": (lambda m: m["never"].remove("modify_iam"), "never-list entries dropped: modify_iam"),
    "prompts in spans": (lambda m: m.update({"trace_content": True}), "prompts and outputs now go into spans (trace_content)"),
    "a larger monthly budget": (lambda m: m["budget"].update({"per_month_usd": 900}),
                                "budget per_month_usd raised from 500 to 900"),
}


@pytest.mark.parametrize("name", GROWTH)
def test_growth_is_refused_without_a_change_record(tmp_path: Path, name: str) -> None:
    change, line = GROWTH[name]
    result = check(tmp_path, manifest=changed(change))
    assert result.returncode == 1, result.stdout
    assert f"grown: {line}" in result.stdout.splitlines()


def test_a_catalog_change_that_widens_a_listed_tool_is_growth(tmp_path: Path) -> None:
    catalog = load(CATALOG)
    catalog["tools"]["get_pod_status"]["aws"][0]["actions"].append("eks:ListNodegroups")
    catalog["tools"]["get_pod_status"]["eks_access"]["namespaces"].append("payments")
    catalog["never"]["modify_iam"] = []
    result = check(tmp_path, catalog=catalog)
    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        "grown: never-list modify_iam: deny dropped for iam:*",
        "grown: get_pod_status: IAM eks:ListNodegroups on ${cluster_arn}",
        "grown: get_pod_status: Kubernetes namespace payments",
    ]


def test_narrowing_and_unrelated_catalog_changes_pass_without_a_record(tmp_path: Path) -> None:
    def narrow(m: dict[str, Any]) -> None:
        m["tools"].pop("search_runbooks")
        m["regions"].remove("ca-west-1")
        m["never"].append("touch_payments")
        m["budget"]["per_run_usd"] = 1.0

    catalog = load(CATALOG)
    catalog["tools"]["export_audit_log"] = {"server": "k8s-mcp", "writes": False,
                                            "aws": [{"actions": ["s3:GetObject"], "resources": ["*"]}]}
    result = check(tmp_path, manifest=changed(narrow), catalog=catalog)
    assert result.returncode == 0, result.stderr
    assert "grown:" not in result.stdout
    assert "narrowed: tool removed: search_runbooks" in result.stdout.splitlines()
    assert "w3-incident reaches no further than before" in result.stdout


def test_a_new_workflow_is_all_growth(tmp_path: Path) -> None:
    result = check(tmp_path, base=None)
    assert result.returncode == 1 and result.stdout.splitlines()[0] == "grown: new workflow w3-incident"
    assert check(tmp_path, base=None, record="CHG-20432").returncode == 0


@pytest.mark.parametrize("record", ["", "  ", "CHG-12", "chg-20431", "approved by Tomasz", "CHG-20431; rm -rf"])
def test_only_a_change_record_number_counts(tmp_path: Path, record: str) -> None:
    assert check(tmp_path, base=CH05_W3, record=record).returncode == 1


def test_a_base_manifest_without_the_base_catalog_stops_the_pipeline(tmp_path: Path) -> None:
    """Otherwise the catalog is compared with itself, and a grant it adds passes unseen."""
    catalog = load(CATALOG)
    catalog["tools"]["get_pod_status"]["aws"][0]["actions"] = ["eks:*"]
    head_catalog = tmp_path / "catalog.yaml"
    head_catalog.write_text(yaml.safe_dump(catalog), encoding="utf-8")
    result = subprocess.run([sys.executable, str(SCRIPT), "--base-manifest", str(W3), "--manifest", str(W3),
                             "--catalog", str(head_catalog)], capture_output=True, text=True, timeout=60,
                            env={"PYTHONUTF8": "1", "SYSTEMROOT": "C:\\Windows"})
    assert result.returncode == 2 and "--base-catalog is required" in result.stderr


def test_an_invalid_manifest_or_catalog_stops_the_pipeline(tmp_path: Path) -> None:
    manifest = changed(lambda m: m.update({"data_class_max": "secret"}))
    assert check(tmp_path, manifest=manifest).returncode == 2
    catalog = load(CATALOG)
    catalog["tools"]["get_pod_status"]["server"] = "nowhere-mcp"
    assert check(tmp_path, catalog=catalog).returncode == 2
    other = changed(lambda m: m.update({"workflow": "w2-ops-assistant"}))
    assert check(tmp_path, manifest=other).returncode == 2  # a base for a different workflow
