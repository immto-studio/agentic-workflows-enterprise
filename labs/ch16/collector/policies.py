"""The Collector's tail-sampling policies and content drop, written again in Python to check its decisions.

Chapter 16, step 3 (companion #14, O-D3). config.yaml holds the policies the Collector runs. This module
holds what they should decide, from their documented semantics at v0.164.1, so the run and the tests can
set every decision the Collector made against an independent one:

- failed: a span with status ERROR or an `error.type` attribute;
- refused: `larkspur.refused` true on a span or a resource;
- slow: the trace's latest end minus its earliest start, in whole milliseconds, above threshold_ms;
- over-budget: a span of a workflow whose `larkspur.cost_usd` is at least that workflow's per_run_usd;
- fallback: `larkspur.fallback` true;
- share-of-the-rest: FNV-1a over the hash salt and the trace id's 16 bytes, at or below the threshold
  the processor computes from the percentage (`hashTraceID` and `calculateThreshold` in its source).

The trace is kept if any policy keeps it. The policy the Collector records is the first in the list among
those that kept it with the lowest threshold: every keep-all policy reports a share of one, so a trace
the share kept alone is the only one that records it. Its share is OpenTelemetry's threshold in the
span's tracestate (`ot=th:...`), and `share_from_tracestate` reads it back.

The over-budget conditions and the content attributes aren't typed in twice: `over_budget_conditions` writes
the conditions from the manifests, and `content_attributes` reads the opt-in attributes from the pinned
span definitions; the tests hold config.yaml to both.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Iterable, Mapping
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
LAB = HERE.parent
COMPANION = LAB.parents[1]
CONFIG = HERE / "config.yaml"
SEMCONV = HERE / "semconv-genai"
REGISTRY = LAB.parent / "ch05" / "tracing" / "semconv-genai" / "gen-ai-registry.yaml"
MANIFEST_GLOBS = ("workflows/*/manifest/*.yaml", "labs/ch05/manifest/*.yaml", "labs/ch06/manifests/*.yaml")
WORKFLOW_MANIFESTS = "workflows/*/manifest/*.yaml"
KEEP_ALL = ("failed", "refused", "slow", "over-budget", "fallback")
SHARE = "share-of-the-rest"
MASK = (1 << 64) - 1
_TH = re.compile(r"(?:^|;)th:([0-9a-f]{1,14})(?:;|$)")


# --- what config.yaml must agree with ----------------------------------------------------------------------

def config(path: Path = CONFIG) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def manifests(globs: Iterable[str] = MANIFEST_GLOBS) -> dict[Path, dict[str, Any]]:
    """Every workflow manifest in the companion, by path."""
    return {path: yaml.safe_load(path.read_text(encoding="utf-8"))
            for pattern in globs for path in sorted(COMPANION.glob(pattern))}


def budgets(globs: Iterable[str] = (WORKFLOW_MANIFESTS,)) -> dict[str, Decimal]:
    """workflow -> per_run_usd, from the workflows' own manifests (one per workflow name)."""
    out: dict[str, Decimal] = {}
    for data in manifests(globs).values():
        value = Decimal(str(data["budget"]["per_run_usd"]))
        if out.setdefault(data["workflow"], value) != value:
            raise ValueError(f"two per_run_usd for {data['workflow']}")
    return out


def over_budget_conditions(per_run: Mapping[str, Decimal]) -> list[str]:
    """The OTTL conditions config.yaml's over-budget policy holds, one per workflow, in the manifests' order."""
    return [f'span.attributes["larkspur.workflow"] == "{workflow}" and '
            f'span.attributes["larkspur.cost_usd"] >= {budget:.2f}' for workflow, budget in per_run.items()]


