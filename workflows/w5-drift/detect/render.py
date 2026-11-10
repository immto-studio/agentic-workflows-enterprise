"""The templates: the HCL a pull request carries, rendered from a finding and never written by a model.

Chapter 14, W5-D8. A pull request's diff comes from one of eight templates over the structured finding;
the model writes the title and the body and no line of HCL, so a hijacked model can change a sentence and
not a block. The templates are `string.Template` files under templates/ (import, removed, revert, note)
and small functions here (adopt, tags, remove_block, instance_type); no template engine, no dependency.

Which template renders which finding (`template_for`):

- `unmanaged`: `import` for a resource with an identity of its own (an `import { to, id }` block and a
  resource block with the live attributes, Terraform 1.5); `revert` for a route, because a route in a
  managed route table is a member of a set the code owns: the code is kept, the next plan removes the
  route, and the comment shows the `route` block that would keep it instead (the postmortem's choice,
  made by a person).
- `changed`: `revert` when every changed attribute is one of REVERT_ATTRIBUTES (a security-group rule
  added outside Terraform, a route's target), because a rule or a route added by hand on a managed
  resource is proposed for removal: the code is kept and the plan reverts it, the comment says so.
  `adopt` otherwise (an instance type changed in the console): the code is set to the live value, as a
  diff fragment, because an apply that reverts a running instance's type stops it.
- `missing`: `removed` (a `removed` block with `lifecycle { destroy = false }`, Terraform 1.7, and the
  resource block deleted) for a state resource; `note` for a route.
- `untagged`: `tags`, the missing keys added to the resource's `tags` map with a placeholder value the
  owner fills in; `note` when the resource is not in Terraform.
- `idle` and `graviton_candidate`: `instance_type`, a one-line change (one size down; the Graviton
  family ADR-0050 names); `note` when there is no address or no smaller size.
- `unattached_volume` and `old_snapshot`: `remove_block`, the resource block deleted so the plan destroys
  the resource under a person's apply; `note` when the resource is not in Terraform (W5 deletes nothing).

Every rendering is a `Rendered`: the template's name, the diff fragment the pull request shows, the HCL
blocks to add in a new file, the edits to existing blocks (validate.apply writes them into a module), and
the values it held out. Author text (a rule's description, a tag value) is quoted as an HCL string or
written inside a comment with its line breaks removed, so it cannot close the string or the comment it
sits in.

Before a template copies a value a person or a client can write in the account (a tag's key or value, a
security group's name or description, a rule's description, a snapshot's description, a load balancer's
name), a `fields.Screen` checks it against what its field allows: the tagging standard's values or the
tagging API's pattern for a tag, and printable ASCII on one line, at most 255 characters, for a name or a
description, with no text that reads as an instruction in either. A value that fails stays out of the
diff: `fields.HELD` takes its place, or a tag with a failing key is left out, and `Rendered.held` lists
it for the writer, who quotes it in the body's facts as data read from the account. Chapter 15's red-team
moved planted text into four such fields, and until this check the templates copied it into the diff. A
value that passes renders exactly as it did before.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from string import Template
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from fields import HELD, Held, Screen  # noqa: E402
from findings import Finding  # noqa: E402

__all__ = ["TEMPLATES", "REVERT_ATTRIBUTES", "TAG_PLACEHOLDER", "Edit", "Rendered", "template_for", "render",
           "hcl", "hcl_key", "quote", "import_address", "HELD"]

TEMPLATES = ("import", "revert", "adopt", "removed", "tags", "remove_block", "instance_type", "note")
# A changed attribute whose live value is proposed for reversal (the code kept, the plan reverts it).
REVERT_ATTRIBUTES = frozenset({("aws_security_group", "ingress"), ("aws_security_group", "egress"),
                               ("aws_route", "target")})
TAG_PLACEHOLDER = "TODO: set by {owner}"  # letters, digits, spaces, and : only, which a tag value allows
TEMPLATE_DIR = HERE / "templates"
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")
_NAME = re.compile(r"[^A-Za-z0-9_]")
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


@dataclass(frozen=True)
class Edit:
    """One change to an existing block of a module: set an attribute, set or add tag keys, remove the
    block, or put a comment above it. validate.apply writes it; the fragment shows it."""
    op: str  # set | tags | remove | comment
    address: str
    name: str = ""  # the attribute, for set and tags
    value: Any = None  # the HCL text for set, the {key: value} map for tags, the comment text for comment


@dataclass(frozen=True)
class Rendered:
    template: str
    fragment: str  # the diff fragment the pull request shows
    blocks: str  # HCL to add in a new file of the module (import and resource, removed, a note), or ""
    edits: tuple[Edit, ...]  # changes to blocks the module already has
    held: tuple[Held, ...] = ()  # account values that failed their field's check and stayed out of all three


def _template(name: str) -> Template:
    return Template((TEMPLATE_DIR / f"{name}.tf").read_text(encoding="utf-8"))


# --- the template choice ------------------------------------------------------------------------------

def template_for(finding: Finding) -> str:
    kind, type_, address, evidence = finding.kind, finding.resource_type, finding.address, finding.evidence
    if kind == "unmanaged":
        return "revert" if type_ == "aws_route" else "import"
    if kind == "changed":
        attributes = evidence.get("attributes", {})
        return "revert" if attributes and all((type_, a) in REVERT_ATTRIBUTES for a in attributes) else "adopt"
    if kind == "missing":
        return "removed" if address else "note"
    if kind == "untagged":
        return "tags" if address else "note"
    if kind in ("idle", "graviton_candidate"):
        return "instance_type" if address and evidence.get("suggested_type") else "note"
    if kind in ("unattached_volume", "old_snapshot"):
        return "remove_block" if address else "note"
    raise ValueError(f"no template for a finding of kind {kind!r}")


# --- HCL ---------------------------------------------------------------------------------------------------

def quote(text: str) -> str:
    """An HCL string literal: backslashes, quotes, and line breaks escaped, interpolation sequences
    doubled so a value never becomes an expression."""
    escaped = (str(text).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
               .replace("${", "$${").replace("%{", "%%{"))
    return f'"{escaped}"'


def hcl(value: Any, indent: str = "") -> str:
    """An HCL expression for a scalar, a list, or a map, multi-line maps aligned as terraform fmt leaves them."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return quote(value)
    if isinstance(value, (list, tuple)):
        if not value:
            return "[]"
        return "[" + ", ".join(hcl(v) for v in value) + "]"
    if isinstance(value, dict):
        if not value:
            return "{}"
        inner = indent + "  "
        lines = _aligned([(hcl_key(k), hcl(v, inner)) for k, v in value.items()], inner)
        return "{\n" + "\n".join(lines) + "\n" + indent + "}"
    raise TypeError(f"no HCL for {type(value).__name__}")


