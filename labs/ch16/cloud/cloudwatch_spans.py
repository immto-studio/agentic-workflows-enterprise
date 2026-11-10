"""What CloudWatch shows of the run, and when: the spans in aws/spans, the indexed traces, the services (item 2).

With Transaction Search on, every span the Collector sends to X-Ray's OTLP endpoint lands in the `aws/spans` log
group (fact sheet 8.2). This polls the group for the run's trace ids, records when each trace's first span appeared
and when every span the Collector sent was there, counted against what left the Collector, and then reads what
else CloudWatch made of them: the shape of one record (the fact sheet found no page naming the field that holds
the trace id), X-Ray's indexed trace summaries for the window (the Default indexing rule's share), Application
Signals' service list, and one Logs Insights query over the group with its statistics.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import cloud_session  # noqa: E402

GROUP = "aws/spans"


def fetch_events(logs: Any, group: str, start_ms: int) -> list[dict[str, Any]]:
    """Every event in the group since `start_ms`, its message parsed."""
    out: list[dict[str, Any]] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"logGroupName": group, "startTime": start_ms, "interleaved": True}
        if token:
            kwargs["nextToken"] = token
        try:
            page = logs.filter_log_events(**kwargs)
        except logs.exceptions.ResourceNotFoundException:
            return out
        for event in page.get("events", []):
            try:
                message = json.loads(event["message"])
            except json.JSONDecodeError:
                message = {"raw": event["message"][:300]}
            out.append({"timestamp_ms": event["timestamp"], "ingestion_ms": event.get("ingestionTime"), "message": message})
        token = page.get("nextToken")
        if not token:
            return out


def find_trace_id(value: Any, trace_ids: Iterable[str], path: str = "") -> tuple[str, str] | None:
    """The first string among `trace_ids` in the record, with the dotted path that held it."""
    wanted = set(trace_ids)
    if isinstance(value, str):
        return (value, path) if value in wanted else None
    if isinstance(value, Mapping):
        for key, inner in value.items():
            found = find_trace_id(inner, wanted, f"{path}.{key}" if path else str(key))
            if found:
                return found
    if isinstance(value, list):
        for index, inner in enumerate(value):
            found = find_trace_id(inner, wanted, f"{path}[{index}]")
            if found:
                return found
    return None


def count_by_trace(events: list[dict[str, Any]], trace_ids: Iterable[str]) -> tuple[dict[str, list[dict[str, Any]]], str | None]:
    wanted = set(trace_ids)
    by_trace: dict[str, list[dict[str, Any]]] = {}
    key_path = None
    for event in events:
        found = find_trace_id(event["message"], wanted)
        if found:
            by_trace.setdefault(found[0], []).append(event)
            key_path = key_path or found[1]
    return by_trace, key_path


def shape(message: Mapping[str, Any]) -> dict[str, Any]:
    return {"keys": sorted(message.keys()),
            "nested_keys": {k: sorted(v.keys()) for k, v in message.items() if isinstance(v, Mapping)}}


def poll(s: Any, expected: Mapping[str, int], since: float, sink_times: Mapping[str, float], *,
         limit: float = 1200.0, every: float = 15.0, group: str = GROUP) -> dict[str, Any]:
    """Poll the group until every trace has every span, or the limit; what each reading saw is kept."""
    logs = s.client("logs")
    clock = cloud_session.Clock()
    since_ms = int((since - 120) * 1000)
    first_seen: dict[str, dict[str, Any]] = {}
    complete: dict[str, dict[str, Any]] = {}
    readings: list[dict[str, Any]] = []
    key_path, sample, events = None, None, []
    group_seen_s = None
    while True:
        groups = logs.describe_log_groups(logGroupNamePrefix=group).get("logGroups", [])
        exists = any(g["logGroupName"] == group for g in groups)
        if exists and group_seen_s is None:
            group_seen_s = clock.seconds()
        events = fetch_events(logs, group, since_ms) if exists else []
        by_trace, path = count_by_trace(events, expected)
        key_path = key_path or path
        now = time.time()
        for trace_id, items in by_trace.items():
            if trace_id not in first_seen:
                earliest = min(items, key=lambda e: e["timestamp_ms"])
                first_seen[trace_id] = {"seconds": clock.seconds(),
                                        "after_sink_s": round(now - sink_times[trace_id], 1) if trace_id in sink_times else None,
                                        "ingestion_minus_span_ms": (earliest["ingestion_ms"] or 0) - earliest["timestamp_ms"]}
            if trace_id not in complete and len(items) >= expected[trace_id]:
                complete[trace_id] = {"seconds": clock.seconds(), "spans": len(items),
                                      "after_sink_s": round(now - sink_times[trace_id], 1) if trace_id in sink_times else None}
            if sample is None:
                sample = items[0]["message"]
        readings.append({"seconds": clock.seconds(), "group_exists": exists, "events": len(events),
                         "traces_seen": len(by_trace), "traces_complete": len(complete)})
        if len(complete) == len(expected) or clock.seconds() > limit:
            break
        time.sleep(every)
    by_trace, _ = count_by_trace(events, expected)
    end = datetime.now(timezone.utc)
    start = datetime.fromtimestamp(since - 120, tz=timezone.utc)
    record: dict[str, Any] = {
        "group": group, "clock": cloud_session.CLOCK, "started": clock.started, "polled_s": clock.seconds(),
        "group_seen_after_s": group_seen_s, "readings": readings, "trace_id_key": key_path,
        "record_shape": shape(sample) if sample else None, "sample_record": sample,
        "spans_expected": dict(expected), "spans_found": {t: len(v) for t, v in by_trace.items()},
        "traces_expected": len(expected), "traces_seen": len(by_trace), "traces_complete": len(complete),
        "first_seen": first_seen, "complete": complete,
        "events_not_ours": sum(1 for e in events if not find_trace_id(e["message"], expected)),
    }
    record["xray"] = trace_summaries(s.client("xray"), start, end, expected)
    record["application_signals"] = services(s, start, end)
    record["insights"] = insights_query(logs, group, key_path, expected, start, end)
    return record


def trace_summaries(xray: Any, start: datetime, end: datetime, trace_ids: Iterable[str]) -> dict[str, Any]:
    """X-Ray's indexed trace summaries in the window: the share the Default rule indexed."""
    wanted = set(trace_ids)
    summaries: list[dict[str, Any]] = []
    try:
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"StartTime": start, "EndTime": end, "Sampling": False}
            if token:
                kwargs["NextToken"] = token
            page = xray.get_trace_summaries(**kwargs)
            summaries += page.get("TraceSummaries", [])
            token = page.get("NextToken")
            if not token:
                break
        rules = xray.get_indexing_rules().get("IndexingRules", [])
    except Exception as exc:
        return {"ok": False, **cloud_session.aws_error(exc)}
    ours = [s for s in summaries if s.get("Id") in wanted]
    return {"ok": True, "summaries_in_window": len(summaries), "ours_indexed": len(ours),
            "ours_ids": sorted(s["Id"] for s in ours),
            "indexing_percent": next(((r.get("Rule") or {}).get("Probabilistic", {}).get("DesiredSamplingPercentage")
                                      for r in rules if r.get("Name") == "Default"), None),
            "sample": {k: v for k, v in ours[0].items() if k in ("Id", "Duration", "ResponseTime", "HasError", "HasFault")} if ours else None}


