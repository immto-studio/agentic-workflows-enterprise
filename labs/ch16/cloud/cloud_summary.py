"""The cloud session's summary, written from the JSON files beside it (step 7).

Every table in the README's step 7 section is one of these, and tests/test_cloud_results.py checks that the
summary is what this writes from the committed files and that the README's rows are the summary's. The spend
estimate multiplies the quantities the session recorded by the prices of fact sheet 8.8, read 2026-11-03, with
the dated table's form: the quote, its source and its date beside each number.

Run (from labs/ch16):
    python cloud/cloud_summary.py --results results/<date>/cloud
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
LAB = HERE.parent

PRICES = {
    "m7i-flex.large": (0.09576, "$0.09576 per On Demand Linux m7i-flex.large Instance Hour"),
    "t3.xlarge": (0.1664, "$0.1664 per On Demand Linux t3.xlarge Instance Hour"),
    "gp3": (0.08, "$0.08 per GB-month of General Purpose (gp3) provisioned storage - US East (Ohio)"),
    "public_ip": (0.005, "$0.005 per In-use public IPv4 address per hour"),
    "spans_gb": (0.35, "$0.35 per GB of Application Signals data ingested for the first 10TB - US East (Ohio)"),
    "span_indexed": (0.00000075, "$0.00000075 per spans indexed for USE2-XRay-Spans-Indexed in US East (Ohio)"),
    "insights_gb": (0.005, "$0.005 per GB log data scanned by CloudWatch Logs Insights queries - US East (Ohio)"),
    "nova_us_in": (0.06, "$0.00006 per 1K tokens for Nova Lite-input-tokens in us-east-2 (Ohio)"),
    "nova_us_out": (0.24, "the dated table's nova-lite-us output price, 0.24 USD per million tokens"),
    "nova_ca_in": (0.064, "$0.000064 per 1K tokens for CAN1-NovaLite-input-tokens in Canada (Central)"),
    "nova_ca_out": (0.256, "$0.000256 per 1K tokens for CAN1-NovaLite-output-tokens in Canada (Central)"),
    "ce_request": (0.01, "$0.01 per API Request"),
}
SOURCE = "fact sheet 8.8 (ledger/prices.yaml), read 2026-11-03"
SPAN_BYTES = 1000  # the CloudWatch pricing page's own assumption, "1 span = ~1kB" (fact sheet 8.2)


def load(results: Path, name: str) -> dict[str, Any]:
    path = results / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def q(value: Any, *keys: Any, default: Any = None) -> Any:
    for key in keys:
        if isinstance(value, dict):
            value = value.get(key)
        elif isinstance(value, list) and isinstance(key, int) and -len(value) <= key < len(value):
            value = value[key]
        else:
            return default
        if value is None:
            return default
    return value


def fmt(value: Any, digits: int = 1) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:,.{digits}f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def usd(value: float | None) -> str:
    return "none" if value is None else f"{value:.6f}".rstrip("0").rstrip(".") if value < 0.01 else f"{value:.4f}"


def whole(value: Any) -> str:
    """A statistic CloudWatch returns as a float (309817.0), printed as the count it is."""
    return "none" if value is None else f"{int(float(value)):,}"


def refusal(call: dict[str, Any], width: int = 120) -> str:
    """A refused call, as the gateway's own message when the body is JSON, and cut at a word boundary otherwise."""
    body = call.get("body") or call.get("error") or ""
    try:
        body = json.loads(body).get("error", {}).get("message") or body
    except (TypeError, ValueError, AttributeError):
        pass
    body = str(body)
    if len(body) > width:
        body = body[:width].rsplit(" ", 1)[0] + "..."
    return f"no: {call.get('status') or call.get('code') or ''} {body}".strip()


def spread(values: list[float]) -> str:
    """min / median / max, as the other steps' tables print a spread."""
    values = [v for v in values if v is not None]
    if not values:
        return "none"
    return f"{min(values):.1f} / {statistics.median(values):.1f} / {max(values):.1f}"


