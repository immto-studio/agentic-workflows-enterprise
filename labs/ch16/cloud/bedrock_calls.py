"""Bedrock with the trace id in requestMetadata, and the US profile called from us-east-2 (step 7, items 3 and 4).

Four Nova Lite calls, each with the run's trace id and workflow in Bedrock's `requestMetadata` (O-D2, amended;
fact sheet 8.2), each a one-line synthetic prompt:

- the Canada call, through step 7's gateway with chapter 6's design (litellm.bedrock-ca.yaml): W3's `larkspur-chat`
  on the Canadian profile, called in ca-central-1. The lab account can enable logging and read CloudTrail in
  us-east-2 alone (book D-034), so the session also records what ca-central-1 answers;
- two logged calls in us-east-2 through the gateway (litellm.bedrock-us.yaml), W2's `larkspur-chat` on Nova Lite
  In-Region: one with text delivery off, as Terraform leaves it, one with text delivery on, switched by API;
- the US cross-Region profile, `us.amazon.nova-lite-v1:0`, called in us-east-2 with the SDK and the same metadata
  (item 4): a refusal would be a finding (O-D11). Its serving Region comes from the invocation log's
  `inferenceRegion` and from CloudTrail's `additionalEventData.inferenceRegion`, and the two records' request IDs
  are compared (fact sheet 8.2 left both unverified).

`calls` makes the calls and reads the invocation log back; `cloudtrail`, run later, finds the calls' CloudTrail
events in us-east-2, which take minutes to appear. Both write to results/<date>/cloud/bedrock.json.

Run (from labs/ch16, with the session's environment):
    python cloud/bedrock_calls.py calls --out results/<date>/cloud
    python cloud/bedrock_calls.py cloudtrail --out results/<date>/cloud
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).resolve().parent
LAB = HERE.parent
CH05 = LAB.parent / "ch05"
for folder in (HERE, LAB / "collector", LAB / "budget", CH05 / "harness", CH05 / "tracing"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import cloud_session  # noqa: E402
import procs  # noqa: E402  step 4's: a process stopped with its whole tree
import trace_setup as tracing  # noqa: E402
from cloudwatch_spans import fetch_events  # noqa: E402
from gateway_model import GatewayModel  # noqa: E402
from join import read_jsonl  # noqa: E402
from otelcol import free_port  # noqa: E402

PROMPT = "Reply with the single word: ready."
MASTER_KEY = "sk-larkspur-lab-ch16-cloud"  # a local value for the proxy and its one caller, not a secret
US_PROFILE = "us.amazon.nova-lite-v1:0"
CA_PROFILE = "ca.amazon.nova-lite-v1:0"
TEXT_FIELDS = ("inputBodyJson", "outputBodyJson", "inputBody", "outputBody", "messages")


# --- the gateway -------------------------------------------------------------------------------------------

class Gateway:
    """Step 7's LiteLLM proxy on one config, with the two callbacks, its cost lines and spans in `work`."""

    def __init__(self, config: Path, work: Path, *, manifest_dir: Path | None = None, tag: str = "") -> None:
        self.config, self.work, self.manifest_dir = config, work, manifest_dir
        self.proc: subprocess.Popen | None = None
        self.url = ""
        stem = f"{config.stem}{'-' + tag if tag else ''}"
        self.cost_lines = work / f"gateway-{stem}.jsonl"
        self.spans = work / f"traces-{stem}.jsonl"
        self.log = work / f"proxy-{stem}.log"

    def start(self, timeout: float = 180.0) -> Gateway:
        litellm = shutil.which("litellm", path=str(Path(sys.executable).parent))
        if not litellm:
            raise RuntimeError("the litellm console script isn't next to this interpreter; use chapter 5's environment")
        env = dict(os.environ) | cloud_session.aws_environment() | {
            "GATEWAY_CONFIG": str(self.config), "GATEWAY_LOG_FILE": str(self.cost_lines),
            "TRACE_FILE": str(self.spans), "LITELLM_MASTER_KEY": MASTER_KEY, "LITELLM_LOCAL_MODEL_COST_MAP": "True",
            "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
        env.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)  # the gateway's spans go to its JSON lines file
        if self.manifest_dir:
            env["MANIFEST_DIR"] = str(self.manifest_dir)  # chapter 5's hooks read the manifests from here
        port = free_port()
        self.url = f"http://127.0.0.1:{port}"
        self._log = self.log.open("ab")
        self.proc = subprocess.Popen([litellm, "--config", self.config.name, "--host", "127.0.0.1", "--port", str(port)],
                                     cwd=str(HERE), env=env, stdout=self._log, stderr=subprocess.STDOUT)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"the proxy exited with {self.proc.returncode}; see {self.log}")
            try:
                if httpx.get(f"{self.url}/health/liveliness", timeout=2).status_code < 500:
                    return self
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        raise RuntimeError(f"the proxy didn't answer in {timeout:.0f} s; see {self.log}")

    def stop(self) -> None:
        if self.proc:
            procs.stop_tree(self.proc)  # litellm.exe is a launcher: the whole tree, as step 4's scripts stop it
            self._log.close()

    def lines_for(self, trace_id: str) -> dict[str, list[dict[str, Any]]]:
        return {"cost_lines": [line for line in read_jsonl(self.cost_lines) if line.get("trace_id") == trace_id],
                "spans": [span for span in read_jsonl(self.spans) if span.get("trace_id") == trace_id]}