def services(s: Any, start: datetime, end: datetime) -> dict[str, Any]:
    """Application Signals' service list for the window: whether the lab's three processes appear in it."""
    try:
        page = s.client("application-signals").list_services(StartTime=start, EndTime=end)
    except Exception as exc:
        return {"ok": False, **cloud_session.aws_error(exc)}
    names = sorted((item.get("KeyAttributes") or {}).get("Name", "?") for item in page.get("ServiceSummaries", []))
    return {"ok": True, "services": names}


def insights_query(logs: Any, group: str, key_path: str | None, trace_ids: Iterable[str], start: datetime,
                   end: datetime) -> dict[str, Any]:
    """One Logs Insights query over aws/spans for the run's traces, with the statistics CloudWatch bills on."""
    if not key_path:
        return {"ok": False, "why": "no record held one of the run's trace ids, so the field is unknown"}
    ids = ", ".join(f'"{t}"' for t in sorted(trace_ids))
    query = f"fields @timestamp | filter {key_path} in [{ids}] | stats count(*) as spans by {key_path}"
    try:
        started = logs.start_query(logGroupName=group, startTime=int(start.timestamp()), endTime=int(end.timestamp()),
                                   queryString=query, limit=1000)
        for _ in range(60):
            answer = logs.get_query_results(queryId=started["queryId"])
            if answer.get("status") in ("Complete", "Failed", "Cancelled", "Timeout"):
                break
            time.sleep(2)
    except Exception as exc:
        return {"ok": False, "query": query, **cloud_session.aws_error(exc)}
    rows = [{f["field"]: f["value"] for f in row} for row in answer.get("results", [])]
    return {"ok": answer.get("status") == "Complete", "query": query, "status": answer.get("status"),
            "rows": len(rows), "spans_by_trace": {r.get(key_path): int(r.get("spans", 0)) for r in rows},
            "statistics": answer.get("statistics")}
