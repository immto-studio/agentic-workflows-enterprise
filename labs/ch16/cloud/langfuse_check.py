"""What Langfuse made of the run, read through the tunnel: the traces, the observations, the tokens, the cost.

Step 7, item 7 (O-D4, amended). The Collector's Langfuse exporter sends OTLP/HTTP with basic auth and the
`x-langfuse-ingestion-version: 4` header (fact sheet 8.5). This polls Langfuse's public API for the run's trace
ids until every kept span has an observation, or the limit, and records the delay; then it compares, trace by
trace, what Langfuse holds with what the Collector kept: the observations against the spans, by span id; on the
gateway's `chat` spans, Langfuse's usage and cost against the span's token counts and `gen_ai.usage.cost`, which
the Collector copies from `larkspur.cost_usd` on this pipeline alone (step 3); and whether the tracestate that
carries the sampling share survives anywhere.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import cloud_session  # noqa: E402


def client(base: str, public_key: str, secret_key: str) -> httpx.Client:
    return httpx.Client(base_url=base, auth=(public_key, secret_key), timeout=30.0)


def health(c: httpx.Client) -> dict[str, Any]:
    try:
        answer = c.get("/api/public/health")
        return {"ok": answer.status_code == 200, "status": answer.status_code, "body": answer.json() if answer.status_code == 200 else answer.text[:200]}
    except httpx.HTTPError as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}


FIELDS = "core,basic,time,io,metadata,model,usage,metrics,trace_context"  # the v2 route's field groups (its served spec)


def observations(c: httpx.Client, trace_id: str, fields: str | None = None) -> list[dict[str, Any]]:
    """One trace's observations from the v2 route, following its cursor; `fields` asks for more than the core
    and basic groups the route returns by default (usage, cost, model, metadata, input and output)."""
    out: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(50):
        params: dict[str, Any] = {"traceId": trace_id, "limit": 100}
        if fields:
            params["fields"] = fields
        if cursor:
            params["cursor"] = cursor
        answer = c.get("/api/public/v2/observations", params=params)
        answer.raise_for_status()
        body = answer.json()
        out += body.get("data", [])
        cursor = (body.get("meta") or {}).get("cursor")
        if not cursor:
            return out
    return out


def trace(c: httpx.Client, trace_id: str) -> dict[str, Any] | None:
    answer = c.get(f"/api/public/traces/{trace_id}")
    return answer.json() if answer.status_code == 200 else None


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def compare(spans_by_trace: Mapping[str, list[dict[str, Any]]],
            obs_by_trace: Mapping[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Trace by trace, what Langfuse holds against what the Collector kept."""
    rows = []
    cost_rows = []
    for trace_id, spans in sorted(spans_by_trace.items()):
        obs = obs_by_trace.get(trace_id, [])
        span_ids = {s["span_id"] for s in spans}
        obs_ids = {o.get("id") for o in obs}
        same = span_ids & obs_ids
        types = {}
        for o in obs:
            types[o.get("type")] = types.get(o.get("type"), 0) + 1
        rows.append({"trace_id": trace_id, "spans_kept": len(spans), "observations": len(obs),
                     "same_span_ids": len(same), "observation_types": types,
                     "root_observations": sum(1 for o in obs if not o.get("parentObservationId"))})
        for span in spans:
            # The span file holds the gateway's own attribute; the Collector copies it into gen_ai.usage.cost on
            # the Langfuse pipeline alone (step 3), so Langfuse's cost is compared with larkspur.cost_usd.
            cost = span["attributes"].get("larkspur.cost_usd", span["attributes"].get("gen_ai.usage.cost"))
            if cost is None:
                continue
            match = next((o for o in obs if o.get("id") == span["span_id"]), None)
            usage = (match or {}).get("usageDetails") or {}
            costs = (match or {}).get("costDetails") or {}
            total_cost = _number(costs.get("total")) if costs else _number((match or {}).get("totalCost"))
            span_tokens = [span["attributes"].get("gen_ai.usage.input_tokens"), span["attributes"].get("gen_ai.usage.output_tokens")]
            langfuse_tokens = [usage.get("input"), usage.get("output")]
            cost_rows.append({
                "trace_id": trace_id, "span": span["name"], "found": match is not None,
                "type": (match or {}).get("type"), "model": (match or {}).get("model"),
                "span_cost": cost, "langfuse_cost": total_cost,
                "cost_equal": total_cost is not None and abs(total_cost - float(cost)) < 1e-9,
                "span_tokens": span_tokens, "langfuse_tokens": langfuse_tokens,
                "tokens_equal": langfuse_tokens == span_tokens and span_tokens != [None, None],
            })
    everything = json.dumps(list(obs_by_trace.values()))
    return {"traces": rows, "gateway_spans_with_cost": cost_rows,
            "traces_with_every_span": sum(1 for r in rows if r["same_span_ids"] == r["spans_kept"] and r["spans_kept"] > 0),
            "cost_read_from_gen_ai_usage_cost": sum(1 for r in cost_rows if r["cost_equal"]),
            "cost_rows": len(cost_rows),
            "tracestate_anywhere": "ot=th:" in everything or "tracestate" in everything.lower(),
            "span_attributes_kept_as_metadata": any("larkspur.workflow" in json.dumps(o.get("metadata") or {})
                                                     for obs in obs_by_trace.values() for o in obs)}


