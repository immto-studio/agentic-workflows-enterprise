"""The templates checked by Terraform: the rendered HCL written into a copy of a fixture module and validated.

Chapter 14, W5-D8 and W5-D13. For one workspace, `validate_workspace` copies detect/fixtures/<workspace>
(the module as the state fixture describes it: the provider with its skip flags and a placeholder Region,
the resources, the child modules), applies every finding's rendering to the copy (`apply`: the blocks
appended in w5-drift.tf, the edits made in the blocks they name), and runs the only Terraform commands
W5 ever runs, `terraform init -backend=false` from a provider mirror and `terraform validate` (the fact
sheet, B.4), with `terraform fmt -check` beside them because the upstream's check runs it too. No
credentials are in the environment, no backend is read, nothing is planned or applied: the harness never
applies, and the pipeline's identity does after a person's merge (W5-D7).

The edits are the tiny set a template needs on a module written in terraform fmt's own shape (one block
per resource, two-space indents, `tags = {` on its own line): set an attribute, set or add keys in the
tags map (re-aligned), remove a block, put a comment above a block. A real repository's files are step
4's concern; here the fixture modules are the lab's own.

  python detect/validate.py [--plugin-dir DIR] [--workspace NAME]

runs the fixture night (fixture_night.findings_for) over the three workspaces and validates each, printing
one line per workspace; the plugin directory defaults to TF_PLUGIN_CACHE_DIR, as W4's plan_offline.py.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from findings import Finding  # noqa: E402
from render import Edit, Rendered, hcl_key, render  # noqa: E402

__all__ = ["FIXTURES", "WORKSPACES", "NEW_FILE", "Validation", "apply", "validate_workspace", "terraform", "module_files"]

FIXTURES = HERE / "fixtures"
WORKSPACES = ("network-live", "claims-api-prod", "sandbox-quill")
NEW_FILE = "w5-drift.tf"  # where a finding's blocks go: a new file, so an import or a note touches nothing else
_HEADER = re.compile(r'^resource "([^"]+)" "([^"]+)" \{$')
_PAIR = re.compile(r'^(\s+)("[^"]+"|[A-Za-z_][A-Za-z0-9_-]*)\s*=\s*(.*)$')


@dataclass(frozen=True)
class Validation:
    workspace: str
    ok: bool
    steps: dict[str, tuple[int, str]] = field(default_factory=dict)  # init, validate, fmt -> (exit code, output)
    files: dict[str, str] = field(default_factory=dict)  # the module after the edits, by relative path


# --- the module as text -------------------------------------------------------------------------------------

def module_files(workspace: str) -> dict[str, str]:
    """The fixture module's .tf files by path relative to its root."""
    root = FIXTURES / workspace
    return {path.relative_to(root).as_posix(): path.read_text(encoding="utf-8") for path in sorted(root.rglob("*.tf"))}


def _file_of(address: str) -> tuple[str, str]:
    """The file an address lives in and the `type.name` inside it: a module's resources are in
    modules/<name>/main.tf, the root's in main.tf. Index keys are dropped to find the block."""
    parts = re.sub(r"\[[^\]]*\]", "", address).split(".")
    path = "main.tf"
    while parts and parts[0] == "module":
        path = f"modules/{parts[1]}/main.tf"
        parts = parts[2:]
    if len(parts) != 2:
        raise ValueError(f"not a resource address: {address!r}")
    return path, ".".join(parts)


def _locate(lines: list[str], type_name: str) -> tuple[int, int]:
    """The line range [start, end] of `resource "type" "name" {` ... `}`."""
    type_, name = type_name.split(".", 1)
    for i, line in enumerate(lines):
        match = _HEADER.match(line)
        if match and match.group(1) == type_ and match.group(2) == name:
            for j in range(i + 1, len(lines)):
                if lines[j] == "}":
                    return i, j
            raise ValueError(f"block {type_name} has no closing brace")
    raise ValueError(f"no block {type_name} in the module")


def _set(lines: list[str], start: int, end: int, name: str, value: str) -> None:
    pattern = re.compile(rf"^(  {re.escape(name)}\s*= ).*$")  # the key and its alignment kept, the value replaced
    for i in range(start + 1, end):
        match = pattern.match(lines[i])
        if match:
            lines[i] = match.group(1) + value
            return
    lines[end:end] = ["", f"  {name} = {value}"]  # absent: its own group before the closing brace


def _tags(lines: list[str], start: int, end: int, tags: dict[str, str]) -> None:
    opened = next((i for i in range(start + 1, end) if lines[i] == "  tags = {"), None)
    pairs: list[tuple[str, str]] = []
    if opened is not None:
        closed = next(i for i in range(opened + 1, end) if lines[i] == "  }")
        for line in lines[opened + 1:closed]:
            match = _PAIR.match(line)
            if match:
                pairs.append((match.group(2), match.group(3)))
        del lines[opened:closed + 1]
        end -= closed + 1 - opened
    else:
        opened = end
        lines[opened:opened] = [""]
        opened += 1
        end += 1
    quoted = {hcl_key(k): v for k, v in tags.items()}
    kept = [(k, v) for k, v in pairs if k not in quoted]
    merged = kept + [(k, '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"') for k, v in quoted.items()]
    width = max(len(k) for k, _ in merged)
    block = ["  tags = {", *(f"    {k.ljust(width)} = {v}" for k, v in merged), "  }"]
    lines[opened:opened] = block


