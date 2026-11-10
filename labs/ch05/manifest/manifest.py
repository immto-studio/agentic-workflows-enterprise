"""Load and validate workflow manifests (chapter 5; the schema is manifest/schema.json).

The gateway reads the manifests to decide which aliases a workflow may call and the highest data
class it may send; the harness's allowlist must sit inside the manifest's tools (a test checks it).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import yaml

HERE = Path(__file__).resolve().parent
SCHEMA = json.loads((HERE / "schema.json").read_text(encoding="utf-8"))
DATA_CLASSES = ("public", "internal", "confidential", "restricted")  # in order, least to most sensitive


class ManifestError(ValueError):
    """A manifest that does not validate, or two manifests for one workflow."""


def rank(data_class: str) -> int:
    return DATA_CLASSES.index(data_class)


def load_manifest(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(data, SCHEMA)
    except jsonschema.ValidationError as exc:
        raise ManifestError(f"{path.name}: {exc.message}") from exc
    return data


def load_manifests(folder: Path = HERE) -> dict[str, dict[str, Any]]:
    """workflow name -> manifest, for every *.yaml in the folder."""
    manifests: dict[str, dict[str, Any]] = {}
    for path in sorted(folder.glob("*.yaml")):
        data = load_manifest(path)
        if data["workflow"] in manifests:
            raise ManifestError(f"two manifests for workflow {data['workflow']!r}")
        manifests[data["workflow"]] = data
    return manifests


def allowlist(manifest: dict[str, Any]) -> dict[str, set[str]]:
    """The manifest's tools in the shape the chapter 1 loop takes: tool name -> argument names."""
    return {name: set(spec["args"]) for name, spec in manifest["tools"].items()}