@functools.lru_cache(maxsize=None)
def opt_in_attributes(paths: tuple[Path, ...] = (SEMCONV / "gen-ai-spans.yaml", SEMCONV / "mcp-spans.yaml")) -> frozenset[str]:
    """Every attribute a pinned span definition sets as opt-in."""
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, Mapping):
            level = node.get("requirement_level")
            if node.get("ref") and (level == "opt_in" or (isinstance(level, Mapping) and "opt_in" in level)):
                found.add(node["ref"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for path in paths:
        walk(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
    return frozenset(found)


@functools.lru_cache(maxsize=None)
def registry(path: Path = REGISTRY) -> dict[str, dict[str, Any]]:
    """Chapter 5's pinned GenAI registry: attribute key -> its entry."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return {entry["key"]: entry for entry in data["attributes"]}


@functools.lru_cache(maxsize=None)
def content_attributes() -> tuple[str, ...]:
    """The opt-in attributes of chapter 5's registry, sorted; a template attribute keeps its type."""
    missing = opt_in_attributes() - set(registry())
    if missing:
        raise ValueError(f"opt-in in the span definitions but not in chapter 5's registry: {sorted(missing)}")
    return tuple(sorted(opt_in_attributes()))


def is_template(key: str) -> bool:
    return str(registry()[key].get("type", "")).startswith("template[")


@functools.lru_cache(maxsize=None)
def _content_keys() -> tuple[frozenset[str], tuple[str, ...]]:
    exact = frozenset(a for a in content_attributes() if not is_template(a))
    prefixes = tuple(a + "." for a in content_attributes() if is_template(a))
    return exact, prefixes


def is_content(key: str) -> bool:
    """Whether an attribute key is one of the content attributes the Collector drops."""
    exact, prefixes = _content_keys()
    return key in exact or key.startswith(prefixes)


# --- the decisions ------------------------------------------------------------------------------------------

def fnv1a64(data: bytes) -> int:
    value = 0xcbf29ce484222325
    for byte in data:
        value = ((value ^ byte) * 0x100000001b3) & MASK
    return value


@functools.lru_cache(maxsize=None)
def share_threshold(ratio: float) -> int:
    """MaxUint64 times the ratio, rounded to 64 significant bits and truncated, as big.Float does it there."""
    exact = Fraction(MASK) * Fraction(ratio)
    if exact <= 0:
        return 0
    exponent = 0
    while Fraction(2) ** exponent <= exact:
        exponent += 1
    ulp = Fraction(2) ** (exponent - 64)
    units = exact / ulp
    whole = units.numerator // units.denominator
    rest = units - whole
    if rest > Fraction(1, 2) or (rest == Fraction(1, 2) and whole % 2):
        whole += 1
    return min(int(whole * ulp), MASK)


def share_keeps(trace_id: str, salt: str, percent: float) -> bool:
    return fnv1a64(salt.encode("utf-8") + bytes.fromhex(trace_id)) <= share_threshold(percent / 100)


def share_from_tracestate(trace_state: str | None) -> float | None:
    """The share a kept span records: 1 - th / 2**56, from `ot=th:...` in its tracestate."""
    for member in (trace_state or "").split(","):
        key, _, value = member.strip().partition("=")
        if key == "ot" and (match := _TH.search(value)):
            return round(1 - int(match.group(1).ljust(14, "0"), 16) / 2**56, 12)
    return None


def settings(cfg: Mapping[str, Any] | None = None, percent: float | None = None) -> dict[str, Any]:
    cfg = cfg or config()
    policies = {p["name"]: p for p in cfg["processors"]["tail_sampling"]["policies"]}
    share = policies[SHARE]["probabilistic"]
    default = float(str(share["sampling_percentage"]).split(":-")[-1].rstrip("}"))
    return {"threshold_ms": int(policies["slow"]["latency"]["threshold_ms"]), "salt": share["hash_salt"],
            "percent": default if percent is None else percent, "order": [p["name"] for p in cfg["processors"]
                                                                         ["tail_sampling"]["policies"]]}


def features(spans: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """What the policies read from a trace's spans (flat, as fake_otlp writes them), and nothing else."""
    spans = list(spans)
    if not spans:
        return {"spans": 0}

    def flag(key: str) -> bool:
        return any(s["attributes"].get(key) is True or s.get("resource", {}).get(key) is True for s in spans)

    costs = sorted([s["attributes"]["larkspur.workflow"], s["attributes"]["larkspur.cost_usd"]] for s in spans
                   if isinstance(s["attributes"].get("larkspur.workflow"), str)
                   and isinstance(s["attributes"].get("larkspur.cost_usd"), (int, float)))
    return {"spans": len(spans),
            "error": any(s["status"] == "ERROR" or "error.type" in s["attributes"] for s in spans),
            "refused": flag("larkspur.refused"), "fallback": flag("larkspur.fallback"),
            "duration_ms": (max(s["end_ns"] for s in spans) - min(s["start_ns"] for s in spans)) // 1_000_000,
            "costs": costs}


def matched(found: Mapping[str, Any], per_run: Mapping[str, Decimal], threshold_ms: int) -> list[str]:
    """The keep-all policies a trace's features match, in config order."""
    if not found.get("spans"):
        return []
    hits = {"failed": found["error"], "refused": found["refused"], "slow": found["duration_ms"] > threshold_ms,
            "over-budget": any(workflow in per_run and Decimal(str(cost)) >= per_run[workflow]
                               for workflow, cost in found["costs"]),
            "fallback": found["fallback"]}
    return [name for name in KEEP_ALL if hits[name]]


def decide(trace_id: str, found: Mapping[str, Any], *, per_run: Mapping[str, Decimal],
           threshold_ms: int, salt: str, percent: float) -> dict[str, Any]:
    """What the tail sampler should decide for one trace: kept, the policy it records, and the share."""
    keep_all = matched(found, per_run, threshold_ms)
    by_share = share_keeps(trace_id, salt, percent)
    if keep_all:
        return {"kept": True, "policy": keep_all[0], "share": 1.0, "matched": keep_all, "share_keeps": by_share}
    if by_share:
        return {"kept": True, "policy": SHARE, "share": min(percent / 100, 1.0), "matched": [], "share_keeps": True}
    return {"kept": False, "policy": None, "share": None, "matched": [], "share_keeps": False}
