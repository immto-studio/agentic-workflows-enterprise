"""The tool role assumed with the run's trace id, one read under it, the deny-all timed, and the CloudTrail join.

Step 7, items 5 and 6 (O-D2 and O-D7, amended). The role is terraform/iam.tf's: chapter 6's name for W3's read
tool, a trust policy that requires the `workflow` and `trace_id` session tags and a role session name of the
engineer's object ID, a dot, and the trace id's first 16 characters, and one read, ec2:DescribeInstances. `run`:

- assumes the role for one of the live run's trace ids (the run join.py then prints whole), makes the read, and
  tries the three shapes the trust policy must refuse: no trace id tag, chapter 6's session name alone, and a tag
  key the policy doesn't list;
- pulls the identity half of the kill switch with budget/identity.py's own functions on that role, with the
  session's credentials already issued, and counts the seconds until the first AccessDenied; releases it; and
  counts the seconds until a session issued after the release works, with the earlier session still refused;
  then removes the policy (`release --purge`), so the destroy finds the role as Terraform left it.

`cloudtrail`, run later, polls us-east-2's event history for the AssumeRole and DescribeInstances events of those
sessions, records how long each took to appear, keeps them (redacted) in the results, and runs join.py both ways:
the trace id to every record, the live run's local stores included, and one event back to its run.

Run (from labs/ch16, with the session's environment):
    python cloud/tool_role.py run --trace-id <a trace id of the live run> --out results/<date>/cloud
    python cloud/tool_role.py cloudtrail --stores results/<date>/cloud/export-run --out results/<date>/cloud
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
LAB = HERE.parent
for folder in (HERE, LAB / "budget", LAB / "collector"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import cloud_session  # noqa: E402
import identity  # noqa: E402  step 4's identity half of the kill switch
import join  # noqa: E402

OBJECT_ID = "3f2b9c1e-6a4d-4e8b-9c7f-1a2b3c4d5e6f"  # the engineer's object ID the samples use; synthetic
MANIFEST = LAB.parent / "ch05" / "manifest" / "w3-incident.yaml"
WORKFLOW = "w3-incident"
PREFIX = join.PREFIX
EVENT_NAMES = ("AssumeRole", "DescribeInstances")


def session_name(object_id: str, trace_id: str) -> str:
    """The amended O-D2's shape: the engineer's object ID, a dot, the trace id's first 16 hex characters."""
    return f"{object_id}.{trace_id[:PREFIX]}"


def sts_client(s: Any) -> Any:
    """STS at its us-east-2 endpoint, so the AssumeRole event lands in us-east-2's event history."""
    return s.client("sts", region_name=cloud_session.REGION, endpoint_url=f"https://sts.{cloud_session.REGION}.amazonaws.com")


def assume(sts: Any, role_arn: str, trace_id: str, *, workflow: str = WORKFLOW, object_id: str = OBJECT_ID,
           name: str | None = None, tags: list[dict[str, str]] | None = None, duration: int = 900) -> dict[str, Any]:
    """AssumeRole with the session name and the tags; the credentials never leave the process."""
    request = {"RoleArn": role_arn, "RoleSessionName": name or session_name(object_id, trace_id),
               "DurationSeconds": duration,
               "Tags": tags if tags is not None else [{"Key": "workflow", "Value": workflow}, {"Key": "trace_id", "Value": trace_id}]}
    started, t0 = cloud_session.utc(), time.perf_counter()
    try:
        answer = sts.assume_role(**request)
    except Exception as exc:
        return {"ok": False, "session": request["RoleSessionName"], "tags": [t["Key"] for t in request["Tags"]],
                "started": started, "latency_s": round(time.perf_counter() - t0, 3), **cloud_session.aws_error(exc)}
    return {"ok": True, "session": request["RoleSessionName"], "tags": [t["Key"] for t in request["Tags"]],
            "started": started, "latency_s": round(time.perf_counter() - t0, 3),
            "expiration": answer["Credentials"]["Expiration"].isoformat(),
            "returned_access_key_id": answer["Credentials"]["AccessKeyId"],  # redacted to its placeholder when kept
            "credentials": answer["Credentials"]}


