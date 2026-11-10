"""The model register (chapter 16, step 8, O-D14): the loader, and the check that the register and the gateways
name the same deployments.

lifecycle/register.yaml is one register for the three clouds and the local models, merged from chapters 6 to 9. A
model has one lifecycle (stage, retirement date, replacement) and one or more deployments, each with the identifier
a gateway pins it by. `check` reads every LiteLLM configuration the register names under `gateways.litellm` and
compares deployment by deployment: the deployment id (`model_info.id`) must be a register deployment that names the
configuration, the model string's identifier must be the register's, and the alias must be one the register gives
it; the other way round, every register deployment that names a configuration must be in it. The two Terraform
files are read the way chapters 7 and 8's own tests read them. `digests` asks an Ollama for what it serves and sets
its digests against the register's local pins; nothing else here touches the network.

Run (from labs/ch16):
  python lifecycle/register.py --check                         the consistency check; exit 1 on a problem
  python lifecycle/register.py --digests http://127.0.0.1:11435  the local pins against what that Ollama reports
  python lifecycle/register.py --json                          the register as JSON, dates as ISO strings
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
LAB = HERE.parent
ROOT = LAB.parents[1]  # the companion repository
REGISTER = HERE / "register.yaml"
REQUIRED = ("id", "name", "cloud", "host", "model", "pinned", "stage", "stage_scheme", "retires",
            "retires_no_earlier_than", "replacement", "processed_in_canada", "pin", "deployments", "source")
DEPLOYMENT_REQUIRED = ("id", "identifier", "aliases", "region", "hosting")
CLOUDS = ("aws", "google", "azure", "local")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def load(path: Path = REGISTER) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def models(register: dict[str, Any]) -> list[dict[str, Any]]:
    return list(register["models"])


def identifier_of(model_string: str) -> str:
    """The identifier in a LiteLLM model string: what follows the provider prefix (bedrock/converse/X, ollama_chat/X,
    hosted_vllm/X)."""
    return model_string.rsplit("/", 1)[-1]


def read_yaml(relative: str) -> Any:
    return yaml.safe_load((ROOT / relative).read_text(encoding="utf-8"))


# --- the register's own shape -----------------------------------------------------------------------------------

def shape_problems(register: dict[str, Any]) -> list[str]:
    """What is wrong with the register itself: a missing field, a stage outside its scheme, a pin without the
    digest it claims, a deployment that names no configuration and no Terraform."""
    out: list[str] = []
    schemes = register["stages"]
    seen: set[str] = set()
    for m in models(register):
        name = m.get("id", "?")
        if name in seen:
            out.append(f"{name}: listed twice")
        seen.add(name)
        for field in REQUIRED:
            if field not in m:
                out.append(f"{name}: no {field}")
        if m.get("cloud") not in CLOUDS:
            out.append(f"{name}: cloud {m.get('cloud')!r} is not one of {CLOUDS}")
        scheme = schemes.get(m.get("stage_scheme"))
        if scheme is None or m.get("stage") not in scheme["values"]:
            out.append(f"{name}: stage {m.get('stage')!r} is not in the {m.get('stage_scheme')!r} scheme")
        if m.get("retires") is not None and not isinstance(m["retires"], dt.date):
            out.append(f"{name}: retires is not a date")
        if m.get("retires") is not None and m.get("retires_no_earlier_than") is not None:
            out.append(f"{name}: both a retirement date and an earliest date; keep one")
        pin = m.get("pin") or {}
        for field in ("kind", "value", "versioned"):
            if field not in pin:
                out.append(f"{name}: pin has no {field}")
        if pin.get("kind") == "ollama digest":
            if not HEX64.match(str(pin.get("value"))):
                out.append(f"{name}: an Ollama digest is 64 hex characters, not {pin.get('value')!r}")
            if not pin.get("server"):
                out.append(f"{name}: a local pin names the server that reports the digest")
        if pin.get("versioned") is False and not pin.get("note"):
            out.append(f"{name}: an unversioned pin says what that means")
        if m.get("cloud") == "local" and m.get("pinned") and m.get("stage") != "serving":
            out.append(f"{name}: a pinned local model is serving")
        for d in m.get("deployments") or []:
            did = d.get("id", "?")
            for field in DEPLOYMENT_REQUIRED:
                if field not in d:
                    out.append(f"{name}/{did}: no {field}")
            if not d.get("configs") and not d.get("terraform"):
                out.append(f"{name}/{did}: names no gateway configuration and no Terraform file")
            if m.get("pinned") and m.get("cloud") != "local" and not (d.get("configs") or d.get("terraform")):
                out.append(f"{name}/{did}: a pinned model's deployment is somewhere")
        if m.get("pinned") and not m.get("deployments"):
            out.append(f"{name}: pinned, and behind nothing")
    return out


# --- the gateways -----------------------------------------------------------------------------------------------

def register_deployments(register: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    return [(m, d) for m in models(register) for d in m.get("deployments") or []]


def litellm_problems(register: dict[str, Any], root: Path = ROOT) -> list[str]:
    """The register against every LiteLLM configuration it names, both ways."""
    out: list[str] = []
    pairs = register_deployments(register)
    for relative in register["gateways"]["litellm"]:
        path = root / relative
        if not path.exists():
            out.append(f"{relative}: not in the repository")
            continue
        config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        entries = config.get("model_list") or []
        for entry in entries:
            info = entry.get("model_info") or {}
            did, alias = str(info.get("id", "")), entry["model_name"]
            ident = identifier_of(str(entry["litellm_params"]["model"]))
            found = [(m, d) for m, d in pairs if d["id"] == did and relative in (d.get("configs") or [])]
            if not found:
                out.append(f"{relative}: deployment {did!r} ({alias} -> {ident}) is not in the register")
                continue
            m, d = found[0]
            if d["identifier"] != ident:
                out.append(f"{relative}: {did!r} serves {ident}, the register says {d['identifier']}")
            if alias not in d["aliases"]:
                out.append(f"{relative}: {did!r} serves alias {alias}, the register gives it {d['aliases']}")
            if str(info.get("region")) != str(d["region"]):
                out.append(f"{relative}: {did!r} is in {info.get('region')}, the register says {d['region']}")
            if str(info.get("hosting")) != str(d["hosting"]):
                out.append(f"{relative}: {did!r} is {info.get('hosting')}, the register says {d['hosting']}")
        ids_here = {str((e.get("model_info") or {}).get("id", "")) for e in entries}
        for m, d in pairs:
            if relative in (d.get("configs") or []) and d["id"] not in ids_here:
                out.append(f"{relative}: the register's {d['id']!r} ({m['id']}) is not in it")
    return out


def google_models(path: Path) -> set[str]:
    """The model IDs chapter 7's Terraform deploys under ${local.models}/, as its own test reads them."""
    text = path.read_text(encoding="utf-8")
    return set(re.findall(r'"\$\{local\.models\}/([a-z0-9.\-]+)"', text))


