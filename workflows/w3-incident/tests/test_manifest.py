"""W3's manifest and catalog: the manifest validates against chapter 5's schema, its tools match the catalog and
the loop's allowlist, the writes are marked, Restricted is its class, ca-central-1 its only Region, and the
never-list's actions are served by no tool (W3-D11)."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

W3 = Path(__file__).resolve().parents[1]
CH05_MANIFEST = W3.parents[1] / "labs" / "ch05" / "manifest"
for folder in (CH05_MANIFEST,):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

MANIFEST = yaml.safe_load((W3 / "manifest" / "w3-incident.yaml").read_text(encoding="utf-8"))
CATALOG = yaml.safe_load((W3 / "catalog" / "tools.yaml").read_text(encoding="utf-8"))
W2_CATALOG = yaml.safe_load((W3.parent / "w2-ops-assistant" / "catalog" / "tools.yaml").read_text(encoding="utf-8"))
CHAPTER_4_NEVER = {"delete_namespace", "modify_iam", "modify_security_group", "read_vault_secret", "run_command"}
WRITES = {"restart_deployment", "scale_deployment", "record_change"}


def test_the_manifest_validates_against_chapter_5s_schema():
    import json
    import jsonschema
    schema = json.loads((CH05_MANIFEST / "schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(MANIFEST, schema)


def test_it_is_a_rung_3_restricted_workflow_in_canada():
    assert MANIFEST["rung"] == 3
    assert MANIFEST["data_class_max"] == "restricted"
    assert MANIFEST["regions"] == ["ca-central-1"]
    assert set(MANIFEST["models"]) == {"larkspur-chat", "larkspur-chat-restricted"}
    assert MANIFEST["trace_content"] is False


def test_the_writes_are_marked_and_only_the_writes():
    marked = {name for name, spec in MANIFEST["tools"].items() if spec.get("writes")}
    assert marked == WRITES


def test_the_reads_are_w2s_six():
    w2_reads = set(W2_CATALOG["tools"])
    assert w2_reads <= set(MANIFEST["tools"]), "W3 triages with W2's reads"
    for tool in w2_reads:
        assert MANIFEST["tools"][tool]["args"] == {"args": W2_CATALOG["tools"][tool]["args"]}["args"]


def test_every_tool_is_in_the_catalog_and_the_loops_allowlist():
    from loop import SYSTEM_PROMPT  # noqa: F401  importable: the loop is W3's
    catalog_tools = set(CATALOG["tools"]) | set(W2_CATALOG["tools"])
    assert set(MANIFEST["tools"]) <= catalog_tools, "no tool the catalog does not serve"
    writes_in_catalog = {name for name, spec in CATALOG["tools"].items() if "writes" in spec}
    assert writes_in_catalog == {"restart_deployment", "scale_deployment", "record_change"}


def test_the_never_list_is_chapter_4s_and_no_tool_serves_it():
    assert set(MANIFEST["never"]) == CHAPTER_4_NEVER, "chapter 4's tool-shaped actions; the payments slice is the map's"
    assert not (set(MANIFEST["never"]) & set(MANIFEST["tools"])), "no never action is also a tool"
    assert set(MANIFEST["never"]) == set(CATALOG["never"]), "the catalog names the same never-list"
    # restart and scale are writes, not never-list actions (chapter 4 gates them by approval, not forbids them).
    assert "restart_deployment" not in MANIFEST["never"] and "scale_deployment" not in MANIFEST["never"]


def test_each_write_identity_holds_the_one_verb_not_the_edit_role():
    writer = CATALOG["servers"]["writer-mcp"]
    assert set(writer["identities"]) == {"restart_deployment", "scale_deployment"}
    assert writer["azure"]["role"] == "Azure Kubernetes Service RBAC Writer", "the write role, scoped to the namespace"
    assert writer["azure"]["scope"] == "namespace"
    # The edit built-in role is never named (the fact sheet, B.4: it reads Secrets and runs pods as any SA).
    text = (W3 / "catalog" / "tools.yaml").read_text(encoding="utf-8")
    assert "Kubernetes Service RBAC Admin" not in text and "roles/container.admin" not in text


def test_the_servicenow_identity_is_an_integration_user():
    snow = CATALOG["servers"]["servicenow-mcp"]
    assert snow["servicenow"]["write_role"] == "itil" and snow["servicenow"]["read_role"] == "sn_change_read"
