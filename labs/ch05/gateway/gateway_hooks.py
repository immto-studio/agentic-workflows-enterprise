"""The gateway's own rules: a pre-call decision, limits, a cost line and a span, as a LiteLLM callback.

Chapter 5, part 3. LiteLLM routes and falls back on its own (see `litellm.config.yaml`). What the
book asks of a model gateway beyond that is not configuration, and lives here.

The rules are pure functions in gateway_rules.py; this file is the LiteLLM glue.

1. The manifest. Every request carries `workflow:<name>` and `data_class:<class>` tags and a
   `trace_id` in its metadata. The workflow must have a manifest (labs/ch05/manifest), the alias
   must be one of the manifest's models, and the data class must not exceed its maximum.
2. The data-class grid of chapter 2, applied to where each deployment actually serves. The config
   declares every deployment's Region, jurisdiction and hosting in `model_info`; `may_receive`
   reads chapter 2's rows against that. Every deployment behind the requested alias must pass, and
   must sit in a Region the manifest allows, or the request is refused. The same test runs on
   every hop of the alias's fallback chain. A hop that fails it does not refuse the request; the
   request runs with fallbacks disabled, so a failover can never carry a prompt somewhere it could
   not have been sent directly. Fallback fields in the request body (`fallbacks` and its
   relatives) are removed first: the chain the rules checked is the only one the router gets.
3. Limits from the manifest: a budget per run (summed by trace id from the cost LiteLLM computes)
   and, when the manifest sets one, requests per minute per workflow. Both fail closed with a 429.
   Both keep their state in this process, so two gateway pods mean two budgets; a fleet keeps the
   counters in Redis, which is one reason chapter 5 calls the gateway a tier-0 service.
4. A cost line per call: trace id, workflow, data class, alias asked for, alias and deployment
   that served it, Region, whether it was a fallback, model, tokens, cost and latency.
5. A `chat <alias>` span per call with the request's trace context (a `traceparent` in the
   metadata wins, else the bare trace id), the serving model and the Region. The span comes from
   a tracer provider of its own, so LiteLLM's HTTP spans neither become its parent nor end up in
   the lab's trace file.

What the callback cannot see: LiteLLM's pass-through routes (`/vllm/...`, `/anthropic/...` and
the like) forward a request to a configured deployment without calling the pre-call hook. In
front of a real gateway, the ingress forwards only the chat and health routes.

What this does not do: check that the caller is the workflow it says it is. Behind one master key
any caller can write any tag, including `data_class:public` on a prompt full of claim numbers.
Binding a workflow and its maximum data class to a key needs LiteLLM's database (virtual keys)
or its enterprise JWT auth; chapter 5 says what Larkspur did about it.

Environment: GATEWAY_LOG_FILE (default labs/ch05/gateway.log), GATEWAY_CONFIG (the LiteLLM config
to read destinations and fallbacks from; default the one next to this file), MANIFEST_DIR
(default labs/ch05/manifest), TRACE_FILE / OTEL_EXPORTER_OTLP_ENDPOINT (tracing/trace_setup.py).
"""

from __future__ import annotations

import atexit
import json
import os
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from litellm.integrations.custom_logger import CustomLogger
from opentelemetry.trace import SpanKind

HERE = Path(__file__).resolve().parent
LAB = HERE.parent
# LiteLLM loads this file by path, so its neighbours are put on the path explicitly.
for folder in (HERE, LAB / "manifest", LAB / "tracing"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import manifest as manifests  # noqa: E402
import trace_setup as tracing  # noqa: E402
from gateway_rules import (  # noqa: E402
    CLIENT_ROUTING_FIELDS, Limits, decide, describe, guardrail_verdicts, parse_tags, read_config,
    set_cache_salt,
)

LOG_PATH = Path(os.environ.get("GATEWAY_LOG_FILE") or LAB / "gateway.log")
CONFIG_PATH = Path(os.environ.get("GATEWAY_CONFIG") or HERE / "litellm.config.yaml")
MANIFEST_DIR = Path(os.environ.get("MANIFEST_DIR") or LAB / "manifest")


# --- logging and tracing --------------------------------------------------------------------------

def _json_line(**fields: Any) -> None:
    record = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), **fields}
    with LOG_PATH.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record) + "\n")


def _ns(moment: Any) -> int | None:
    return int(moment.timestamp() * 1e9) if isinstance(moment, datetime) else None


_tracer: Any = None


def _gateway_tracer() -> Any:
    """A tracer on the gateway's own provider, built once. The global provider is left alone."""
    global _tracer
    if _tracer is None:
        setup = tracing.build_provider("gateway")
        atexit.register(setup.provider.shutdown)
        _tracer = setup.provider.get_tracer(tracing.INSTRUMENTATION_NAME)
    return _tracer