def hcl_key(key: str) -> str:
    """A map key: bare when it is an identifier, quoted otherwise (`"karpenter.sh/nodepool"`)."""
    return key if _IDENTIFIER.match(key) else quote(key)


def _aligned(pairs: list[tuple[str, str]], indent: str) -> list[str]:
    """`key = value` lines with the equals signs aligned, as terraform fmt aligns a run of attributes."""
    width = max((len(k) for k, _ in pairs), default=0)
    return [f"{indent}{k.ljust(width)} = {v}" for k, v in pairs]


def _comment(text: str, indent: str = "") -> str:
    """One comment line; line breaks and control characters in author text become spaces."""
    return f"{indent}# {_CONTROL.sub(' ', str(text)).strip()}"


def _name(text: str) -> str:
    name = _NAME.sub("_", text)
    return name if name[:1].isalpha() or name[:1] == "_" else f"r_{name}"


def import_address(finding: Finding, screen: Screen | None = None) -> str:
    """The address an unmanaged resource is imported to: the type and a name made from its id (a load
    balancer's id is an ARN, so its name is used instead, when the name passes the screen)."""
    if finding.resource_type == "aws_lb":
        name = finding.evidence.get("name")
        if name and screen is not None and screen.text("name", name) == HELD:
            name = None
        return f"aws_lb.{_name(name or 'imported')}"
    return f"{finding.resource_type}.{_name(finding.resource_id)}"


def _rule_blocks(kind: str, rules: list[list[Any]], indent: str = "  ") -> list[str]:
    """`ingress {}` and `egress {}` blocks from rules as [protocol, from, to, source]."""
    out = []
    for protocol, frm, to, source in rules:
        if source == "self":
            field = "self"
            value: Any = True
        elif str(source).startswith("sg-"):
            field, value = "security_groups", [source]
        elif str(source).startswith("pl-"):
            field, value = "prefix_list_ids", [source]
        elif ":" in str(source):
            field, value = "ipv6_cidr_blocks", [source]
        else:
            field, value = "cidr_blocks", [source]
        pairs = [("protocol", quote(str(protocol))), ("from_port", str(frm)), ("to_port", str(to)), (field, hcl(value))]
        out.append(f"{indent}{kind} {{\n" + "\n".join(_aligned(pairs, indent + "  ")) + f"\n{indent}}}")
    return out