def read_call(s: Any, credentials: dict[str, Any]) -> dict[str, Any]:
    """The one read the role allows, with the session's credentials."""
    ec2 = s.client("ec2", region_name=cloud_session.REGION, aws_access_key_id=credentials["AccessKeyId"],
                   aws_secret_access_key=credentials["SecretAccessKey"], aws_session_token=credentials["SessionToken"])
    t0 = time.perf_counter()
    try:
        answer = ec2.describe_instances(MaxResults=5)
        return {"ok": True, "reservations": len(answer.get("Reservations", [])), "latency_s": round(time.perf_counter() - t0, 3)}
    except Exception as exc:
        return {"ok": False, "latency_s": round(time.perf_counter() - t0, 3), **cloud_session.aws_error(exc)}


def refusals(sts: Any, role_arn: str, trace_id: str) -> list[dict[str, Any]]:
    """The shapes the trust policy must refuse."""
    cases = [
        ("no trace_id tag", {"tags": [{"Key": "workflow", "Value": WORKFLOW}]}),
        ("chapter 6's session name, the object ID alone", {"name": OBJECT_ID}),
        ("a tag key the policy doesn't list", {"tags": [{"Key": "workflow", "Value": WORKFLOW}, {"Key": "trace_id", "Value": trace_id},
                                                        {"Key": "team", "Value": "ops"}]}),
        ("a trace id of the wrong length", {"tags": [{"Key": "workflow", "Value": WORKFLOW}, {"Key": "trace_id", "Value": trace_id[:31]}]}),
    ]
    out = []
    for why, kwargs in cases:
        answer = assume(sts, role_arn, trace_id, **kwargs)
        answer.pop("credentials", None)
        out.append({"case": why, "refused": not answer["ok"], "code": answer.get("code"), "message": answer.get("message")})
    return out


def deny_all(s: Any, iam: Any, sts: Any, role_name: str, role_arn: str, issued: dict[str, Any], *,
             every: float = 0.5, limit: float = 180.0) -> dict[str, Any]:
    """identity.py's pull and release on the role, timed against credentials already issued."""
    record: dict[str, Any] = {"clock": cloud_session.CLOCK, "poll_interval_s": every}
    clock = cloud_session.Clock()
    record["pull_requested"] = clock.started
    results = identity.pull(iam, [role_name], WORKFLOW)
    record["pull"] = [r.__dict__ for r in results]
    record["pull_answered_s"] = clock.seconds()
    calls = []
    while clock.seconds() < limit:
        answer = read_call(s, issued["credentials"])
        calls.append({"seconds": clock.seconds(), "ok": answer["ok"], "code": answer.get("code")})
        if not answer["ok"]:
            break
        time.sleep(every)
    denied = next((c for c in calls if not c["ok"]), None)
    record["calls_after_pull"] = calls
    record["first_denied_s"] = denied["seconds"] if denied else None
    record["first_denied_code"] = denied["code"] if denied else None
    record["calls_that_passed_after_pull"] = sum(1 for c in calls if c["ok"])

    release_clock = cloud_session.Clock()
    record["release_requested"] = release_clock.started
    results = identity.release(iam, [role_name], WORKFLOW)
    record["release"] = [r.__dict__ for r in results]
    record["release_answered_s"] = release_clock.seconds()
    time.sleep(2.0)  # the revoke statement's cut-off is the release's second; a session issued in it would be denied
    later_trace = uuid.uuid4().hex
    later = assume(sts, role_arn, later_trace)
    record["later_session"] = {k: v for k, v in later.items() if k != "credentials"}
    record["later_trace_id"] = later_trace
    calls = []
    if later["ok"]:
        while release_clock.seconds() < limit:
            answer = read_call(s, later["credentials"])
            calls.append({"seconds": release_clock.seconds(), "ok": answer["ok"], "code": answer.get("code")})
            if answer["ok"]:
                break
            time.sleep(every)
    passed = next((c for c in calls if c["ok"]), None)
    record["calls_after_release"] = calls
    record["later_session_first_success_s"] = passed["seconds"] if passed else None
    record["later_session_refusals_before_success"] = sum(1 for c in calls if not c["ok"])
    record["issued_before_release_after"] = read_call(s, issued["credentials"])
    purge_clock = cloud_session.Clock()
    results = identity.release(iam, [role_name], WORKFLOW, purge=True)
    record["purge"] = {"results": [r.__dict__ for r in results], "seconds": purge_clock.seconds()}
    time.sleep(2.0)
    record["later_session_after_purge"] = read_call(s, later["credentials"]) if later["ok"] else None
    return record