def _span(info: Mapping[str, Any], start_time: Any, end_time: Any, error: str | None = None) -> None:
    """One `chat <alias>` span in the caller's trace, with the call's real start and end."""
    if not isinstance(info.get("trace_id"), str):
        return
    attributes = {
        tracing.GEN_AI_OPERATION_NAME: tracing.OP_CHAT,
        tracing.GEN_AI_REQUEST_MODEL: info.get("requested_alias"),
        tracing.GEN_AI_RESPONSE_MODEL: info.get("served_model"),
        tracing.GEN_AI_USAGE_INPUT_TOKENS: info.get("prompt_tokens"),
        tracing.GEN_AI_USAGE_OUTPUT_TOKENS: info.get("completion_tokens"),
        tracing.LARKSPUR_COMPONENT: "gateway",
        tracing.LARKSPUR_TRACE_ID: info["trace_id"],
        tracing.ERROR_TYPE: error,
        "larkspur.workflow": info.get("workflow"),
        "larkspur.data_class": info.get("data_class"),
        "larkspur.served_alias": info.get("served_alias"),
        "larkspur.deployment": info.get("deployment"),
        "larkspur.region": info.get("region"),
        "larkspur.fallback": info.get("fallback"),
        "larkspur.cost_usd": info.get("cost_usd"),
    }
    span = tracing.open_span(f"{tracing.OP_CHAT} {info.get('requested_alias')}", kind=SpanKind.CLIENT,
                             traceparent=info.get("traceparent"), trace_id=info["trace_id"],
                             start_time=_ns(start_time), attributes=attributes,
                             use_tracer=_gateway_tracer(), ignore_current=True)
    span.end(end_time=_ns(end_time))


class GatewayHooks(CustomLogger):
    def __init__(self) -> None:
        super().__init__()
        self.manifests = manifests.load_manifests(MANIFEST_DIR)
        self.destinations, self.fallbacks = read_config(CONFIG_PATH)
        self.limits = Limits()

    async def async_pre_call_hook(self, user_api_key_dict: Any, cache: Any, data: dict,
                                  call_type: str) -> dict | None:
        metadata = data.get("metadata") or {}
        removed = [field for field in CLIENT_ROUTING_FIELDS if data.pop(field, None) is not None]
        tags = parse_tags(metadata)
        alias = data.get("model", "")
        trace_id = metadata.get("trace_id")
        decision = decide(alias, tags, trace_id, self.manifests, self.destinations, self.fallbacks)
        if decision.refused:
            _json_line(event="refused", alias=alias, trace_id=trace_id, tags=tags, reason=decision.refused)
            raise HTTPException(status_code=400, detail=decision.refused)
        over = self.limits.check(tags["workflow"], trace_id, self.manifests[tags["workflow"]])
        if over:
            _json_line(event="refused", alias=alias, trace_id=trace_id, tags=tags, reason=over)
            raise HTTPException(status_code=429, detail=over)
        if removed:
            _json_line(event="routing_override_removed", alias=alias, trace_id=trace_id, fields=removed)
        # Both set on every request, so neither can be supplied by the caller.
        data["disable_fallbacks"] = bool(decision.no_fallback)
        metadata["fallbacks_disabled"] = bool(decision.no_fallback)
        if decision.no_fallback:
            _json_line(event="fallback_disabled", alias=alias, trace_id=trace_id, tags=tags,
                       reason=decision.no_fallback)
        set_cache_salt(data, tags["workflow"], self.destinations.get(alias, []))
        metadata["requested_alias"] = alias  # carried to the callbacks, through any failover
        data["metadata"] = metadata
        return data

    async def async_log_success_event(self, kwargs: dict, response_obj: Any,
                                      start_time: Any, end_time: Any) -> None:
        info = describe(kwargs)
        usage = getattr(response_obj, "usage", None)
        cost = kwargs.get("response_cost")
        cost = round(cost, 8) if isinstance(cost, (int, float)) else None
        info |= {"prompt_tokens": getattr(usage, "prompt_tokens", None),
                 "completion_tokens": getattr(usage, "completion_tokens", None), "cost_usd": cost}
        if verdicts := guardrail_verdicts(kwargs):
            info["guardrails"] = verdicts
        self.limits.record(info["trace_id"], cost)
        latency = (int((end_time - start_time).total_seconds() * 1000)
                   if isinstance(start_time, datetime) and isinstance(end_time, datetime) else None)
        _json_line(event="call", **{k: v for k, v in info.items() if k != "traceparent"}, latency_ms=latency)
        _span(info, start_time, end_time)

    async def async_log_failure_event(self, kwargs: dict, response_obj: Any,
                                      start_time: Any, end_time: Any) -> None:
        exc = kwargs.get("exception")
        if exc is not None and "request refused" in str(exc):
            return  # our own pre-call refusal; it is already logged as a `refused` line
        info = describe(kwargs)
        if verdicts := guardrail_verdicts(kwargs):  # a guardrail that blocked lands here
            info["guardrails"] = verdicts
        error = type(exc).__name__ if exc is not None else "error"
        _json_line(event="failed", **{k: v for k, v in info.items() if k != "traceparent"},
                   error=error, message=str(exc)[:200] if exc is not None else None)
        _span(info, start_time, end_time, error=error)


hooks = GatewayHooks()