def _route_argument(target: str) -> str:
    """The `route` block argument a target id belongs to, by the id's prefix."""
    prefixes = (("tgw-", "transit_gateway_id"), ("nat-", "nat_gateway_id"), ("igw-", "gateway_id"), ("vgw-", "gateway_id"),
                ("pcx-", "vpc_peering_connection_id"), ("eni-", "network_interface_id"), ("eigw-", "egress_only_gateway_id"),
                ("lgw-", "local_gateway_id"), ("cagw-", "carrier_gateway_id"), ("vpce-", "vpc_endpoint_id"))
    if target.startswith("arn:") and ":core-network/" in target:
        return "core_network_arn"
    return next((arg for prefix, arg in prefixes if target.startswith(prefix)), "gateway_id")


def _route_block(destination: str, target: str, indent: str = "  ") -> list[str]:
    field = "ipv6_cidr_block" if ":" in destination else "destination_prefix_list_id" if destination.startswith("pl-") else "cidr_block"
    pairs = [(field, quote(destination)), (_route_argument(target), quote(target))]
    return [f"{indent}route {{", *_aligned(pairs, indent + "  "), f"{indent}}}"]


def _resource_body(finding: Finding, s: Screen) -> str:
    """The live attributes of an unmanaged resource as a resource block's body, by type; the name, the
    description, and the tags through the screen."""
    e, type_ = finding.evidence, finding.resource_type
    scalars: list[tuple[str, str]] = []
    blocks: list[str] = []
    if type_ == "aws_ebs_volume":
        scalars = [("availability_zone", quote(e["availability_zone"])), ("size", str(e["size"])), ("type", quote(e["type"]))]
        if e.get("iops") and e["type"] in ("gp3", "io1", "io2"):
            scalars.append(("iops", str(e["iops"])))
        scalars.append(("encrypted", hcl(bool(e.get("encrypted")))))
    elif type_ == "aws_instance":
        scalars = [("ami", quote(e["ami"])), ("instance_type", quote(e["instance_type"])), ("subnet_id", quote(e["subnet_id"])),
                   ("vpc_security_group_ids", hcl(e.get("security_group_ids", [])))]
    elif type_ == "aws_security_group":
        scalars = [("name", quote(s.text("name", e["name"]))), ("description", quote(s.text("description", e.get("description", "")))),
                   ("vpc_id", quote(e["vpc_id"]))]
        blocks = _rule_blocks("ingress", e.get("ingress", [])) + _rule_blocks("egress", e.get("egress", []))
    elif type_ == "aws_route_table":
        scalars = [("vpc_id", quote(e["vpc_id"]))]
        for destination, route in sorted(e.get("routes", {}).items()):
            blocks.append("\n".join(_route_block(destination, route["target"])))
    elif type_ == "aws_lb":
        scalars = [("name", quote(s.text("name", e["name"]))), ("internal", hcl(e.get("scheme") == "internal")),
                   ("load_balancer_type", quote(e["type"])), ("subnets", hcl(e.get("subnets", []))),
                   ("security_groups", hcl(e.get("security_group_ids", [])))]
    elif type_ == "aws_ebs_snapshot":
        scalars = [("volume_id", quote(e["volume_id"])), ("description", quote(s.text("description", e.get("description", ""))))]
    parts = ["\n".join(_aligned(scalars, "  "))]
    parts.extend(blocks)
    parts.append("\n".join(_aligned([("tags", hcl(s.tags(e.get("tags", {})), "  "))], "  ")))
    return "\n\n".join(p for p in parts if p)


# --- the fragments -----------------------------------------------------------------------------------------

def _added(text: str) -> str:
    return "\n".join("+" + line for line in text.rstrip("\n").split("\n"))


def _removed(text: str) -> str:
    return "\n".join("-" + line for line in text.rstrip("\n").split("\n"))


def _header(address: str) -> str:
    type_, name = address.rsplit(".", 1)
    return f'resource "{type_}" "{name}" {{'