def _remove(lines: list[str], start: int, end: int) -> None:
    del lines[start:end + 1]
    if start < len(lines) and lines[start] == "" and (start == 0 or lines[start - 1] == ""):
        del lines[start]


def _comment(lines: list[str], start: int, text: str) -> None:
    lines[start:start] = text.rstrip("\n").split("\n")


def _apply_edit(files: dict[str, str], edit: Edit) -> None:
    path, type_name = _file_of(edit.address)
    lines = files[path].rstrip("\n").split("\n")
    start, end = _locate(lines, type_name)
    if edit.op == "set":
        _set(lines, start, end, edit.name, edit.value)
    elif edit.op == "tags":
        _tags(lines, start, end, dict(edit.value))
    elif edit.op == "remove":
        _remove(lines, start, end)
    elif edit.op == "comment":
        _comment(lines, start, str(edit.value))
    else:
        raise ValueError(f"unknown edit {edit.op!r}")
    files[path] = "\n".join(lines) + "\n"


def apply(files: dict[str, str], rendered: list[Rendered]) -> dict[str, str]:
    """The module's files with every rendering applied: the edits in place, the blocks in NEW_FILE."""
    out = dict(files)
    blocks = []
    for item in rendered:
        for edit in item.edits:
            _apply_edit(out, edit)
        if item.blocks:
            blocks.append(item.blocks.rstrip("\n"))
    if blocks:
        out[NEW_FILE] = "# Written by W5's templates from the night's findings (detect/render.py); no model wrote a line.\n\n" \
                        + "\n\n".join(blocks) + "\n"
    return out


# --- terraform, as W4 runs it offline -----------------------------------------------------------------------------

def terraform(work: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "TF_IN_AUTOMATION": "1", "AWS_SHARED_CREDENTIALS_FILE": str(work / "none"),
           "AWS_CONFIG_FILE": str(work / "none"), "AWS_PROFILE": ""}
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        env.pop(name, None)
    if any(a.startswith("-plugin-dir=") for a in args):
        env.pop("TF_PLUGIN_CACHE_DIR", None)  # init refuses to copy a plugin directory onto itself
    return subprocess.run(["terraform", *args], cwd=work, capture_output=True, text=True, timeout=900, env=env)


def validate_workspace(workspace: str, findings: list[Finding], plugin_dir: Path | None, work: Path | None = None) -> Validation:
    """The fixture module of `workspace` with the findings' renderings applied, initialised from the mirror
    and validated. `work` is the folder to build in (a temporary one otherwise)."""
    if workspace not in WORKSPACES:
        raise ValueError(f"workspace must be one of {', '.join(WORKSPACES)}, got {workspace!r}")
    files = apply(module_files(workspace), [render(f) for f in findings if f.workspace == workspace])
    with tempfile.TemporaryDirectory(prefix="w5-validate-") if work is None else _keep(work) as folder:
        root = Path(folder) / workspace
        for path, text in files.items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="\n")
        init = ["init", "-backend=false", "-input=false", "-no-color"]
        if plugin_dir:
            init.append(f"-plugin-dir={plugin_dir}")
        steps: dict[str, tuple[int, str]] = {}
        for step in (init, ["validate", "-no-color"], ["fmt", "-check", "-recursive", "-diff", "-no-color"]):
            result = terraform(root, *step)
            steps[step[0]] = (result.returncode, (result.stdout + result.stderr).strip())
            if result.returncode != 0 and step[0] != "fmt":
                break
    return Validation(workspace=workspace, ok=all(code == 0 for code, _ in steps.values()) and len(steps) == 3,
                      steps=steps, files=files)


class _keep:
    """A context that yields an existing folder and removes nothing."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def __enter__(self) -> str:
        self.path.mkdir(parents=True, exist_ok=True)
        return str(self.path)

    def __exit__(self, *_: Any) -> None:
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    cache = os.environ.get("TF_PLUGIN_CACHE_DIR")
    parser.add_argument("--plugin-dir", type=Path, default=Path(cache) if cache else None)
    parser.add_argument("--workspace", choices=WORKSPACES, default=None)
    args = parser.parse_args(argv)
    if shutil.which("terraform") is None:
        print("terraform is not on PATH", file=sys.stderr)
        return 2
    from fixture_night import findings_for
    failed = 0
    for workspace in ([args.workspace] if args.workspace else WORKSPACES):
        findings = findings_for(workspace)
        result = validate_workspace(workspace, findings, args.plugin_dir)
        state = "ok" if result.ok else "FAILED"
        print(f"{workspace}: {len(findings)} findings, {state} "
              f"({', '.join(f'{name} {code}' for name, (code, _) in result.steps.items())})")
        if not result.ok:
            failed += 1
            for name, (code, output) in result.steps.items():
                if code != 0:
                    print(f"  {name}:\n{output}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
