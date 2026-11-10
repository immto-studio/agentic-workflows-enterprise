"""Every record of one run, found by its trace id, and the run behind a CloudTrail event.

Chapter 16, step 3 (companion #14, O-D2). The trace id is the one key every store of a run shares: the harness
writes it on each line of its log and in the `_meta` of every tool call, the tool server logs it from there,
the gateway puts it on each cost line, and every span carries it. Given a trace id, this prints what each store
holds for it: the harness log, the tool server's log, the gateway's cost lines, and the spans the Collector
kept, as a tree with timings and the share each span was kept at. A run the tail sampler dropped still has
its logs and its cost lines, which never pass through sampling; its spans section says none were kept.

The cloud's own records join the same way, and each is one more `Store`. CloudTrail is written here, against
sample events in the shape AWS documents (`samples/cloudtrail-events.json`), so step 7 only points it at the
real trail; the model invocation log is step 7's to add. The amended O-D2 puts the trace id where CloudTrail
keeps it: in the role session name the tool server asks for, the engineer's object ID, a dot, and the trace
id's first 16 hex characters, which every event made with the session's credentials shows inside
`userIdentity.arn`; and in full as the session tag `trace_id`, which only the AssumeRole event records. An event
matches a run when its session name ends in the run's 16 characters, or it is the AssumeRole whose tag holds
the trace id, or its `userIdentity.accessKeyId`, when CloudTrail filled it in, is one an AssumeRole of the run
returned. Given a CloudTrail event instead (`--event`), the session name gives the 16 characters, and the full
trace id comes from the AssumeRole's tag or from the local stores.

Run (from labs/ch16):
    python collector/join.py <trace id>                              # the committed local run's stores
    python collector/join.py <trace id> --stores DIR --cloudtrail FILE
    python collector/join.py --event FILE --cloudtrail FILE          # the run behind a CloudTrail event
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import fake_otlp  # noqa: E402
import policies  # noqa: E402

DEFAULT_STORES = HERE.parent / "results" / "2026-11-03" / "collector" / "every-run"
SAMPLE_CLOUDTRAIL = HERE / "samples" / "cloudtrail-events.json"
TRACE_TAG = "trace_id"  # the session tag that carries the full trace id (O-D2, amended)
PREFIX = 16             # hex characters of the trace id in the role session name
_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")
_PREFIX = re.compile(r"^[0-9a-f]{16}$")


class Store(Protocol):
    name: str

    def records(self, trace_id: str) -> list[dict[str, Any]]: ...


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@dataclass
class JsonLines:
    """A JSON lines log whose lines carry `trace_id`: the harness's, the tool server's, the gateway's."""

    name: str
    path: Path

    def records(self, trace_id: str) -> list[dict[str, Any]]:
        return [line for line in read_jsonl(self.path) if line.get("trace_id") == trace_id]

    def trace_ids(self) -> set[str]:
        return {line["trace_id"] for line in read_jsonl(self.path) if isinstance(line.get("trace_id"), str)}


@dataclass
class Spans:
    """The Collector's span file: the spans it kept, as OTLP JSON, one export a line."""

    name: str
    path: Path

    def records(self, trace_id: str) -> list[dict[str, Any]]:
        return sorted((s for s in fake_otlp.spans_from_file(self.path) if s["trace_id"] == trace_id),
                      key=lambda s: (s["start_ns"], s["end_ns"]))


# --- CloudTrail ----------------------------------------------------------------------------------------

def load_events(path: Path) -> list[dict[str, Any]]:
    """CloudTrail events from a log file ({"Records": [...]}), LookupEvents output, or JSON lines."""
    text = Path(path).read_text(encoding="utf-8").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:  # more than one document: JSON lines
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    if isinstance(data, list):
        return data
    if "Records" in data:
        return list(data["Records"])
    if "Events" in data:  # LookupEvents: each event's record is a JSON string
        return [json.loads(e["CloudTrailEvent"]) for e in data["Events"]]
    return [data]


def session_of_arn(arn: str | None) -> str | None:
    """The role session name in an assumed-role ARN: arn:aws:sts::<account>:assumed-role/<role>/<session>."""
    if not arn or ":assumed-role/" not in arn:
        return None
    parts = arn.split(":assumed-role/", 1)[1].split("/", 1)
    return parts[1] if len(parts) == 2 else None


def prefix_of_session(name: str | None) -> str | None:
    """The trace id's 16 hex characters at the end of a session name `<object id>.<16 hex>`, if they are there."""
    if not name:
        return None
    _, dot, tail = name.rpartition(".")
    return tail if dot and _PREFIX.match(tail) else None


