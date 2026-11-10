"""The model gateway's rules as pure functions: no LiteLLM, no network, no files except the config.

Chapter 5, part 3. gateway_hooks.py calls these from inside the LiteLLM proxy; the unit tests in
tests/test_gateway_rules.py call them directly. What each rule does and why is in the docstring
of gateway_hooks.py.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

import manifest as manifests

HOME_JURISDICTION = "CA"  # where the lab's data belongs; a multi-country platform tags it per request
REQUIRED_TAGS = ("workflow", "data_class")
# Request-body fields with which a caller could steer LiteLLM's router around the checked chain.
# The hook removes them; the gateway's own config is the only source of fallbacks.
CLIENT_ROUTING_FIELDS = ("fallbacks", "context_window_fallbacks", "content_policy_fallbacks",
                         "default_fallbacks", "router_settings_override", "model_group_alias")
# Every kind of fallback the config can declare, in either section; all of them are a way out.
FALLBACK_KEYS = ("fallbacks", "context_window_fallbacks", "content_policy_fallbacks")


# --- where each alias serves, and what it may receive -----------------------------------------

@dataclass(frozen=True)
class Destination:
    alias: str
    deployment: str
    region: str
    jurisdiction: str
    hosting: str  # "managed" or "self-hosted"
    # Every Region the deployment can serve a request from, when that isn't only `region`: a
    # cross-Region profile is called in one Region and served from any of its destinations.
    serves_from: tuple[str, ...] = ()

    @property
    def regions(self) -> tuple[str, ...]:
        return self.serves_from or (self.region,)


def read_config(path: Path) -> tuple[dict[str, list[Destination]], dict[str, list[str]]]:
    """(alias -> its deployments, alias -> its fallback aliases), from the LiteLLM config."""
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return {}, {}
    destinations: dict[str, list[Destination]] = defaultdict(list)
    for entry in config.get("model_list") or []:
        info = entry.get("model_info") or {}
        destinations[entry["model_name"]].append(Destination(
            alias=entry["model_name"], deployment=str(info.get("id", "")),
            region=str(info.get("region", "unknown")), jurisdiction=str(info.get("jurisdiction", "unknown")),
            hosting=str(info.get("hosting", "unknown")),
            serves_from=tuple(str(r) for r in info.get("serves_from") or ())))
    fallbacks: dict[str, list[str]] = {}
    for section in ("litellm_settings", "router_settings"):
        settings = config.get(section) or {}
        for key in FALLBACK_KEYS:
            for item in settings.get(key) or []:
                for alias, targets in item.items():
                    fallbacks.setdefault(alias, []).extend(targets)
        for target in settings.get("default_fallbacks") or []:  # applies to every alias
            fallbacks.setdefault("*", []).append(target)
    return dict(destinations), fallbacks


def may_receive(data_class: str, dest: Destination,
                home: str = HOME_JURISDICTION) -> bool:
    """Chapter 2's grid, read by row, for one deployment.

    Public goes anywhere. Internal may cross regions because the gateway logs the serving Region.
    Confidential stays in the jurisdiction. Restricted goes to a self-hosted model in the
    jurisdiction; the per-workflow signature chapter 2 allows for a managed endpoint is not
    modelled here, and such a workflow would get its own alias.
    """
    in_jurisdiction = dest.jurisdiction == home
    hosted = dest.hosting in {"managed", "self-hosted"}
    return {
        "public": True,
        "internal": hosted,
        "confidential": in_jurisdiction and hosted,
        "restricted": in_jurisdiction and dest.hosting == "self-hosted",
    }.get(data_class, False)


def chain(alias: str, fallbacks: Mapping[str, list[str]]) -> list[str]:
    """The alias and every alias a failover could reach from it, in order, without repeats.

    A "*" entry (LiteLLM's wildcard, and `default_fallbacks`) applies to every alias.
    """
    seen: list[str] = []
    queue = [alias]
    while queue:
        current = queue.pop(0)
        if current not in seen:
            seen.append(current)
            queue.extend(fallbacks.get(current, []) + fallbacks.get("*", []))
    return seen


def _blocked(alias: str, data_class: str, manifest: Mapping[str, Any],
             destinations: Mapping[str, list[Destination]]) -> str | None:
    """Why this alias may not take this request, or None."""
    deployments = destinations.get(alias)
    if not deployments:
        return f"{alias!r} is not a gateway alias"
    for dest in deployments:
        if not may_receive(data_class, dest):
            return (f"data class {data_class!r} may not go to {alias!r} "
                    f"({dest.hosting}, {dest.region}, {dest.jurisdiction})")
        outside = [r for r in dest.regions if r not in manifest["regions"]]
        if outside:
            return f"{alias!r} serves from {outside[0]}, outside the regions of {manifest['workflow']!r}"
    return None


@dataclass(frozen=True)
class Decision:
    refused: str | None = None       # the request may not leave; the reason
    no_fallback: str | None = None   # it may leave but must not fail over; the reason


def decide(alias: str, tags: Mapping[str, str], trace_id: str | None,
           known: Mapping[str, Mapping[str, Any]],
           destinations: Mapping[str, list[Destination]],
           fallbacks: Mapping[str, list[str]]) -> Decision:
    """The pre-call decision, as a pure function. Reads metadata only, never the prompt.

    The manifest's `models` lists the aliases a workflow may ask for. A fallback alias is reached
    only through the router, and is checked by grid and Region rather than by that list.
    """
    has_trace = isinstance(trace_id, str) and bool(trace_id.strip())
    missing = [t for t in REQUIRED_TAGS if t not in tags] + ([] if has_trace else ["trace_id"])
    if missing:
        return Decision(refused=f"request refused: missing {', '.join(missing)} in metadata")
    workflow, data_class = tags["workflow"], tags["data_class"]
    manifest = known.get(workflow)
    if manifest is None:
        return Decision(refused=f"request refused: no manifest for workflow {workflow!r}")
    if alias not in manifest["models"]:
        return Decision(refused=f"request refused: {alias!r} is not a model in the manifest of {workflow!r}")
    if data_class not in manifests.DATA_CLASSES:
        return Decision(refused=f"request refused: unknown data class {data_class!r}")
    if manifests.rank(data_class) > manifests.rank(manifest["data_class_max"]):
        return Decision(refused=f"request refused: data class {data_class!r} is above the maximum "
                                f"of {workflow!r} ({manifest['data_class_max']!r})")
    reason = _blocked(alias, data_class, manifest, destinations)
    if reason:
        return Decision(refused=f"request refused: {reason}")
    for hop in chain(alias, fallbacks)[1:]:
        reason = _blocked(hop, data_class, manifest, destinations)
        if reason:
            return Decision(no_fallback=f"fallback to {hop!r} disabled "
                                        f"for this request: {reason}")
    return Decision()


# --- guardrail verdicts --------------------------------------------------------------------------

# What a guardrail finding may put in a log line. Bedrock's findings also name what matched
# ("match", "regex"), which can be the very text the filter exists to keep out of logs.
FINDING_FIELDS = ("type", "name", "action", "detected", "confidence")


def guardrail_verdicts(kwargs: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Each guardrail's verdict on one call, for the call's log line: never the text it matched.

    LiteLLM keeps every guardrail's response in the standard logging payload. For Amazon Bedrock
    Guardrails that is ApplyGuardrail's response, whose `assessments` hold one list of findings
    per policy. In detect mode the action is NONE and nothing is blocked, so this line is where the
    findings go: the gateway's log, the collector, security engineering's queue.
    """
    payload = kwargs.get("standard_logging_object")
    infos = payload.get("guardrail_information") if isinstance(payload, Mapping) else None
    if isinstance(infos, Mapping):
        infos = [infos]
    verdicts = []
    for info in infos if isinstance(infos, list) else []:
        if not isinstance(info, Mapping):
            continue
        response = info.get("guardrail_response")
        response = response if isinstance(response, Mapping) else {}
        findings = []
        for assessment in response.get("assessments") or []:
            for policy, body in assessment.items() if isinstance(assessment, Mapping) else ():
                for entries in body.values() if isinstance(body, Mapping) else ():
                    findings += [{"policy": policy, **{k: e[k] for k in FINDING_FIELDS if k in e}}
                                 for e in (entries if isinstance(entries, list) else []) if isinstance(e, Mapping)]
        verdicts.append({"guardrail": info.get("guardrail_name"), "status": info.get("guardrail_status"),
                         "action": response.get("action"), "findings": findings})
    return verdicts


# --- limits -------------------------------------------------------------------------------------

class Limits:
    """Per-run budget and per-workflow request rate, in this process's memory.

    The budget is checked before a call and charged after it, from the cost LiteLLM computes, so a
    run can overshoot by the calls it has in flight at the moment it crosses the line.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.spent: dict[str, float] = defaultdict(float)        # trace id -> USD
        self.recent: dict[str, deque[float]] = defaultdict(deque)  # workflow -> request times

    def check(self, workflow: str, trace_id: str, manifest: Mapping[str, Any]) -> str | None:
        budget = manifest["budget"]
        if self.spent[trace_id] >= budget["per_run_usd"]:
            return (f"request refused: run {trace_id} has spent ${self.spent[trace_id]:.4f} of its "
                    f"${budget['per_run_usd']:.2f} budget")
        limit = budget.get("requests_per_minute")
        if limit:
            now, window = self.clock(), self.recent[workflow]
            while window and now - window[0] >= 60:
                window.popleft()
            if len(window) >= limit:
                return f"request refused: {workflow!r} is over {limit} requests per minute"
            window.append(now)
        return None

    def record(self, trace_id: str | None, cost: float | None) -> None:
        if trace_id and cost:
            self.spent[trace_id] += cost


# --- what the gateway adds to a request -----------------------------------------------------------

def set_cache_salt(data: dict, workflow: str, destinations: list[Destination]) -> None:
    """One prefix cache per workflow on self-hosted replicas, chosen by the gateway, never the caller.

    vLLM reuses cached prompt prefixes across requests; a `cache_salt` keeps one workflow's cached
    prefixes from serving another's. Any salt the caller sent is removed. The salt is added only
    when every deployment behind the alias is self-hosted, so it never reaches a managed provider.
    """
    data.pop("cache_salt", None)
    extra = {k: v for k, v in (data.get("extra_body") or {}).items() if k != "cache_salt"}
    if destinations and all(d.hosting == "self-hosted" for d in destinations):
        extra["cache_salt"] = workflow
    if extra:
        data["extra_body"] = extra
    else:
        data.pop("extra_body", None)


# --- reading a request ----------------------------------------------------------------------------

def parse_tags(metadata: Mapping[str, Any]) -> dict[str, str]:
    """`tags: ["workflow:w2", "data_class:internal"]` -> {"workflow": "w2", "data_class": "internal"}."""
    out: dict[str, str] = {}
    for tag in metadata.get("tags") or []:
        if isinstance(tag, str) and ":" in tag:
            key, value = tag.split(":", 1)
            out[key] = value
    return out


def describe(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    """What the cost line and the span need, from the kwargs LiteLLM passes to a callback."""
    params = kwargs.get("litellm_params") or {}
    metadata = params.get("metadata") or {}
    tags = parse_tags(metadata)
    model_info = metadata.get("model_info") or params.get("model_info") or {}
    served_alias = metadata.get("model_group") or kwargs.get("model")
    requested = metadata.get("requested_alias") or served_alias
    return {
        "trace_id": metadata.get("trace_id"),
        "traceparent": metadata.get("traceparent"),
        "workflow": tags.get("workflow"),
        "data_class": tags.get("data_class"),
        "requested_alias": requested,
        "served_alias": served_alias,
        "fallback": bool(requested and served_alias and requested != served_alias),
        "fallbacks_disabled": bool(metadata.get("fallbacks_disabled")),
        "deployment": model_info.get("id"),
        "region": model_info.get("region"),
        "served_model": kwargs.get("model"),
    }