def run(s: Any, role_name: str, trace_id: str) -> dict[str, Any]:
    iam, sts = s.client("iam"), sts_client(s)
    role = iam.get_role(RoleName=role_name)["Role"]
    record: dict[str, Any] = {"started": cloud_session.utc(), "clock": cloud_session.CLOCK, "role": role_name,
                              "role_tags": {t["Key"]: t["Value"] for t in role.get("Tags") or []},
                              "trace_id": trace_id, "object_id": OBJECT_ID, "session": session_name(OBJECT_ID, trace_id),
                              "sts_endpoint": sts.meta.endpoint_url}
    assumed = assume(sts, role["Arn"], trace_id)
    record["assume"] = {k: v for k, v in assumed.items() if k != "credentials"}
    if not assumed["ok"]:
        return record
    record["read"] = {"started": cloud_session.utc(), **read_call(s, assumed["credentials"])}
    record["refusals"] = refusals(sts, role["Arn"], trace_id)
    record["deny_all"] = deny_all(s, iam, sts, role_name, role["Arn"], assumed)
    record["ended"] = cloud_session.utc()
    return record


# --- CloudTrail --------------------------------------------------------------------------------------------

def lookup(trail: Any, event_name: str, since: datetime) -> list[dict[str, Any]]:
    out = []
    token: str | None = None
    for _ in range(20):
        kwargs: dict[str, Any] = {"LookupAttributes": [{"AttributeKey": "EventName", "AttributeValue": event_name}],
                                  "StartTime": since, "MaxResults": 50}
        if token:
            kwargs["NextToken"] = token
        page = trail.lookup_events(**kwargs)
        out += [json.loads(item["CloudTrailEvent"]) for item in page.get("Events", [])]
        token = page.get("NextToken")
        if not token:
            break
    return out


def ours(events: list[dict[str, Any]], sessions: set[str]) -> list[dict[str, Any]]:
    return [e for e in events if join.session_name(e) in sessions]


def cloudtrail(s: Any, record: dict[str, Any], *, limit: float = 1200.0, every: float = 20.0) -> dict[str, Any]:
    """Poll for the sessions' events until the first run's AssumeRole and read are there, or the limit."""
    sessions = {record["session"]}
    later = record.get("deny_all", {}).get("later_session", {}).get("session")
    if later:
        sessions.add(later)
    since = datetime.fromisoformat(record["started"]).astimezone(timezone.utc) - timedelta(minutes=2)
    call_times = {"AssumeRole": record["assume"]["started"], "DescribeInstances": record["read"]["started"]}
    trail = s.client("cloudtrail")
    clock = cloud_session.Clock()
    first_seen: dict[str, dict[str, Any]] = {}
    readings = []
    events: dict[str, list[dict[str, Any]]] = {}
    while True:
        for name in EVENT_NAMES:
            events[name] = ours(lookup(trail, name, since), sessions)
            mine = [e for e in events[name] if join.session_name(e) == record["session"]]
            if mine and name not in first_seen:
                earliest = min(mine, key=lambda e: e.get("eventTime", ""))
                made = datetime.fromisoformat(call_times[name]).astimezone(timezone.utc)
                first_seen[name] = {"seconds": clock.seconds(), "event_time": earliest.get("eventTime"),
                                    "minutes_after_call": round((datetime.now(timezone.utc) - made).total_seconds() / 60, 1)}
        readings.append({"seconds": clock.seconds(), **{name: len(events[name]) for name in EVENT_NAMES}})
        if len(first_seen) == len(EVENT_NAMES) or clock.seconds() > limit:
            break
        time.sleep(every)
    everything = sorted((e for name in EVENT_NAMES for e in events[name]), key=lambda e: e.get("eventTime", ""))
    out: dict[str, Any] = {"clock": cloud_session.CLOCK, "started": clock.started, "polled_s": clock.seconds(),
                           "readings": readings, "first_seen": first_seen, "sessions": sorted(sessions),
                           "events": len(everything),
                           "by_name": {name: len(events[name]) for name in EVENT_NAMES},
                           "with_access_key_id": sum(1 for e in everything if (e.get("userIdentity") or {}).get("accessKeyId")),
                           "denied": sum(1 for e in everything if e.get("errorCode")),
                           "assume_role_with_tags": sum(1 for e in events["AssumeRole"] if join.trace_tag(e)),
                           "records": everything}
    return out