def session_name(event: Mapping[str, Any]) -> str | None:
    """The session an event belongs to: the one an AssumeRole created, or the one that made the call."""
    if event.get("eventName") == "AssumeRole":
        return (event.get("requestParameters") or {}).get("roleSessionName")
    identity = event.get("userIdentity") or {}
    return session_of_arn(identity.get("arn")) if identity.get("type") == "AssumedRole" else None


def trace_tag(event: Mapping[str, Any]) -> str | None:
    tags = (event.get("requestParameters") or {}).get("tags") or []
    return next((t.get("value") for t in tags if t.get("key") == TRACE_TAG), None)


@dataclass
class CloudTrail:
    """CloudTrail events, matched to a run by the role session name, the AssumeRole's tag, or the access key."""

    path: Path
    name: str = "CloudTrail"
    events: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.events = load_events(self.path)

    def matches(self, trace_id: str) -> list[tuple[str, dict[str, Any]]]:
        prefix = trace_id[:PREFIX]
        found: list[tuple[str, dict[str, Any]]] = []
        keys: set[str] = set()
        for event in self.events:  # the AssumeRole events first: they return the keys later events may carry
            if event.get("eventName") != "AssumeRole":
                continue
            if trace_tag(event) == trace_id:
                why = "AssumeRole, session tag trace_id"
            elif prefix_of_session(session_name(event)) == prefix:
                why = "AssumeRole, role session name"
            else:
                continue
            found.append((why, event))
            key = ((event.get("responseElements") or {}).get("credentials") or {}).get("accessKeyId")
            if key:
                keys.add(key)
        for event in self.events:
            if event.get("eventName") == "AssumeRole":
                continue
            identity = event.get("userIdentity") or {}
            key = identity.get("accessKeyId")
            if prefix_of_session(session_name(event)) == prefix:
                found.append(("role session name in userIdentity.arn", event))
            elif key and key in keys:  # used only when CloudTrail filled the key in
                found.append(("access key from the run's AssumeRole", event))
        return sorted(found, key=lambda pair: pair[1].get("eventTime", ""))

    def records(self, trace_id: str) -> list[dict[str, Any]]:
        return [{"matched_by": why, **summary(event)} for why, event in self.matches(trace_id)]

    def trace_ids_for(self, prefix: str) -> set[str]:
        """Full trace ids the AssumeRole tags give for a 16-character prefix."""
        return {tag for event in self.events if (tag := trace_tag(event)) and tag.startswith(prefix)}


def summary(event: Mapping[str, Any]) -> dict[str, Any]:
    identity = event.get("userIdentity") or {}
    context = identity.get("sessionContext") or {}
    out = {"eventTime": event.get("eventTime"), "eventSource": event.get("eventSource"),
           "eventName": event.get("eventName"), "awsRegion": event.get("awsRegion"),
           "session": session_name(event), "accessKeyId": identity.get("accessKeyId"),
           "sourceIdentity": context.get("sourceIdentity") or (event.get("requestParameters") or {}).get("sourceIdentity"),
           "requestID": event.get("requestID"), "eventID": event.get("eventID")}
    if event.get("eventName") == "AssumeRole":
        params = event.get("requestParameters") or {}
        out["roleArn"] = params.get("roleArn")
        out["tags"] = {t.get("key"): t.get("value") for t in params.get("tags") or []}
        out["returnedAccessKeyId"] = ((event.get("responseElements") or {}).get("credentials") or {}).get("accessKeyId")
    return out


# --- one run, from every store -----------------------------------------------------------------------

def local_stores(folder: Path) -> list[Store]:
    folder = Path(folder)
    return [JsonLines("harness log", folder / "harness.jsonl"), JsonLines("tool server log", folder / "server.jsonl"),
            JsonLines("gateway cost lines", folder / "gateway.jsonl"), Spans("spans", folder / "spans.jsonl")]


def join(trace_id: str, stores: Iterable[Store]) -> dict[str, list[dict[str, Any]]]:
    if not _TRACE_ID.match(trace_id):
        raise ValueError(f"{trace_id!r} isn't a trace id (32 lowercase hex characters)")
    return {store.name: store.records(trace_id) for store in stores}