def _block_from_state(finding: Finding) -> str:
    """The resource block as the state describes it, for a fragment that deletes it."""
    e = finding.evidence.get("state", {}) if finding.kind == "missing" else finding.evidence
    pairs = [(k, hcl(e[k])) for k in ("availability_zone", "size", "type", "instance_type", "name") if e.get(k) is not None]
    body = "\n".join(_aligned(pairs, "  ")) if pairs else "  # ..."
    return f"{_header(finding.address)}\n{body}\n}}"


def _rule_text(rule: list[Any], descriptions: dict[str, str], s: Screen, attribute: str) -> str:
    protocol, frm, to, source = rule
    ports = "all ports" if str(protocol) == "-1" else f"{frm}-{to}"
    text = f"{protocol} {ports} from {source}"
    description = descriptions.get(json.dumps(rule))
    if not description:
        return text
    if s.text("description", description, where=f"{attribute} rule {text}") == HELD:
        return f"{text} (its description is held out of the diff)"
    return f'{text} ("{_CONTROL.sub(" ", description)}")'


def _revert(finding: Finding, s: Screen) -> Rendered:
    e = finding.evidence
    if finding.resource_type == "aws_route":
        address = e["route_table_address"]
        headline = (f"The live route table {e['route_table_id']} carries a route the code does not: "
                    f"{e['destination']} -> {e['target']}")
        details = ["# The next plan removes it (the postmortem of 2026-05-19). To keep the route instead, add to the",
                   "# route table's code:", *("#   " + line for line in _route_block(e["destination"], e["target"], ""))]
    else:
        address = finding.address or ""
        lines = []
        for attribute, change in e.get("attributes", {}).items():
            descriptions = change.get("descriptions", {})
            for rule in change.get("added", []):
                lines.append(f"#   {attribute} added outside Terraform: {_rule_text(rule, descriptions, s, attribute)}")
            for rule in change.get("removed", []):
                lines.append(f"#   {attribute} removed outside Terraform: {_rule_text(rule, descriptions, s, attribute)}")
            if "added" not in change:
                lines.append(f"#   {attribute}: code {hcl(change['state'])}, live {hcl(change['live'])}")
        headline = f"The live {finding.resource_type} {finding.resource_id} differs from its code:"
        details = lines
    text = _template("revert").substitute(key=finding.key, headline=_CONTROL.sub(" ", headline),
                                          details="\n".join(details)).rstrip("\n")
    fragment = _added(text) + "\n " + _header(address)
    return Rendered("revert", fragment, "", (Edit("comment", address, value=text),))


def _adopt(finding: Finding, s: Screen) -> Rendered:
    edits, minus, plus, comments = [], [], [], []
    for attribute, change in finding.evidence.get("attributes", {}).items():
        if (finding.resource_type, attribute) in REVERT_ATTRIBUTES or attribute == "attachment":
            comments.append(f"# W5 drift {finding.key}: {attribute} differs live and is left to the plan to revert")
            continue
        live = s.tags(change["live"]) if attribute == "tags" and isinstance(change["live"], dict) else change["live"]
        value = hcl(live, "  ")
        edits.append(Edit("set", finding.address, attribute, value))
        minus.append(f"  {attribute} = {hcl(change['state'], '  ')}")
        plus.append(f"  {attribute} = {value}")
    fragment_lines = [*("+" + c for c in comments), " " + _header(finding.address), *_removed("\n".join(minus)).split("\n"),
                      *_added("\n".join(plus)).split("\n"), " }"]
    if comments:
        edits.append(Edit("comment", finding.address, value="\n".join(comments)))
    return Rendered("adopt", "\n".join(line for line in fragment_lines if line not in ("+", "-")), "", tuple(edits))


def _import(finding: Finding, s: Screen) -> Rendered:
    address = import_address(finding, s)
    type_, name = address.split(".", 1)
    blocks = _template("import").substitute(address=address, id=finding.resource_id, type=type_, name=name,
                                            body=_resource_body(finding, s))
    return Rendered("import", _added(blocks), blocks, ())


def _removed_block(finding: Finding, s: Screen) -> Rendered:
    blocks = _template("removed").substitute(address=finding.address)
    fragment = _removed(_block_from_state(finding)) + "\n" + _added(blocks)
    return Rendered("removed", fragment, blocks, (Edit("remove", finding.address),))


def _remove_block(finding: Finding, s: Screen) -> Rendered:
    return Rendered("remove_block", _removed(_block_from_state(finding)), "", (Edit("remove", finding.address),))