def join_both_ways(trace_id: str, stores: Path, events_path: Path) -> dict[str, Any]:
    trail = join.CloudTrail(events_path)
    local = join.local_stores(stores)
    joined = join.join(trace_id, [*local, trail])
    text = join.render(trace_id, joined)
    read_events = [e for e in trail.events if e.get("eventName") == "DescribeInstances" and not e.get("errorCode")
                   and join.prefix_of_session(join.session_name(e)) == trace_id[:PREFIX]]
    reverse = join.trace_for_event(read_events[0], local, trail) if read_events else []
    return {"records_per_store": {name: len(records) for name, records in joined.items()},
            "cloudtrail_matched_by": sorted({r["matched_by"] for r in joined.get("CloudTrail", [])}),
            "reverse_from_one_read_event": reverse, "text": text}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("action", choices=("run", "cloudtrail"))
    parser.add_argument("--trace-id", help="run: the live run's trace id to assume the role for")
    parser.add_argument("--role", help="the role's name (default: the Terraform output tool_role_name)")
    parser.add_argument("--stores", type=Path, help="cloudtrail: the live run's stores (results/<date>/cloud/export-run)")
    parser.add_argument("--out", type=Path, default=cloud_session.results_dir())
    args = parser.parse_args(argv)
    cloud_session.require_environment()
    s = cloud_session.session()
    path = args.out / "tool-role.json"
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["workflow"] == WORKFLOW
    if args.action == "run":
        if not args.trace_id or not join._TRACE_ID.match(args.trace_id):
            parser.error("--trace-id must be 32 lowercase hex characters")
        role = args.role or cloud_session.terraform_outputs()["tool_role_name"]
        record = run(s, role, args.trace_id)
        cloud_session.merge_json(path, "run", record)
        deny = record.get("deny_all", {})
        print(f"assume ok={record['assume']['ok']} read ok={record.get('read', {}).get('ok')} "
              f"refused {sum(1 for r in record.get('refusals', []) if r['refused'])} of {len(record.get('refusals', []))}; "
              f"deny-all: first denied {deny.get('first_denied_s')} s, later session ok after {deny.get('later_session_first_success_s')} s")
    else:
        record = cloud_session.read_json(path)["run"]
        out = cloudtrail(s, record)
        records = out.pop("records")
        raw = cloud_session.SCRATCH / "cloudtrail-events-raw.json"  # the raw events, so the kept file can be made again
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text(json.dumps(records), encoding="utf-8", newline="\n")
        events_path = args.out / "cloudtrail-events.json"
        cloud_session.write_json(events_path, {"about": "CloudTrail event history, us-east-2, the sessions of step 7's tool role; "
                                               "account IDs, access key IDs, principal IDs, user names, and addresses replaced",
                                               "Records": records})
        if args.stores:
            joined = join_both_ways(record["trace_id"], args.stores, events_path)
            cloud_session.write_text(args.out / "join.txt", joined.pop("text"))
            out["join"] = joined
        cloud_session.merge_json(path, "cloudtrail", out)
        print(f"events {out['events']} ({out['by_name']}), first seen {out['first_seen']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