def trace_for_event(event: Mapping[str, Any], stores: Iterable[Store], trail: CloudTrail | None) -> list[str]:
    """The full trace ids a CloudTrail event can belong to: from its session name, then a tag or a log."""
    prefix = prefix_of_session(session_name(event))
    if prefix is None:
        return []
    found = set(trail.trace_ids_for(prefix)) if trail else set()
    if tag := trace_tag(event):
        found.add(tag)
    for store in stores:
        if isinstance(store, JsonLines):
            found |= {t for t in store.trace_ids() if t.startswith(prefix)}
    return sorted(t for t in found if _TRACE_ID.match(t))


def tree(spans: list[dict[str, Any]]) -> list[str]:
    """The spans as an indented tree, each with its offset from the trace's start and its duration."""
    if not spans:
        return []
    start = min(s["start_ns"] for s in spans)
    ids = {s["span_id"] for s in spans}
    children: dict[str | None, list[dict[str, Any]]] = {}
    for s in spans:
        parent = s["parent_span_id"] if s["parent_span_id"] in ids else None
        children.setdefault(parent, []).append(s)
    lines: list[str] = []

    def walk(parent: str | None, depth: int) -> None:
        for s in sorted(children.get(parent, []), key=lambda s: (s["start_ns"], s["end_ns"])):
            share = policies.share_from_tracestate(s.get("trace_state"))
            extra = f"  (kept at a share of {share:g})" if share is not None and depth == 0 else ""
            lines.append(f"{'  ' * depth}{s['name']}  [{s['resource'].get('service.name')}]  "
                         f"+{(s['start_ns'] - start) / 1e6:.0f} ms, {(s['end_ns'] - s['start_ns']) / 1e6:.0f} ms"
                         f"{'  ' + s['status'] if s['status'] == 'ERROR' else ''}{extra}")
            walk(s["span_id"], depth + 1)

    walk(None, 0)
    return lines


def render(trace_id: str, joined: Mapping[str, list[dict[str, Any]]]) -> str:
    out = [f"trace {trace_id}"]
    for name, records in joined.items():
        if name == "spans":
            policy = sorted({s["scope_attributes"].get("tailsampling.policy") for s in records} - {None})
            shares = sorted({policies.share_from_tracestate(s.get("trace_state")) for s in records} - {None})
            head = (f"{len(records)} kept" + (f" by {', '.join(policy)}" if policy else "")
                    + (f", at a share of {', '.join(f'{x:g}' for x in shares)}" if shares else "")
                    if records else "none kept: the tail sampler dropped this run, or it hasn't decided yet")
            out.append(f"\n{name}: {head}")
            out += [f"  {line}" for line in tree(records)]
            continue
        head = f"{len(records)} record{'s' if len(records) != 1 else ''}"
        if name == "gateway cost lines" and records:
            calls = [r for r in records if r.get("event") == "call"]
            cost = sum(r.get("cost_usd") or 0 for r in calls)
            tokens_in = sum(r.get("prompt_tokens") or 0 for r in calls)
            tokens_out = sum(r.get("completion_tokens") or 0 for r in calls)
            head += f": {len(calls)} served, {cost:.6f} USD, {tokens_in:,} tokens in, {tokens_out:,} out"
        out.append(f"\n{name}: {head}")
        out += [f"  {json.dumps(r, ensure_ascii=False)}" for r in records]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("trace_id", nargs="?", help="the run's trace id, 32 lowercase hex characters")
    parser.add_argument("--stores", type=Path, default=DEFAULT_STORES,
                        help="folder with harness.jsonl, server.jsonl, gateway.jsonl and spans.jsonl")
    parser.add_argument("--cloudtrail", type=Path, help="CloudTrail events: a log file, LookupEvents output or JSON lines")
    parser.add_argument("--event", type=Path, help="one CloudTrail event (JSON): print the run behind it")
    parser.add_argument("--json", action="store_true", help="print the joined records as JSON")
    args = parser.parse_args(argv)
    stores: list[Store] = local_stores(args.stores)
    trail = CloudTrail(args.cloudtrail) if args.cloudtrail else None
    if trail:
        stores.append(trail)
    if args.event:
        event = json.loads(args.event.read_text(encoding="utf-8"))
        ids = trace_for_event(event, stores, trail)
        if len(ids) != 1:
            print(f"the event's session name {session_name(event)!r} gives {len(ids)} trace ids: {ids}", file=sys.stderr)
            return 1
        trace_id = ids[0]
    elif args.trace_id:
        trace_id = args.trace_id
    else:
        parser.error("give a trace id or --event")
    joined = join(trace_id, stores)
    if args.json:
        print(json.dumps({"trace_id": trace_id, **joined}, indent=2))
    else:
        print(render(trace_id, joined), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