def azure_chat_model(path: Path) -> dict[str, str]:
    """The chat_model default in chapter 8's variables.tf: {name, version}, as its own test reads it."""
    import hcl2

    def unquote(value: Any) -> Any:
        if isinstance(value, dict):
            return {unquote(k): unquote(v) for k, v in value.items() if k not in ("__is_block__", "__comments__")}
        if isinstance(value, str) and len(value) >= 2 and value[0] == value[-1] == '"':
            return value[1:-1]
        return value

    with path.open(encoding="utf-8") as handle:
        variables = {k: v for block in hcl2.load(handle)["variable"] for k, v in unquote(block).items()}
    return dict(variables["chat_model"]["default"])


def terraform_problems(register: dict[str, Any], root: Path = ROOT) -> list[str]:
    out: list[str] = []
    pairs = register_deployments(register)
    for item in register["gateways"]["terraform"]:
        relative = item["path"]
        path = root / relative
        if not path.exists():
            out.append(f"{relative}: not in the repository")
            continue
        mine = [(m, d) for m, d in pairs if d.get("terraform") == relative]
        if relative.startswith("labs/ch07/"):
            deployed = google_models(path)
            registered = {d["identifier"] for _, d in mine}
            for name in sorted(deployed - registered):
                out.append(f"{relative}: deploys {name}, which the register doesn't list for it")
            for name in sorted(registered - deployed):
                out.append(f"{relative}: the register's {name} is not deployed there")
        elif relative.startswith("labs/ch08/"):
            default = azure_chat_model(path)
            registered = {(d["identifier"], str(d.get("version"))) for _, d in mine}
            if {(default["name"], default["version"])} != registered:
                out.append(f"{relative}: chat_model is {default}, the register says {sorted(registered)}")
        else:
            out.append(f"{relative}: no reader for this Terraform file")
    return out