def poll(base: str, public_key: str, secret_key: str, expected: Mapping[str, int],
         spans_by_trace: Mapping[str, list[dict[str, Any]]], sink_times: Mapping[str, float], *,
         limit: float = 900.0, every: float = 15.0) -> dict[str, Any]:
    clock = cloud_session.Clock()
    with client(base, public_key, secret_key) as c:
        record: dict[str, Any] = {"base": base, "clock": cloud_session.CLOCK, "started": clock.started, "health": health(c)}
        first_seen: dict[str, dict[str, Any]] = {}
        complete: dict[str, dict[str, Any]] = {}
        obs_by_trace: dict[str, list[dict[str, Any]]] = {}
        readings = []
        errors: list[str] = []
        while True:
            now = time.time()
            for trace_id, wanted in expected.items():
                if trace_id in complete:
                    continue
                try:
                    obs = observations(c, trace_id)
                except httpx.HTTPError as exc:
                    errors.append(f"{type(exc).__name__}: {exc}"[:200])
                    continue
                obs_by_trace[trace_id] = obs
                if obs and trace_id not in first_seen:
                    first_seen[trace_id] = {"seconds": clock.seconds(),
                                            "after_sink_s": round(now - sink_times[trace_id], 1) if trace_id in sink_times else None}
                if len(obs) >= wanted:
                    complete[trace_id] = {"seconds": clock.seconds(), "observations": len(obs),
                                          "after_sink_s": round(now - sink_times[trace_id], 1) if trace_id in sink_times else None}
            readings.append({"seconds": clock.seconds(), "traces_seen": len(first_seen), "traces_complete": len(complete)})
            if len(complete) == len(expected) or clock.seconds() > limit:
                break
            time.sleep(every)
        sample_trace = next((trace(c, t) for t in sorted(complete)), None)
    record |= {"polled_s": clock.seconds(), "readings": readings, "errors": errors[:10],
               "traces_expected": len(expected), "traces_seen": len(first_seen), "traces_complete": len(complete),
               "first_seen": first_seen, "complete": complete, "comparison": compare(spans_by_trace, obs_by_trace),
               "sample_trace_keys": sorted(sample_trace.keys()) if sample_trace else None,
               "sample_observation": next((o for obs in obs_by_trace.values() for o in obs if o.get("type") == "GENERATION"), None)
               or next((o for obs in obs_by_trace.values() for o in obs), None),
               "observations": obs_by_trace}
    return record