def table(header: list[str], rows: list[list[Any]]) -> list[str]:
    out = ["|" + " |".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["|" + " |".join(str(c) for c in row) + " |" for row in rows]
    return out + [""]


def hours_between(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    a = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(timezone.utc)
    b = datetime.fromisoformat(end.replace("Z", "+00:00")).astimezone(timezone.utc)
    return round((b - a).total_seconds() / 3600, 3)


# --- sections -------------------------------------------------------------------------------------------------

def budget_section(budget: dict[str, Any]) -> list[str]:
    rows = []
    for moment in ("start", "end"):
        item = budget.get(moment)
        if not item:
            continue
        b = item["budget"]
        notes = "; ".join(f"{int(n['threshold'])}% {n['type']}, {n.get('state') or 'no state'}, "
                          f"{', '.join(s['type'] + ' ' + s['address_kind'] for s in n['subscribers'])}"
                          for n in sorted(b["notifications"], key=lambda n: n["threshold"]))
        rows.append([moment, item["at"][:19], b["name"], f"{b['limit']['Amount']} {b['limit']['Unit']} a month",
                     f"{q(b, 'calculated_spend', 'ActualSpend', 'Amount', default='none')} USD", notes,
                     f"{q(item, 'plan', 'remaining_credits', 'amount', default='none')} USD ({q(item, 'plan', 'plan')}, {q(item, 'plan', 'status')})"])
    return ["## The budget (item 1)", "",
            *table(["Moment", "At (UTC)", "Budget", "Limit", "Actual spend", "Notifications", "Credits left"], rows)]


def transaction_search_section(ts: dict[str, Any]) -> list[str]:
    on, off = ts.get("on", {}), ts.get("off", {})
    statuses = sorted((k, v) for k, v in ts.items() if k.startswith("status_"))
    rows = []
    if on:
        rows.append(["on: resource policy", f"put as {q(on, 'resource_policy', 'name')}", fmt(q(on, "resource_policy", "seconds"))])
        rows.append(["on: destination to CloudWatchLogs", f"{q(on, 'update_destination', 'destination')} {q(on, 'update_destination', 'status') or q(on, 'update_destination', 'code')}",
                     fmt(q(on, "update_destination", "seconds"))])
        active = on.get("active", {})
        rows.append(["on: destination ACTIVE", f"{'reached' if active.get('reached') else 'still ' + str(q(active, 'readings', -1, 'status'))} after {len(active.get('readings', []))} readings",
                     fmt(active.get("seconds"))])
        rows.append(["on: indexing rule after the switch", f"{fmt(on.get('indexing_percent_after_switch'))} percent", ""])
        if on.get("update_indexing_rule"):
            rows.append(["on: indexing rule set", f"{fmt(q(on, 'update_indexing_rule', 'set_to'))} percent, the page's default", fmt(q(on, "update_indexing_rule", "seconds"))])
    for name, status in statuses:
        present = q(status, "log_groups", "aws/spans", "exists")
        rows.append([f"status at {status['at'][11:19]} UTC", f"{status['destination']} {status['destination_status']}, indexing {fmt(status['indexing_percent'])} percent, "
                     f"aws/spans {'present' if present else 'absent'}"
                     + (f" ({fmt(q(status, 'log_groups', 'aws/spans', 'stored_bytes'))} bytes stored)" if present else ""), ""])
    if off:
        rows.append(["off: destination to XRay", f"{q(off, 'update_destination', 'destination') or ''} {q(off, 'update_destination', 'status') or q(off, 'update_destination', 'code') or ''}".strip(),
                     fmt(q(off, "update_destination", "seconds"))])
        again = off.get("xray_again", {})
        rows.append(["off: destination XRay ACTIVE", f"{'reached' if again.get('reached') else 'not reached'} after {len(again.get('readings', []))} readings", fmt(again.get("seconds"))])
        rows.append(["off: resource policy", "deleted" if q(off, "resource_policy", "deleted") else str(q(off, "resource_policy", "code")), fmt(q(off, "resource_policy", "seconds"))])
        for group, item in (off.get("log_groups") or {}).items():
            rows.append([f"off: {group}", "deleted" if item.get("deleted") else item.get("why") or item.get("code"), fmt(item.get("seconds"))])
        if off.get("update_indexing_rule"):
            rows.append(["off: indexing rule restored", f"{fmt(q(off, 'update_indexing_rule', 'set_to'))} percent, as before the session", fmt(q(off, "update_indexing_rule", "seconds"))])
    out = ["## Transaction Search (item 2)", "", *table(["Step", "What AWS answered", "Seconds"], rows)]
    before, after_on, after_off = on.get("before", {}), on.get("after", {}), off.get("after", {})
    if before:
        out += table(["Setting", "Before the session", "After `on`", "After `off`"], [
            ["Trace segment destination", f"{before.get('destination')} {before.get('destination_status')}",
             f"{after_on.get('destination')} {after_on.get('destination_status')}", f"{after_off.get('destination', 'none')} {after_off.get('destination_status', '')}"],
            ["Default indexing rule (percent)", fmt(before.get("indexing_percent")), fmt(after_on.get("indexing_percent")), fmt(after_off.get("indexing_percent"))],
            ["Resource policy TransactionSearchAccess", fmt(before.get("resource_policy_present")), fmt(after_on.get("resource_policy_present")), fmt(after_off.get("resource_policy_present"))],
            ["Log group aws/spans", fmt(q(before, "log_groups", "aws/spans", "exists")), fmt(q(after_on, "log_groups", "aws/spans", "exists")), fmt(q(after_off, "log_groups", "aws/spans", "exists"))],
            ["Log group /aws/application-signals/data", fmt(q(before, "log_groups", "/aws/application-signals/data", "exists")),
             fmt(q(after_on, "log_groups", "/aws/application-signals/data", "exists")), fmt(q(after_off, "log_groups", "/aws/application-signals/data", "exists"))],
        ])
    prices = on.get("prices_while_on", {})
    if prices:
        out += table(["While on, AWS bills", "Quote", "Source, date"], [
            ["span ingestion", q(prices, "ingestion", "quote"), f"{q(prices, 'ingestion', 'source')}, {q(prices, 'ingestion', 'date')}"],
            ["spans indexed as trace summaries", f"{q(prices, 'indexing', 'quote')}; {q(prices, 'indexing', 'free_share')}", f"{q(prices, 'indexing', 'source')}, {q(prices, 'indexing', 'date')}"],
        ])
    return out


def export_section(export: dict[str, Any], vm: dict[str, Any]) -> list[str]:
    run, cw, lf = export.get("run", {}), export.get("cloudwatch") or {}, export.get("langfuse") or {}
    out = ["## The live run through the Collector (items 2 and 7)", ""]
    if run:
        out += table(["Runs", "Passed", "Traces", "Spans sent", "Left the Collector", "In the span file", "Traces with every span left",
                      "Share of the rest", "decision_wait", "Collector exit", "Error or warning lines in its log"],
                     [[run["runs"], run["passed"], run["traces"], run["spans_sent"], run["spans_left_collector"], run["spans_in_file"],
                       f"{run['traces_with_every_span_left']} of {run['traces']}", f"{fmt(export.get('share_percent'))}%",
                       f"{fmt(export.get('decision_wait_s'), 0)} s", q(export, "collector", "exit_code"), q(export, "collector", "log", "error_or_warning_lines")]])
    out += ["### CloudWatch", ""]
    if cw:
        since_left = [v.get("after_sink_s") for v in cw.get("first_seen", {}).values()]
        ingestion = [v.get("ingestion_minus_span_ms") / 1000 for v in cw.get("first_seen", {}).values() if v.get("ingestion_minus_span_ms") is not None]
        found = sum(cw.get("spans_found", {}).values())
        out += table(["Traces expected", "Group seen after (s)", "Traces seen", "Traces complete", "Spans found / sent", "Events not the run's",
                      "First reading (s after the poll began)", "Traces complete at the first reading",
                      "Had left the Collector (s) before it, min / median / max", "ingestionTime minus the span's start (s), min / median / max"],
                     [[cw["traces_expected"], fmt(cw.get("group_seen_after_s")), cw["traces_seen"], cw["traces_complete"],
                       f"{found} / {sum(cw.get('spans_expected', {}).values())}", cw.get("events_not_ours"), fmt(q(cw, "readings", 0, "seconds")),
                       q(cw, "readings", 0, "traces_complete"), spread(since_left), spread(ingestion)]])
        xray, signals, insights = cw.get("xray") or {}, cw.get("application_signals") or {}, cw.get("insights") or {}
        out += table(["Record keys", "Field that holds the trace id", "X-Ray trace summaries in the window", "Of them, the run's", "Indexing rule (percent)",
                      "Application Signals services", "Logs Insights query", "Rows", "Bytes scanned", "Records matched"],
                     [[", ".join(q(cw, "record_shape", "keys", default=[])), cw.get("trace_id_key"), xray.get("summaries_in_window", xray.get("code")),
                       xray.get("ours_indexed"), fmt(xray.get("indexing_percent")),
                       ", ".join(signals.get("services", [])) or ("none" if signals.get("ok") else signals.get("code")),
                       insights.get("status") or insights.get("code") or insights.get("why"), insights.get("rows"),
                       whole(q(insights, "statistics", "bytesScanned")), whole(q(insights, "statistics", "recordsMatched"))]])
    else:
        out += ["Not reached.", ""]
    out += ["### Langfuse", ""]
    if lf.get("comparison"):
        c = lf["comparison"]
        since_left = [v.get("after_sink_s") for v in lf.get("first_seen", {}).values()]
        out += table(["Langfuse", "Traces expected", "Seen", "Complete", "First reading (s after the poll began)",
                      "Traces complete at the first reading", "Had left the Collector (s) before it, min / median / max",
                      "Traces with every span id", "Gateway spans with a cost", "Cost equal to gen_ai.usage.cost",
                      "Tokens equal", "Tracestate anywhere", "Span attributes kept as metadata"],
                     [[q(lf, "health", "body", "version", default="no health"), lf["traces_expected"], lf["traces_seen"], lf["traces_complete"],
                       fmt(q(lf, "readings", 0, "seconds")), q(lf, "readings", 0, "traces_complete"), spread(since_left),
                       f"{c['traces_with_every_span']} of {len(c['traces'])}", c["cost_rows"], c["cost_read_from_gen_ai_usage_cost"],
                       sum(1 for r in c["gateway_spans_with_cost"] if r["tokens_equal"]), fmt(c["tracestate_anywhere"]), fmt(c["span_attributes_kept_as_metadata"])]])
        types: dict[str, int] = {}
        for row in c["traces"]:
            for kind, n in row["observation_types"].items():
                types[kind] = types.get(kind, 0) + n
        out += table(["Observation types", "Count"], [[k, v] for k, v in sorted(types.items())])
    else:
        out += [f"Not reached: {lf.get('why') or lf.get('health')}", ""]
    out += ["### The VM", ""]
    wait, tunnel = vm.get("wait") or {}, vm.get("tunnel") or {}
    if wait:
        markers = wait.get("markers", {})
        timeline = dict(line.rsplit(" ", 1) for line in (markers.get("timeline.txt") or "").splitlines() if " " in line)
        pull = hours_between(timeline.get("pull start"), timeline.get("pull done"))
        up = hours_between(timeline.get("up issued"), timeline.get("healthy"))
        out += table(["Instance type", "Ready after launch (s)", "Image pull (s)", "`up` to healthy (s)", "Langfuse health", "Pinned tags", "Docker", "Compose", "Cores", "Memory (MB)", "Tunnel"],
                     [[q(wait, "vm", "instance_type"), fmt(wait.get("ready_after_launch_s")), fmt(pull * 3600 if pull is not None else None, 0), fmt(up * 3600 if up is not None else None, 0),
                       json.dumps(markers.get("health.json")), markers.get("pin.txt"),
                       (markers.get("versions.txt") or "").splitlines()[0].replace("Docker version ", "") if markers.get("versions.txt") else "none",
                       (markers.get("versions.txt") or "\n").splitlines()[-1].replace("Docker Compose version ", "") if markers.get("versions.txt") else "none",
                       q(wait, "machine", "cores"), (q(wait, "machine", "memory") or "").split()[1] if q(wait, "machine", "memory") else "none",
                       tunnel.get("path") or "none"]])
        digests = [line.split(" ", 1) for line in (markers.get("digests.txt") or "").splitlines() if " " in line]
        out += table(["Image", "Digest"], [[tag, digest.split("@", 1)[-1][:19] + "..."] for tag, digest in digests])
    return out


def bedrock_section(bedrock: dict[str, Any]) -> list[str]:
    calls, trail = bedrock.get("calls", {}), bedrock.get("cloudtrail", {})
    out = ["## Bedrock with the trace id in requestMetadata (items 3 and 4)", ""]
    rows = []
    for attempt in q(calls, "canada", "attempts", default=[]):
        call = attempt["call"]
        lines = attempt.get("gateway", {})
        rows.append([f"Canada profile, {attempt['manifests']}", calls["canada"]["path"], "yes" if call.get("ok") else refusal(call),
                     f"{fmt(call.get('prompt_tokens'))} / {fmt(call.get('completion_tokens'))}", usd(call.get("cost_usd")),
                     f"{len(lines.get('cost_lines', []))} / {len(lines.get('spans', []))}", "not readable here (ca-central-1)", "", "", "", ""])
    for name, label in (("us_text_off", "In-Region us-east-2, text delivery off"), ("us_text_on", "In-Region us-east-2, text delivery on"),
                        ("us_profile", "US profile from us-east-2 (SDK)")):
        item = calls.get(name)
        if not item:
            continue
        call, shape, log = item["call"], item.get("record_shape") or {}, item.get("log") or {}
        tokens = f"{fmt(call.get('prompt_tokens', q(call, 'usage', 'inputTokens')))} / {fmt(call.get('completion_tokens', q(call, 'usage', 'outputTokens')))}"
        lines = item.get("gateway", {})
        rows.append([label, item["path"], "yes" if call.get("ok") else f"no: {call.get('code') or call.get('status')}", tokens, usd(call.get("cost_usd")),
                     f"{len(lines.get('cost_lines', []))} / {len(lines.get('spans', []))}" if "gateway" in item else "SDK call",
                     "found" if shape else f"not found in {fmt(log.get('polled_s'))} s", fmt(q(log, "found", "record", "seen_after_s")),
                     json.dumps(shape.get("request_metadata")) if shape else "", ", ".join(shape.get("text_fields_present", [])) or ("none" if shape else ""),
                     shape.get("inference_region") or ("absent" if shape else "")])
    out += table(["Call", "Path", "Answered", "Tokens in / out", "Gateway cost (USD)", "Cost lines / spans", "Invocation record", "Record after the call (s)",
                  "requestMetadata in the record", "Text fields", "inferenceRegion in the record"], rows)
    side = calls.get("canada_side", {})
    if side:
        out += table(["ca-central-1, anything but a model call", "Answer"],
                     [[name.replace("_", " "), "allowed" if v.get("ok") else f"refused ({v.get('code')})"] for name, v in side.items()])
    if trail:
        rows = []
        for name, item in trail.get("ours", {}).items():
            event = item.get("event") or {}
            rows.append([name.replace("_", " "), fmt(item["found"]), event.get("aws_region", ""), item.get("inference_region_cloudtrail") or ("absent" if event else ""),
                         item.get("inference_region_log") or "absent", fmt(item.get("request_id_matches_log")), event.get("event_name", "")])
        out += ["### CloudTrail, us-east-2", "", *table(["Call", "Event found", "awsRegion", "inferenceRegion (CloudTrail)", "inferenceRegion (log)",
                                                          "Request ID equals the log's", "Event name"], rows)]
        out += [f"Polled for {fmt(trail.get('polled_s'))} s; {trail.get('events_in_window')} Converse or InvokeModel events in the window.", ""]
    return out


def tool_role_section(tool: dict[str, Any]) -> list[str]:
    run, trail = tool.get("run", {}), tool.get("cloudtrail", {})
    out = ["## The tool role with the trace id (item 5)", ""]
    if run:
        rows = [["AssumeRole with the trace id tag and the session name", f"{'allowed' if q(run, 'assume', 'ok') else 'refused'}; session `{run['session']}`; {fmt(q(run, 'assume', 'latency_s'), 3)} s"],
                ["One read under it (ec2:DescribeInstances)", f"{'answered' if q(run, 'read', 'ok') else 'refused ' + str(q(run, 'read', 'code'))}; {fmt(q(run, 'read', 'latency_s'), 3)} s"]]
        for refusal in run.get("refusals", []):
            rows.append([f"AssumeRole with {refusal['case']}", f"{'refused' if refusal['refused'] else 'allowed'} ({refusal.get('code')})"])
        out += table(["Check", "Result"], rows)
    if trail:
        rows = [[name, fmt(v.get("minutes_after_call")), v.get("event_time", "")] for name, v in trail.get("first_seen", {}).items()]
        out += ["### CloudTrail, us-east-2", "", *table(["Event", "Seen after the call (min)", "Event time"], rows)]
        out += table(["Events of the two sessions", "AssumeRole", "DescribeInstances", "With userIdentity.accessKeyId", "Denied (errorCode)", "AssumeRole with the trace_id tag", "Polled (s)"],
                     [[trail.get("events"), q(trail, "by_name", "AssumeRole"), q(trail, "by_name", "DescribeInstances"), trail.get("with_access_key_id"),
                       trail.get("denied"), trail.get("assume_role_with_tags"), fmt(trail.get("polled_s"))]])
        joined = trail.get("join") or {}
        if joined:
            out += ["### join.py", "", *table(["Store", "Records"], [[k, v] for k, v in joined.get("records_per_store", {}).items()])]
            out += [f"CloudTrail's events matched by: {', '.join(joined.get('cloudtrail_matched_by', []))}. "
                    f"From one DescribeInstances event back to its run: {len(joined.get('reverse_from_one_read_event', []))} trace id.", ""]
    return out


def deny_all_section(tool: dict[str, Any]) -> list[str]:
    deny = q(tool, "run", "deny_all") or {}
    out = ["## The deny-all (item 6)", ""]
    if not deny:
        return out + ["Not run.", ""]
    rows = [["`identity.py pull` answered by IAM", fmt(deny.get("pull_answered_s"), 3), f"{len(deny.get('pull', []))} role; policy larkspur-kill-switch put"],
            ["calls that still passed after the pull", fmt(deny.get("calls_that_passed_after_pull")), f"one read every {fmt(deny.get('poll_interval_s'))} s"],
            ["first AccessDenied on credentials already issued", fmt(deny.get("first_denied_s"), 3), f"code {deny.get('first_denied_code')}"],
            ["`identity.py release` answered by IAM", fmt(deny.get("release_answered_s"), 3), "revoke statement alone, cut-off at the release"],
            ["a session issued after the release", fmt(q(deny, "later_session", "latency_s"), 3), f"{'issued' if q(deny, 'later_session', 'ok') else 'refused'}"],
            ["its first successful read", fmt(deny.get("later_session_first_success_s"), 3), f"{fmt(deny.get('later_session_refusals_before_success'))} refusals before it"],
            ["the earlier session after the release", "", f"{'still refused' if not q(deny, 'issued_before_release_after', 'ok') else 'allowed'} ({q(deny, 'issued_before_release_after', 'code')})"],
            ["`release --purge`", fmt(q(deny, "purge", "seconds"), 3), f"{q(deny, 'purge', 'results', 0, 'action')}; the later session then {'reads' if q(deny, 'later_session_after_purge', 'ok') else 'is refused'}"]]
    return out + table(["Step", "Seconds", "Detail"], rows) + [f"The clock: {deny.get('clock')}.", ""]


def cost_explorer_section(ce: dict[str, Any]) -> list[str]:
    out = ["## Cost Explorer (item 8)", ""]
    if not ce:
        return out + ["Not run.", ""]
    if ce.get("skipped"):
        why = ce.get("why") or {}
        out += [f"Skipped: Cost Explorer answered `{why.get('code')}` ({why.get('message', '')[:160]}) to {ce.get('requests')} request(s) "
                f"in the window {q(ce, 'window', 'start')} to {q(ce, 'window', 'end')}. The author has not opened Cost Explorer in the console, "
                "the one way to enable it (fact sheet 8.6), so the reconciliation of Nova Lite's days against the ledger's cost lines did not run.", ""]
    else:
        out += [f"Answered under the filter `{ce.get('filter')}` ({ce.get('requests')} request(s)); usage types: {', '.join(ce.get('usage_types', [])) or 'none'}; "
                f"cost in the window {usd(ce.get('cost_usd_in_window'))} USD.", ""]
        rows = [[r["day"], ", ".join(r["bill_usage_types"]) or "none", fmt(r["bill_input_tokens"]), fmt(r["bill_output_tokens"]), usd(r["bill_cost_usd"]),
                 r["ledger_calls"], f"{fmt(r['ledger_input_tokens'])} / {fmt(r['ledger_output_tokens'])}", usd(r["ledger_cost_usd"])]
                for r in ce.get("reconciliation", [])]
        out += table(["Day (the bill's, UTC; the ledger's, Toronto)", "Bill's usage types", "Bill input tokens", "Bill output tokens", "Bill cost (USD)",
                      "Ledger calls", "Ledger tokens in / out", "Ledger cost (USD)"], rows)
        a = ce.get("aligned") or {}
        if a:
            out += table(["Bill day (UTC)", "Ledger day (Toronto)", "Usage types", "Bill tokens in / out", "Ledger tokens in / out", "Ledger calls",
                          "Bill over ledger, input", "Bill over ledger, output", "Bill cost (USD)", "Bill at the table's price (USD)", "Ledger cost (USD)", "At list price, bill over ledger"],
                         [[a["bill_day_utc"], a["ledger_day_toronto"], ", ".join(a["usage_types"]), f"{fmt(a['bill_input_tokens'])} / {fmt(a['bill_output_tokens'])}",
                           f"{fmt(a['ledger_input_tokens'])} / {fmt(a['ledger_output_tokens'])}", a["ledger_calls"], fmt(a["input_ratio_bill_over_ledger"], 3),
                           fmt(a["output_ratio_bill_over_ledger"], 3), usd(a["bill_cost_usd"]), usd(a["bill_at_the_tables_price_usd"]), usd(a["ledger_cost_usd"]),
                           fmt(a["cost_ratio_at_list_price"], 3)]])
    ledger = ce.get("ledger", {})
    days = ", ".join(f"{d}: {v['calls']} calls, {v['input_tokens']:,} in, {v['output_tokens']:,} out, {usd(v['cost_usd'])} USD"
                     for d, v in sorted(ledger.get("days", {}).items()))
    out += [f"The ledger's Nova Lite lines: {days}, priced at {q(ledger, 'price', 'id')} ({q(ledger, 'price', 'input_per_million')} / "
            f"{q(ledger, 'price', 'output_per_million')} USD per million tokens, {q(ledger, 'price', 'date')}).", ""]
    return out


def teardown_section(teardown: dict[str, Any]) -> list[str]:
    out = ["## Teardown (item 9)", ""]
    if not teardown:
        return out + ["Not recorded.", ""]
    rows = []
    for name in ("vm_destroy", "destroy"):
        item = teardown.get(name)
        if item:
            rows.append([name.replace("_", " "), item.get("at", "")[:19], fmt(item.get("seconds"), 0), item.get("summary", "")])
    out += table(["Terraform", "At (UTC)", "Seconds", "Result"], rows)
    left = teardown.get("leftovers") or {}
    if left:
        out += table(["cloud/leftovers.py, after the destroy", "Found"],
                     [[k, json.dumps(v) if not isinstance(v, str) else v] for k, v in left.items() if k not in ("at", "region")])
    sweep = teardown.get("aws_sweep") or {}
    if sweep:
        out += table(["tools/cloudcheck/aws_sweep.py", "Found"], [[line.split(":", 1)[0], line.split(":", 1)[1].strip()] for line in sweep.get("lines", []) if ":" in line])
    return out


def spend_section(export: dict[str, Any], vm: dict[str, Any], bedrock: dict[str, Any], ce: dict[str, Any], teardown: dict[str, Any]) -> list[str]:
    wait = vm.get("wait") or {}
    instance_type = q(wait, "vm", "instance_type") or "m7i-flex.large"
    hours = hours_between(wait.get("launched"), q(teardown, "vm_destroy", "terminated_at") or q(teardown, "vm_destroy", "at"))
    rows: list[list[Any]] = []
    total = 0.0

    def add(service: str, quantity: str, key: str | None, amount: float | None, note: str = "") -> None:
        nonlocal total
        if key is None:
            rows.append([service, quantity, note or "no entry in the dated table", "", "not priced"])
            return
        price, quote = PRICES[key]
        rows.append([service, quantity, quote, SOURCE, usd(amount)])
        total += amount or 0.0

    add("EC2, the Langfuse VM", f"{fmt(hours, 3)} instance hours of {instance_type}", instance_type if instance_type in PRICES else None,
        (hours or 0) * PRICES.get(instance_type, (0, ""))[0])
    add("EBS, its gp3 disk", f"30 GiB for {fmt(hours, 3)} hours", "gp3", 30 * (hours or 0) / 730 * PRICES["gp3"][0])
    add("Public IPv4 address", f"{fmt(hours, 3)} hours", "public_ip", (hours or 0) * PRICES["public_ip"][0])
    spans = q(export, "run", "spans_left_collector") or 0
    add("CloudWatch, spans ingested", f"{spans} spans at about {SPAN_BYTES} bytes each (the pricing page's own assumption)", "spans_gb", spans * SPAN_BYTES / 1e9 * PRICES["spans_gb"][0])
    indexed = q(export, "cloudwatch", "xray", "ours_indexed") or 0
    add("CloudWatch, spans indexed", f"{indexed} of the run's traces indexed, inside the free 1 percent", "span_indexed", 0.0)
    scanned = q(export, "cloudwatch", "insights", "statistics", "bytesScanned") or 0
    add("CloudWatch Logs Insights", f"{fmt(scanned, 0)} bytes scanned", "insights_gb", scanned / 1e9 * PRICES["insights_gb"][0])
    calls = bedrock.get("calls", {})
    us_in = us_out = 0
    for name in ("us_text_off", "us_text_on", "us_profile"):
        call = q(calls, name, "call") or {}
        us_in += call.get("prompt_tokens") or q(call, "usage", "inputTokens") or 0
        us_out += call.get("completion_tokens") or q(call, "usage", "outputTokens") or 0
    first = q(bedrock, "first_run", "us_east_2_calls") or {}
    first_in = sum(c.get("prompt_tokens") or c.get("input_tokens") or 0 for c in first.values())
    first_out = sum(c.get("completion_tokens") or c.get("output_tokens") or 0 for c in first.values())
    us_in, us_out = us_in + first_in, us_out + first_out
    note = f", the first run's {len(first)} calls included" if first else ""
    add("Bedrock, Nova Lite in us-east-2", f"{us_in} input and {us_out} output tokens{note}", "nova_us_in",
        us_in / 1e6 * PRICES["nova_us_in"][0] + us_out / 1e6 * PRICES["nova_us_out"][0])
    ca = q(calls, "canada", "call") or {}
    ca_in, ca_out = ca.get("prompt_tokens") or 0, ca.get("completion_tokens") or 0
    add("Bedrock, Nova Lite through the Canada profile", f"{ca_in} input and {ca_out} output tokens", "nova_ca_in", ca_in / 1e6 * PRICES["nova_ca_in"][0] + ca_out / 1e6 * PRICES["nova_ca_out"][0])
    add("Cost Explorer API", f"{ce.get('requests', 0)} request(s)", "ce_request", (ce.get("requests") or 0) * PRICES["ce_request"][0])
    add("EC2 Instance Connect endpoint", "one endpoint", None, None, "no charge (fact sheet 8.6: \"There is no additional cost for using EC2 Instance Connect Endpoints.\")")
    add("AWS Budgets, SNS, IAM, STS, CloudTrail event history, the VPC, the invocation log's records", "one budget, one topic, two roles, the lookups, three records", None, None)
    rows.append(["Total of the priced lines", "", "", "", usd(round(total, 6))])
    return ["## The spend estimate, at list price", "", *table(["Service", "Quantity", "Price", "Source, date", "Estimate (USD)"], rows)]


def render(results: Path) -> str:
    budget, ts = load(results, "budget.json"), load(results, "transaction-search.json")
    export, vm, bedrock = load(results, "export-run.json"), load(results, "langfuse-vm.json"), load(results, "bedrock.json")
    tool, ce, teardown = load(results, "tool-role.json"), load(results, "cost-explorer.json"), load(results, "teardown.json")
    lines = ["# Chapter 16, step 7: the cloud session in us-east-2", "",
             "Written by `cloud/cloud_summary.py` from the files beside it: one session in the lab account on 9 November 2026, profile "
             "`book-lab`, every resource in us-east-2 on synthetic data (book D-034, D-036), the budget first and everything destroyed "
             "in the same session. Every number is a measurement; account IDs, access key IDs, principal IDs, user names, addresses, and "
             "public IP addresses are replaced in every file here. Timings count seconds with time.perf_counter() on this workstation and "
             "stamp moments with its UTC clock.", ""]
    lines += budget_section(budget)
    lines += transaction_search_section(ts)
    lines += export_section(export, vm)
    lines += bedrock_section(bedrock)
    lines += tool_role_section(tool)
    lines += deny_all_section(tool)
    lines += cost_explorer_section(ce)
    lines += teardown_section(teardown)
    lines += spend_section(export, vm, bedrock, ce, teardown)
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--results", type=Path, default=LAB / "results" / "2026-11-09" / "cloud")
    parser.add_argument("--check", action="store_true", help="exit 1 when summary.md differs from what this writes")
    args = parser.parse_args(argv)
    text = render(args.results)
    path = args.results / "summary.md"
    if args.check:
        current = path.read_text(encoding="utf-8").replace("\r\n", "\n") if path.exists() else ""
        print("same" if current == text else "different")
        return 0 if current == text else 1
    path.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {path} ({len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
