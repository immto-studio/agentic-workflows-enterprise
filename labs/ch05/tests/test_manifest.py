"""The workflow manifest: the schema, the two lab manifests, and the harness inside its manifest."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

LAB = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(LAB / "manifest"))
sys.path.insert(0, str(LAB / "harness"))

import manifest as mf  # noqa: E402

MANIFEST_DIR = LAB / "manifest"


def test_lab_manifests_validate() -> None:
    manifests = mf.load_manifests(MANIFEST_DIR)
    assert set(manifests) == {"w2-ops-assistant", "w3-incident"}


def test_a_manifest_without_regions_is_rejected(tmp_path: Path) -> None:
    data = yaml.safe_load((MANIFEST_DIR / "w2-ops-assistant.yaml").read_text(encoding="utf-8"))
    del data["regions"]
    (tmp_path / "w2.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(mf.ManifestError, match="'regions' is a required property"):
        mf.load_manifests(tmp_path)


def test_unknown_fields_are_rejected(tmp_path: Path) -> None:
    data = yaml.safe_load((MANIFEST_DIR / "w2-ops-assistant.yaml").read_text(encoding="utf-8"))
    data["tools"]["get_pod_status"]["runs_as"] = "cluster-admin"
    (tmp_path / "w2.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(mf.ManifestError, match="Additional properties are not allowed"):
        mf.load_manifests(tmp_path)


def test_two_manifests_for_one_workflow_are_rejected(tmp_path: Path) -> None:
    text = (MANIFEST_DIR / "w2-ops-assistant.yaml").read_text(encoding="utf-8")
    (tmp_path / "a.yaml").write_text(text, encoding="utf-8")
    (tmp_path / "b.yaml").write_text(text, encoding="utf-8")
    with pytest.raises(mf.ManifestError, match="two manifests"):
        mf.load_manifests(tmp_path)


def test_never_and_tools_do_not_overlap() -> None:
    for name, manifest in mf.load_manifests(MANIFEST_DIR).items():
        assert not set(manifest["never"]) & set(manifest["tools"]), name


def test_harness_allowlist_sits_inside_the_w2_manifest() -> None:
    # The harness may allow less than the manifest, never more: every allowed tool is in the
    # manifest, with no argument the manifest does not declare.
    import client as harness

    allowed = mf.allowlist(mf.load_manifests(MANIFEST_DIR)["w2-ops-assistant"])
    for tool, args in harness.ALLOWED.items():
        assert tool in allowed, tool
        assert args <= allowed[tool], (tool, args - allowed[tool])