def _tags(finding: Finding, s: Screen) -> Rendered:
    """The missing keys added with a placeholder, and a value the standard doesn't allow replaced by one. The
    owner team named in the placeholder is a live tag's value, and a value the standard doesn't allow fails its
    field by definition, so neither reaches the diff unscreened: the replaced value's line is left out."""
    e = finding.evidence
    owner = e.get("present", {}).get("owner_team")
    owner = owner if owner and s.tag_value("owner_team", owner) != HELD else "the owner team"
    new = {key: TAG_PLACEHOLDER.format(owner=owner) for key in e.get("missing", [])}
    for key, value in e.get("bad", {}).items():
        new[key] = f"TODO: one of {', '.join(e.get('allowed', {}).get(key, []))}"
    width = max((len(hcl_key(k)) for k in new), default=0)
    plus = [f"    {hcl_key(k).ljust(width)} = {quote(v)}" for k, v in new.items()]
    minus = [f"    {hcl_key(k).ljust(width)} = {quote(v)}" for k, v in e.get("bad", {}).items()
             if s.tag_value(k, v) != HELD]
    fragment = "\n".join([" " + _header(finding.address), "   tags = {", *("-" + line for line in minus),
                          *("+" + line for line in plus), "   }", " }"])
    return Rendered("tags", fragment, "", (Edit("tags", finding.address, "tags", new),))


def _instance_type(finding: Finding, s: Screen) -> Rendered:
    e = finding.evidence
    value = quote(e["suggested_type"])
    fragment = "\n".join([" " + _header(finding.address), f"-  instance_type = {quote(e['code_instance_type'])}",
                          f"+  instance_type = {value}", " }"])
    return Rendered("instance_type", fragment, "", (Edit("set", finding.address, "instance_type", value),))


def _note(finding: Finding, s: Screen) -> Rendered:
    e, kind = finding.evidence, finding.kind
    subject = f"{finding.resource_id} ({finding.resource_type})"
    if kind == "untagged":
        headline = f"{subject} is not in Terraform and lacks the tags the standard requires: {', '.join(e.get('missing', []))}"
        details = [f"#   {k} is {quote(v)}; the standard allows {', '.join(e.get('allowed', {}).get(k, []))}"
                   if s.tag_value(k, v) != HELD else
                   f"#   {k} holds a value the standard doesn't allow, held out of the diff; the standard allows "
                   f"{', '.join(e.get('allowed', {}).get(k, []))}" for k, v in e.get("bad", {}).items()]
        details.append("# Its owner adds the tags where it is managed, or imports it (see the unmanaged finding).")
    elif kind == "unattached_volume":
        headline = f"{subject} is not in Terraform, is attached to nothing, and is {e.get('age_days')} days old"
        details = ["# The tagging standard stops an untagged non-production resource after 7 days and deletes it",
                   "# after 30 (FinOps' tag policy, not W5). Its owner deletes it or imports it."]
    elif kind == "old_snapshot":
        headline = f"{subject} is not in Terraform: a snapshot of {e.get('volume_id')} taken {e.get('started')}, {e.get('age_days')} days old"
        details = ["# Its owner deletes it or imports it; W5 deletes nothing."]
    elif kind == "missing":
        headline = f"The route {e.get('destination')} -> {e.get('target')} of {e.get('route_table_id')} is in the code and not live"
        details = ["# The next plan re-creates it from the code; remove the route block to accept the deletion."]
    else:
        headline = f"{subject}: {kind.replace('_', ' ')}"
        details = ["# No code change is proposed: the resource is not in Terraform or has no smaller size."]
    text = _template("note").substitute(key=finding.key, headline=_CONTROL.sub(" ", headline),
                                        details="\n".join(details)).rstrip("\n")
    return Rendered("note", _added(text), text, ())


def render(finding: Finding) -> Rendered:
    """The HCL for one finding, by its template (template_for decides; the finding's own `template` field
    is what the detectors set and must agree), and the account values the screen held out of it. The screen
    knows the tagging standard's values where the finding carries them (an untagged finding's `allowed`)."""
    name = template_for(finding)
    if finding.template and finding.template != name:
        raise ValueError(f"finding {finding.key} says template {finding.template!r}, the rule says {name!r}")
    screen = Screen(finding.evidence.get("allowed") if finding.kind == "untagged" else None)
    rendered = {"import": _import, "revert": _revert, "adopt": _adopt, "removed": _removed_block, "tags": _tags,
                "remove_block": _remove_block, "instance_type": _instance_type, "note": _note}[name](finding, screen)
    return replace(rendered, held=screen.held)