def gateway_request(alias: str, workflow: str, data_class: str, trace_id: str) -> dict[str, Any]:
    """The request as chapter 5's GatewayModel shapes it (its tags and trace id), without a tool list: the
    prompt asks for one word, and Bedrock refuses an empty toolConfig."""
    request = GatewayModel("", alias, tools=[], trace_id=trace_id, workflow=workflow, data_class=data_class,
                           api_key=MASTER_KEY).request([{"role": "user", "content": PROMPT}])
    request.pop("tools", None)
    return request


def gateway_call(url: str, alias: str, workflow: str, data_class: str, trace_id: str) -> dict[str, Any]:
    """One call through the gateway with the metadata chapter 5's harness sends, which the gateway reads."""
    started, t0 = cloud_session.utc(), time.perf_counter()
    try:
        response = httpx.post(f"{url}/chat/completions", json=gateway_request(alias, workflow, data_class, trace_id),
                              headers={"Authorization": f"Bearer {MASTER_KEY}"}, timeout=120)
    except httpx.HTTPError as exc:
        return {"ok": False, "started": started, "error": f"{type(exc).__name__}: {exc}"[:400]}
    latency = round(time.perf_counter() - t0, 3)
    if response.status_code != 200:
        return {"ok": False, "started": started, "status": response.status_code, "latency_s": latency,
                "body": cloud_session.redact_text(response.text)[:400]}
    body = response.json()
    usage = body.get("usage") or {}
    cost = response.headers.get("x-litellm-response-cost")
    text = ((body.get("choices") or [{}])[0].get("message") or {}).get("content")
    return {"ok": True, "started": started, "latency_s": latency, "text": (text or "")[:120],
            "model": body.get("model"), "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "cost_usd": float(cost) if cost not in (None, "None") else None}


def direct_converse(s: Any, region: str, model_id: str, trace_id: str, workflow: str) -> dict[str, Any]:
    """One Converse call with the SDK and the same metadata; the response's request ID joins it to the logs."""
    client = s.client("bedrock-runtime", region_name=region)
    started, t0 = cloud_session.utc(), time.perf_counter()
    try:
        answer = client.converse(modelId=model_id, messages=[{"role": "user", "content": [{"text": PROMPT}]}],
                                 inferenceConfig={"maxTokens": 20, "temperature": 0},
                                 requestMetadata={"trace_id": trace_id, "workflow": workflow})
    except Exception as exc:  # a refusal is the finding O-D11 asks about
        return {"ok": False, "started": started, "region_called": region, "model_id": model_id,
                "latency_s": round(time.perf_counter() - t0, 3), **cloud_session.aws_error(exc)}
    content = answer.get("output", {}).get("message", {}).get("content", [])
    return {"ok": True, "started": started, "region_called": region, "model_id": model_id,
            "latency_s": round(time.perf_counter() - t0, 3), "request_id": answer["ResponseMetadata"]["RequestId"],
            "usage": answer.get("usage"), "metrics": answer.get("metrics"), "stop_reason": answer.get("stopReason"),
            "text": "".join(c.get("text", "") for c in content)[:120]}


# --- the invocation log ------------------------------------------------------------------------------------

def logging_configuration(bedrock: Any) -> dict[str, Any]:
    try:
        return {"ok": True, "config": bedrock.get_model_invocation_logging_configuration().get("loggingConfig")}
    except Exception as exc:
        return {"ok": False, **cloud_session.aws_error(exc)}


def set_text_delivery(bedrock: Any, enabled: bool) -> dict[str, Any]:
    """Flip text delivery on the configuration Terraform made, keeping its destination."""
    current = bedrock.get_model_invocation_logging_configuration().get("loggingConfig") or {}
    config = {k: v for k, v in current.items() if k in ("cloudWatchConfig", "s3Config", "imageDataDeliveryEnabled",
                                                        "embeddingDataDeliveryEnabled", "videoDataDeliveryEnabled")}
    config["textDataDeliveryEnabled"] = enabled
    bedrock.put_model_invocation_logging_configuration(loggingConfig=config)
    after = bedrock.get_model_invocation_logging_configuration().get("loggingConfig") or {}
    return {"text_data_delivery_enabled": after.get("textDataDeliveryEnabled"), "at": cloud_session.utc()}


def record_shape(record: dict[str, Any]) -> dict[str, Any]:
    """The record's keys, what its input and output hold, and whether any text field is present."""
    def keys(value: Any) -> list[str]:
        return sorted(value.keys()) if isinstance(value, dict) else []

    text_present = [k for k in TEXT_FIELDS if k in keys(record.get("input")) or k in keys(record.get("output"))]
    return {"keys": keys(record), "input_keys": keys(record.get("input")), "output_keys": keys(record.get("output")),
            "request_metadata": record.get("requestMetadata"), "inference_region": record.get("inferenceRegion"),
            "region": record.get("region"), "model_id": record.get("modelId"), "operation": record.get("operation"),
            "request_id": record.get("requestId"), "text_fields_present": text_present,
            "input_token_count": (record.get("input") or {}).get("inputTokenCount"),
            "output_token_count": (record.get("output") or {}).get("outputTokenCount")}


def wait_for_records(logs: Any, group: str, since_ms: int, wanted: dict[str, Callable[[dict[str, Any]], bool]],
                     clock: cloud_session.Clock, limit: float = 600.0, every: float = 10.0) -> dict[str, Any]:
    """Poll the group until every wanted record is there, or the limit; the moment each appeared is kept."""
    found: dict[str, dict[str, Any]] = {}
    while True:
        for entry in fetch_events(logs, group, since_ms):  # the same reader cloudwatch_spans uses on aws/spans
            for name, matches in wanted.items():
                if name not in found and matches(entry["message"]):
                    found[name] = {"seen_after_s": clock.seconds(), "log_timestamp_ms": entry["timestamp_ms"],
                                   "ingestion_ms": entry["ingestion_ms"], "record": entry["message"]}
        if len(found) == len(wanted) or clock.seconds() > limit:
            return {"found": found, "missing": sorted(set(wanted) - set(found)), "polled_s": clock.seconds()}
        time.sleep(every)


def by_trace(trace_id: str) -> Callable[[dict[str, Any]], bool]:
    return lambda record: (record.get("requestMetadata") or {}).get("trace_id") == trace_id


# --- CloudTrail ----------------------------------------------------------------------------------------------

def converse_events(cloudtrail: Any, since: datetime, request_ids: Iterable[str]) -> list[dict[str, Any]]:
    """The Converse and InvokeModel events since `since`, the ones whose request ID is one of ours marked."""
    wanted = set(request_ids)
    out = []
    for name in ("Converse", "InvokeModel"):
        token: str | None = None
        for _ in range(20):
            kwargs: dict[str, Any] = {"LookupAttributes": [{"AttributeKey": "EventName", "AttributeValue": name}],
                                      "StartTime": since, "MaxResults": 50}
            if token:
                kwargs["NextToken"] = token
            page = cloudtrail.lookup_events(**kwargs)
            for item in page.get("Events", []):
                event = json.loads(item["CloudTrailEvent"])
                out.append({"event_time": event.get("eventTime"), "event_name": event.get("eventName"),
                            "aws_region": event.get("awsRegion"), "request_id": event.get("requestID"),
                            "ours": event.get("requestID") in wanted, "error_code": event.get("errorCode"),
                            "model_id": (event.get("requestParameters") or {}).get("modelId"),
                            "additional_event_data": event.get("additionalEventData"),
                            "user_identity_type": (event.get("userIdentity") or {}).get("type")})
            token = page.get("NextToken")
            if not token:
                break
    return out


# --- the session's calls -------------------------------------------------------------------------------------

def canada_side(s: Any) -> dict[str, Any]:
    """What ca-central-1 answers this account for anything but a model call (book D-034)."""
    out: dict[str, Any] = {}
    out["get_logging_configuration"] = logging_configuration(s.client("bedrock", region_name="ca-central-1"))
    try:
        s.client("logs", region_name="ca-central-1").describe_log_groups(limit=1)
        out["describe_log_groups"] = {"ok": True}
    except Exception as exc:
        out["describe_log_groups"] = {"ok": False, **cloud_session.aws_error(exc)}
    try:
        s.client("cloudtrail", region_name="ca-central-1").lookup_events(MaxResults=1)
        out["cloudtrail_lookup"] = {"ok": True}
    except Exception as exc:
        out["cloudtrail_lookup"] = {"ok": False, **cloud_session.aws_error(exc)}
    return out


def calls(s: Any, log_group: str, work: Path) -> dict[str, Any]:
    bedrock, logs = s.client("bedrock"), s.client("logs")
    record: dict[str, Any] = {"started": cloud_session.utc(), "clock": cloud_session.CLOCK, "prompt": PROMPT,
                              "log_group": log_group, "canada_side": canada_side(s),
                              "logging_before": logging_configuration(bedrock)}
    since_ms = int(time.time() * 1000) - 60_000
    traces = {name: tracing.new_trace_id() for name in ("canada_ch05", "canada", "us_text_off", "us_text_on", "us_profile")}
    record["trace_ids"] = traces

    # The Canada call, first under chapter 5's W3 manifest, which names ca-central-1 alone, and then under chapter
    # 6's, grown by ca-west-1 because the Canada profile serves from both (labs/ch06/manifests). Chapter 5's rules
    # compare every Region the profile serves from with the manifest's (O-D11), so the first is a refusal.
    record["canada"] = {"path": "gateway, litellm.bedrock-ca.yaml, W3 larkspur-chat (confidential), called in ca-central-1",
                        "attempts": []}
    for label, manifests, trace_key in (("chapter 5's W3 manifest, regions [ca-central-1]", CH05 / "manifest", "canada_ch05"),
                                        ("chapter 6's W3 manifest, regions [ca-central-1, ca-west-1]", LAB.parent / "ch06" / "manifests", "canada")):
        gateway = Gateway(HERE / "litellm.bedrock-ca.yaml", work, manifest_dir=manifests, tag=trace_key).start()
        try:
            call = gateway_call(gateway.url, "larkspur-chat", "w3-incident", "confidential", traces[trace_key])
            time.sleep(2.0)  # chapter 5's callback writes the cost line and the span after the answer has gone back
            lines = gateway.lines_for(traces[trace_key])
        finally:
            gateway.stop()
        record["canada"]["attempts"].append({"manifests": label, "trace_id": traces[trace_key], "call": call, "gateway": lines})
    record["canada"]["call"] = record["canada"]["attempts"][-1]["call"]
    record["canada"]["gateway"] = record["canada"]["attempts"][-1]["gateway"]

    gateway = Gateway(HERE / "litellm.bedrock-us.yaml", work).start()
    clock = cloud_session.Clock()
    try:
        record["us_text_off"] = {"path": "gateway, litellm.bedrock-us.yaml, W2 larkspur-chat (internal), Nova Lite In-Region us-east-2",
                                 "text_delivery": False,
                                 "call": gateway_call(gateway.url, "larkspur-chat", "w2-ops-assistant", "internal", traces["us_text_off"])}
        record["us_text_off"]["log"] = wait_for_records(logs, log_group, since_ms, {"record": by_trace(traces["us_text_off"])}, clock)
        record["text_delivery_on"] = set_text_delivery(bedrock, True)
        clock_on = cloud_session.Clock()
        record["us_text_on"] = {"path": record["us_text_off"]["path"], "text_delivery": True,
                                "call": gateway_call(gateway.url, "larkspur-chat", "w2-ops-assistant", "internal", traces["us_text_on"])}
        record["us_text_on"]["log"] = wait_for_records(logs, log_group, since_ms, {"record": by_trace(traces["us_text_on"])}, clock_on)
        time.sleep(2.0)
        for name in ("us_text_off", "us_text_on"):
            record[name]["gateway"] = gateway.lines_for(traces[name])
    finally:
        gateway.stop()

    clock_us = cloud_session.Clock()
    record["us_profile"] = {"path": f"the SDK's Converse in us-east-2 on {US_PROFILE}, with the same requestMetadata",
                            "call": direct_converse(s, "us-east-2", US_PROFILE, traces["us_profile"], "w2-ops-assistant")}
    if record["us_profile"]["call"].get("ok"):
        record["us_profile"]["log"] = wait_for_records(logs, log_group, since_ms, {"record": by_trace(traces["us_profile"])}, clock_us)
    record["text_delivery_off_again"] = set_text_delivery(bedrock, False)
    for name in ("us_text_off", "us_text_on", "us_profile"):
        found = record.get(name, {}).get("log", {}).get("found", {}).get("record")
        if found:
            record[name]["record_shape"] = record_shape(found["record"])
    record["ended"] = cloud_session.utc()
    return record


def cloudtrail(s: Any, record: dict[str, Any], limit: float = 900.0, every: float = 30.0) -> dict[str, Any]:
    """The calls' events in us-east-2's event history, polled until the US ones are there or the limit."""
    since = datetime.fromisoformat(record["started"]).astimezone(timezone.utc)
    wanted: dict[str, str] = {}
    for name in ("us_text_off", "us_text_on", "us_profile"):
        request_id = (record.get(name, {}).get("record_shape") or {}).get("request_id") \
            or record.get(name, {}).get("call", {}).get("request_id")
        if request_id:
            wanted[name] = request_id
    clock = cloud_session.Clock()
    trail = s.client("cloudtrail")
    while True:
        events = converse_events(trail, since, wanted.values())
        ours = {name: next((e for e in events if e["request_id"] == rid), None) for name, rid in wanted.items()}
        if all(ours.values()) or clock.seconds() > limit:
            break
        time.sleep(every)
    out: dict[str, Any] = {"polled_s": clock.seconds(), "events_in_window": len(events), "ours": {}}
    for name, event in ours.items():
        log_region = (record.get(name, {}).get("record_shape") or {}).get("inference_region")
        out["ours"][name] = {"found": event is not None, "event": event,
                             "inference_region_cloudtrail": (event or {}).get("additional_event_data", {}).get("inferenceRegion") if event else None,
                             "inference_region_log": log_region,
                             "request_id_matches_log": event is not None and event["request_id"] == wanted[name]}
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("action", choices=("calls", "cloudtrail"))
    parser.add_argument("--out", type=Path, default=cloud_session.results_dir())
    parser.add_argument("--work", type=Path, default=cloud_session.SCRATCH / "bedrock")
    parser.add_argument("--log-group", help="the invocation log group (default: the Terraform output)")
    args = parser.parse_args(argv)
    cloud_session.require_environment()
    s = cloud_session.session()
    path = args.out / "bedrock.json"
    if args.action == "calls":
        args.work.mkdir(parents=True, exist_ok=True)
        group = args.log_group or cloud_session.terraform_outputs()["invocation_log_group"]
        record = calls(s, group, args.work)
        cloud_session.merge_json(path, "calls", record)
        for name in ("canada", "us_text_off", "us_text_on", "us_profile"):
            call = record[name]["call"]
            print(f"{name}: ok={call.get('ok')} tokens={call.get('prompt_tokens', (call.get('usage') or {}).get('inputTokens'))}"
                  f"/{call.get('completion_tokens', (call.get('usage') or {}).get('outputTokens'))} "
                  f"log={'found' if record[name].get('log', {}).get('found') else 'none'}")
    else:
        record = cloud_session.read_json(path)["calls"]
        out = cloudtrail(s, record)
        cloud_session.merge_json(path, "cloudtrail", out)
        for name, item in out["ours"].items():
            print(f"{name}: found={item['found']} inferenceRegion={item['inference_region_cloudtrail']} "
                  f"log={item['inference_region_log']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