def source_registers_problems(register: dict[str, Any], root: Path = ROOT) -> list[str]:
    """Every model of chapters 6, 7 and 8's registers is here with the same dates and stage."""
    out: list[str] = []
    mine = {m["model"] + (f" {m['version']}" if m.get("version") else ""): m for m in models(register)}
    for name, entry in read_yaml("labs/ch06/models.yaml").items():
        m = mine.get(name)
        if m is None:
            out.append(f"labs/ch06/models.yaml: {name} is not in the register")
            continue
        if (entry.get("eol"), entry.get("lifecycle"), entry.get("pinned")) != (m["retires"], m["stage"], m["pinned"]):
            out.append(f"labs/ch06/models.yaml: {name} differs (eol, lifecycle, pinned)")
        if entry.get("eol_no_sooner_than") != m["retires_no_earlier_than"]:
            out.append(f"labs/ch06/models.yaml: {name} differs (eol_no_sooner_than)")
    for name, entry in read_yaml("labs/ch07/models.yaml").items():
        m = mine.get(name)
        if m is None:
            out.append(f"labs/ch07/models.yaml: {name} is not in the register")
            continue
        if (entry.get("retires"), entry.get("retires_no_earlier_than")) != (m["retires"], m["retires_no_earlier_than"]):
            out.append(f"labs/ch07/models.yaml: {name} differs (retires)")
        if not m["pinned"]:
            out.append(f"labs/ch07/models.yaml: {name} is pinned there")
    for name, entry in read_yaml("labs/ch08/models.yaml").items():
        m = mine.get(f"{name} {entry['version']}")
        if m is None:
            out.append(f"labs/ch08/models.yaml: {name} {entry['version']} is not in the register")
            continue
        if (entry["retires"], entry["stage"], entry["pinned"]) != (m["retires"], m["stage"], m["pinned"]):
            out.append(f"labs/ch08/models.yaml: {name} differs (retires, stage, pinned)")
    return out


def check(register: dict[str, Any] | None = None, root: Path = ROOT) -> list[str]:
    """Every problem, or an empty list: the register's shape, the LiteLLM configurations both ways, the two
    Terraform files, and the three source registers."""
    register = register or load()
    return (shape_problems(register) + litellm_problems(register, root) + terraform_problems(register, root)
            + source_registers_problems(register, root))


# --- what an Ollama reports -------------------------------------------------------------------------------------

def digests(register: dict[str, Any], base: str) -> dict[str, Any]:
    """The local pins against the digests one Ollama reports now (GET /api/version, /api/tags)."""
    import httpx

    version = httpx.get(base.rstrip("/") + "/api/version", timeout=10.0).json().get("version")
    tags = {t["name"]: t for t in httpx.get(base.rstrip("/") + "/api/tags", timeout=10.0).json().get("models") or []}
    rows = []
    for m in models(register):
        if m["pin"].get("kind") != "ollama digest":
            continue
        tag = tags.get(m["model"]) or {}
        rows.append({"model": m["id"], "tag": m["model"], "pinned_digest": m["pin"]["value"],
                     "pinned_on": m["pin"].get("server"), "served": bool(tag), "reported_digest": tag.get("digest"),
                     "size_bytes": tag.get("size"), "modified_at": tag.get("modified_at"),
                     "matches": tag.get("digest") == m["pin"]["value"]})
    return {"ollama": version, "base": base, "models": rows,
            "other_tags": sorted(set(tags) - {m["model"] for m in models(register)})}


# --- the command ------------------------------------------------------------------------------------------------

def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _json_ready(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_ready(v) for v in value]
    if isinstance(value, dt.date):
        return value.isoformat()
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="the register against the gateways; exit 1 on a problem")
    parser.add_argument("--digests", metavar="URL", help="the local pins against the digests this Ollama reports")
    parser.add_argument("--json", action="store_true", help="print the register as JSON")
    args = parser.parse_args(argv)
    register = load()
    if args.json:
        print(json.dumps(_json_ready(register), indent=1, ensure_ascii=False))
    if args.digests:
        print(json.dumps(digests(register, args.digests), indent=1))
    if args.check or not (args.json or args.digests):
        problems = check(register)
        counts = {c: sum(1 for m in models(register) if m["cloud"] == c) for c in CLOUDS}
        print(f"{len(models(register))} models: " + ", ".join(f"{c} {n}" for c, n in counts.items())
              + f"; {len(register_deployments(register))} deployments")
        if problems:
            print("\n".join(f"- {p}" for p in problems))
            return 1
        print("the register and the gateways name the same deployments")
    return 0


if __name__ == "__main__":
    sys.exit(main())
