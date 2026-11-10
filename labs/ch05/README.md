# Lab, chapter 5: the skeleton, local only

The chapter 5 skeleton, in four parts.

- Part 1 has a read-only MCP server over a fake Kubernetes namespace, under a scoped identity, and a
  harness that runs the chapter 1 agent loop with that server's tools behind it.
- Part 2 has two A2A agents that use the harness and authenticate to each other, a tracing hook that
  puts every component in one OpenTelemetry trace, and a golden set with a runner.
- Part 3 is the model gateway: a LiteLLM proxy in front of three fake model backends, with the
  workflow manifest, the data-class grid, per-run budgets, a cost line and a span in a callback, and
  the harness's model calls routed through it.
- Part 4 is the runtime adapter: the few dozen lines that serve the AgentCore, Google Agent Runtime
  and Foundry container contracts in front of the same harness.

Everything is local: no cloud, no model API, no network listener beyond 127.0.0.1.

```
mcp-server/
  server.py          part 1: two read-only tools, stdio and Streamable HTTP, one span per call
  fake_platform.py   in-memory fake of the larkspur-prod namespace and its alert store, typed results
  tools.lock.json    SHA-256 of every tool definition; the server refuses to start if one drifts
harness/
  client.py          part 1: connects, verifies the lock, runs labs/ch01/agent_loop.py with an allowlist
  rule_model.py      part 2: a rule-based stand-in for the model that answers real questions
  gateway_model.py   part 3: the loop's model as a Chat Completions call through the gateway
a2a/
  analyst.py         part 2: A2A server agent; "summarize the alerts for <service>" via the harness
  scribe.py          part 2: A2A client agent; discovers analyst, sends the task, writes the artifact
  agent_common.py    the identity rule, the tokens and the metadata keys both agents share
tracing/
  trace_setup.py     part 2: OpenTelemetry setup used by every process above
  semconv-genai/     a pinned copy of the GenAI conventions registry the naming test checks against
golden/
  golden-set.yaml    part 2: 20 questions with expected tool calls and answers
  run_golden.py      runs the harness over the set, prints the pass rate; --gateway routes the model
manifest/
  schema.json        part 3: the workflow manifest (JSON Schema)
  w2-ops-assistant.yaml, w3-incident.yaml   the two manifests the gateway enforces
gateway/
  litellm.config.yaml  part 3: three aliases, where each deployment serves, the fallback chain
  gateway_rules.py     part 3: the manifest, the grid, the fallback check and the limits, as pure functions
  gateway_hooks.py     part 3: the LiteLLM callback around them: refusals, cost line, span
  fake_backend.py      part 3: an OpenAI-compatible fake endpoint that can be told to fail
  run_demo.py          part 3: starts everything, makes six calls, prints the gateway log, stops
adapter/
  runtime_adapter.py   part 4: the three managed-runtime contracts in front of the harness
tests/               pytest, 173 tests
requirements.txt     exact versions
```

## Setup

```
cd labs/ch05
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```

On Windows, use `py -3.12 -m venv .venv` and `.venv\Scripts\activate`, and set `PYTHONUTF8=1` in the
shell first. The proxy prints a banner that a cp1252 console cannot encode, and so is any path with
non-ASCII characters in it.

**Licenses.** Everything the lab installs is open source. The one exception is easy to install by
accident: `pip install "litellm[proxy]"` also installs `litellm-enterprise`, whose license is
proprietary. `requirements.txt` lists LiteLLM without that extra, and the proxy runs without the
package. The copy of the GenAI conventions registry in `tracing/semconv-genai`
is Apache 2.0, with its license next to it.

# Part 1: the MCP server and the harness

## Run over stdio

The harness launches `server.py` as a subprocess. The identity is required; without it the server
does not start and the harness fails on connect.

```
cd labs/ch05
TOOL_IDENTITY=larkspur-ops-reader python harness/client.py --trace-id demo0001
```

Expected output. Both logs go to stderr (timestamps will differ); the answer goes to stdout:

```
{"ts": "...", "event": "tracing", "exporter": "JsonLinesSpanExporter", "destination": ".../labs/ch05/traces.jsonl"}
{"ts": "...", "event": "server_start", "identity": "larkspur-ops-reader", "transport": "stdio", "tools": {"get_pod_status": "94183d02f2e8", "get_recent_alerts": "8e9ceceb650d"}, "lock": ".../labs/ch05/mcp-server/tools.lock.json", "tracing": ".../labs/ch05/traces.jsonl"}
{"ts": "...", "event": "tools_verified", "trace_id": "demo0001", "transport": "stdio", "tools": {"get_pod_status": "94183d02f2e8", "get_recent_alerts": "8e9ceceb650d"}, "lock": ".../labs/ch05/mcp-server/tools.lock.json"}
{"ts": "...", "event": "tool_call", "trace_id": "demo0001", "trace_source": "request", "tool": "get_pod_status", "args": {"service": "claims-api"}, "identity": "larkspur-ops-reader", "transport": "stdio", "ok": true}
{"ts": "...", "event": "tool_call", "trace_id": "demo0001", "tool": "get_pod_status", "args": {"service": "claims-api"}, "transport": "stdio", "ok": true}
{"ts": "...", "event": "answer", "trace_id": "demo0001", "refused": false, "answer": "claims-api has 2 of 3 pods ready."}
claims-api has 2 of 3 pods ready.
```

The second and fourth lines are the server's (they carry `identity`); the others are the harness's.
To keep them apart, send the server log to a file: `TOOL_LOG_FILE=server.log` is passed through to
the subprocess. Spans land in `traces.jsonl` (see Tracing below).

## Run over Streamable HTTP

Terminal 1, the server (binds 127.0.0.1 only; there is no flag to change that):

```
cd labs/ch05
TOOL_IDENTITY=larkspur-ops-reader TOOL_LOG_FILE=server.log python mcp-server/server.py --transport streamable-http --port 8765
```

Terminal 2, the harness:

```
cd labs/ch05
python harness/client.py --url http://127.0.0.1:8765/mcp --trace-id demo0002
```

Expected: the same answer, the harness lines on stderr with `"transport": "http"`, and in
`server.log` a `tool_call` line with `"trace_id": "demo0002"`, `"trace_source": "request"` and
`"transport": "streamable-http"`. Stop the server with Ctrl-C. The HTTP server accepts any local
caller: it has no OAuth resource-server check, which a production MCP server needs (chapter 5 says
what Larkspur put there).

## What to look at

- The server will not start without an identity. `python mcp-server/server.py` with no
  `TOOL_IDENTITY` prints `refusing to start: TOOL_IDENTITY is not set ...` and exits with status 2.
  Every `tool_call` line names the identity the call ran under. This is one identity for the server
  and both its tools; in chapter 6 it becomes a real role.
- Definitions are pinned. The lock holds the SHA-256 of each tool as a client sees it in
  `tools/list`: name, description, input schema, output schema and annotations, hashed as sorted
  JSON. Edit the `get_pod_status` description in `server.py`, add an argument, or drop
  `read_only_hint`, and the server refuses to start with
  `tool definitions do not match tools.lock.json: get_pod_status: definition changed`. If the change is
  intended, run `python mcp-server/server.py --write-lock` and review the diff of `tools.lock.json`,
  which holds the definitions themselves, in the pull request. The harness checks the same lock
  before the model sees a single description, so a server that drifts is refused at both ends.
- Results are typed. The tools return typed dictionaries, so each `outputSchema` names its fields
  (`service`, `ready`, `desired`, `pods`, and an `Alert` with a `severity` of `critical`, `warning` or
  `info`). The MCP client checks results against it. The only `$ref` in the schemas is local; a
  client that resolves a server's `$ref` over the network is how GHSA-rwrf-2pqf-9j8j happened, fixed
  in mcp 1.30.0 and 2.2.0.
- The harness owns the allowlist. The server serves two tools; `ALLOWED` in `client.py` has one,
  and a test checks that it sits inside the W2 manifest. A model that asks for `get_recent_alerts`
  gets `Refused: get_recent_alerts is not an allowed call.` and the server log shows no call.
- The harness puts `trace_id` into the request `_meta`; the server reads
  it (or generates one, and says so with `"trace_source": "generated"`). Join the two logs on
  `trace_id` and you have the call as the client saw it and as the server ran it.

# Part 2: the A2A demo, the tracing hook and the golden set

## Run the A2A demo

The demo runs two agents, each under an identity of its own, in two terminals. The analyst launches the MCP server as a stdio subprocess
under `TOOL_IDENTITY`, so three identities are in play: the scribe asks, the analyst works, the server
reads. The scribe authenticates to the analyst with a bearer token; the analyst knows its callers
from `ANALYST_CALLER_TOKENS`. Pick any long random string for the token and give it to both.

Terminal 1, the analyst (binds 127.0.0.1:8766; `--port` changes the port, nothing changes the host):

```
cd labs/ch05
export SCRIBE_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(24))")
AGENT_IDENTITY=larkspur-analyst TOOL_IDENTITY=larkspur-ops-reader \
  ANALYST_CALLER_TOKENS="larkspur-scribe=$SCRIBE_TOKEN" python a2a/analyst.py
```

Terminal 2, the scribe, with the same token:

```
cd labs/ch05
AGENT_IDENTITY=larkspur-scribe AGENT_TOKEN=<the same token> python a2a/scribe.py \
  --service claims-api --out summary.json --trace-id 0af7651916cd43dd8448eb211c80319c
```

Expected output of the scribe (stderr, then one stdout line; ids will differ except the trace id):

```
{"ts": "...", "event": "agent_start", "agent": "scribe", "identity": "larkspur-scribe", "tracing": ".../labs/ch05/traces.jsonl"}
{"ts": "...", "event": "agent_card", "name": "analyst", "version": "0.1.0", "skills": ["summarize-alerts"], "interfaces": [["JSONRPC", "http://127.0.0.1:8766/"]], "streaming": true, "bearer_schemes": ["larkspur-bearer"]}
{"ts": "...", "event": "task_sent", "text": "Summarize the alerts for claims-api", "trace_id": "0af7651916cd43dd8448eb211c80319c", "agent_identity": "larkspur-scribe", "traceparent": "00-0af7651916cd43dd8448eb211c80319c-<span id>-03"}
{"ts": "...", "event": "task_event", "task_id": "<task id>", "kind": "task", "state": "TASK_STATE_SUBMITTED"}
{"ts": "...", "event": "task_event", "task_id": "<task id>", "kind": "status_update", "state": "TASK_STATE_WORKING"}
{"ts": "...", "event": "task_event", "task_id": "<task id>", "kind": "artifact_update", "state": "TASK_STATE_WORKING"}
{"ts": "...", "event": "task_event", "task_id": "<task id>", "kind": "status_update", "state": "TASK_STATE_COMPLETED"}
{"ts": "...", "event": "artifact_written", "trace_id": "0af7651916cd43dd8448eb211c80319c", "task_id": "<task id>", "final_state": "TASK_STATE_COMPLETED", "path": "summary.json"}
{"trace_id": "0af7651916cd43dd8448eb211c80319c", "final_state": "TASK_STATE_COMPLETED", "states": ["TASK_STATE_SUBMITTED", "TASK_STATE_WORKING", "TASK_STATE_COMPLETED"], "out": "summary.json"}
```

`summary.json` holds the task ids, the states in order, and the artifact: the summary sentence and the
structured data behind it. The sentence is
`claims-api had 2 alerts in the last 60 minutes (1 critical, 1 warning). Latest, 4 minutes ago, critical: KubePodCrashLooping: claims-api-7d9f8b6c4-t8w2c restarted 7 times in 30m`
and the data carries `service`, `window_minutes`, `count`, `by_severity`, the two alerts, `trace_id`,
`produced_by` (the analyst's identity) and `requested_by` (the scribe's).

Meanwhile the analyst's terminal shows `task_received` with `"caller": "larkspur-scribe"` and
`"trace_source": "header"`, the harness lines (`tools_verified`, `tool_call` for `get_recent_alerts`,
`answer`), the server's `server_start` and `tool_call` lines under `"identity": "larkspur-ops-reader"`,
and `task_completed`. Every line that has a `trace_id` has the same one. Add `--minutes 120` to the
scribe to widen the window (3 alerts), or `--service document-ocr` for another service. Stop the
analyst with Ctrl-C.

## What to look at

- Neither agent starts without an identity. `python a2a/analyst.py` with no `AGENT_IDENTITY`
  prints `refusing to start: AGENT_IDENTITY is not set ...` and exits with status 2. The analyst also
  refuses to start without `ANALYST_CALLER_TOKENS`, and when it would have to launch the MCP server
  without `TOOL_IDENTITY`. The scribe refuses without `AGENT_IDENTITY` or `AGENT_TOKEN`.
- The caller is whoever holds the token. The card at
  `http://127.0.0.1:8766/.well-known/agent-card.json` is public and declares one security scheme,
  HTTP bearer. Every other request without a known token gets 401 before the A2A SDK sees it:

  ```
  curl -i -X POST http://127.0.0.1:8766/ -d '{}'
  HTTP/1.1 401 Unauthorized
  {"error":"a bearer token of a known caller is required"}
  ```

  The analyst logs the token's subject as `caller`. A request whose `agent_identity` metadata names
  someone else is rejected: `refused: the request claims to come from 'larkspur-scribe' but its token
  belongs to 'larkspur-other'`. The scribe sends its token only to an agent whose card declares a
  bearer scheme, and only to the origin it fetched the card from: a card is data the other side
  controls, and one that names an interface on another host is refused. Static tokens are a lab stand-in; in production the token is a short-lived JWT from
  the identity provider, checked for signature, issuer, audience and expiry.
- A task whose request metadata has no `trace_id` ends in A2A state
  `REJECTED` with the message
  `refused: request metadata carries no trace_id; the analyst does not run untraced work`. The MCP
  server is never contacted.
- The analyst is allowed one tool. `ALLOWED` in `analyst.py` names `get_recent_alerts` only. A
  task that asks for pod status, or to restart something, is rejected before the harness runs.
- The task has states. The scribe sees `SUBMITTED` (the task object), `WORKING` (the analyst's
  status update, with a progress message), the artifact, then `COMPLETED`, and finally calls `GetTask`
  to fetch the stored task. The analyst keeps tasks in the SDK's `InMemoryTaskStore`, so a restart
  loses them; a task that runs longer than a deploy needs the SDK's database-backed store.

## Tracing

Every process calls `trace_setup.configure(service_name, identity)` at start-up and says where the
spans go. The default is a JSON lines file, `labs/ch05/traces.jsonl` (override with `TRACE_FILE`),
appended to by every process, one span per line. Set `OTEL_EXPORTER_OTLP_ENDPOINT` (for example
`http://127.0.0.1:4318` for a local Jaeger, Grafana Tempo or OpenTelemetry Collector) and the same
spans go there over OTLP/HTTP instead. One exporter per process: to send spans to two backends, point
the processes at a Collector and fan out there.

After the A2A run above, `traces.jsonl` holds eleven spans with the trace id you passed. Read them
innermost first (that is the order spans end):

```
python - <<'EOF'
import json
for line in open("traces.jsonl", encoding="utf-8"):
    s = json.loads(line)
    print(s["trace_id"][:8], s["kind"].ljust(8), s["resource"]["service.name"].ljust(10), s["name"], "|", s["attributes"].get("larkspur.component"))
EOF
```

```
0af76519 SERVER   mcp-server server/discover | None
0af76519 CLIENT   analyst    MCP send server/discover | None
0af76519 SERVER   mcp-server tools/list | None
0af76519 CLIENT   analyst    MCP send tools/list | None
0af76519 INTERNAL mcp-server execute_tool get_recent_alerts | mcp-server
0af76519 SERVER   mcp-server tools/call get_recent_alerts | None
0af76519 CLIENT   analyst    MCP send tools/call get_recent_alerts | None
0af76519 INTERNAL analyst    execute_tool get_recent_alerts | harness
0af76519 INTERNAL analyst    invoke_agent harness | harness
0af76519 SERVER   analyst    invoke_agent analyst | analyst
0af76519 CLIENT   scribe     invoke_agent analyst | scribe
```

How the id travels. The scribe's `invoke_agent analyst` span is the root, a real one with no parent.
Its W3C `traceparent` goes in the HTTP header of every A2A request, which is what A2A asks for, and
also in the request metadata, because the A2A Python SDK 1.3.0 does not read the header into its own
server spans; the analyst reads the header first. The analyst opens its `invoke_agent analyst` span
as a child; the harness runs inside it; the MCP Python SDK (2.3.0) carries the context in `_meta`
(its `MCP send ...` and `tools/call` spans), and the server's own `execute_tool` span sits inside.
The A2A SDK's own spans are off (`OTEL_INSTRUMENTATION_A2A_SDK_ENABLED=false`, set by the two agent
scripts) because they would start a second trace.

A plain string trace id such as `demo0001` still works as a log join key, but it cannot be an
OpenTelemetry trace id (those are 32 lowercase hex characters). Pass one that is, and the first span
of the run adopts it as a real root (an id generator in `trace_setup.py` hands it over), so no span
points at a parent that is not in the file. At a trust boundary, adopt nothing: start a new trace and
record the caller's id, so a caller cannot choose where your spans land.

### What the spans carry, and what they do not

Tool arguments are content: a service name here, a claim number in a real workflow. The GenAI
conventions make `gen_ai.tool.call.arguments` opt-in and warn that it may hold sensitive information,
so the lab leaves it out of spans unless `LARKSPUR_TRACE_TOOL_ARGS=1`, which is what a workflow whose
manifest says `trace_content: true` would set. The JSON logs keep the arguments; they are the audit
record, with their own retention. Prompts, completions and tool results are never put on spans.

### Attribute names

The GenAI conventions moved out of the main OpenTelemetry conventions into their own repository,
`open-telemetry/semantic-conventions-genai`, which had no release on 2026-10-29. The lab pins a commit
of its registry in `tracing/semconv-genai` (see `SOURCE.md` there), and `test_tracing.py` checks every
name below against it: present, still "development", not deprecated. Refresh the copy and a rename
shows up as a failing test.

| Attribute | Used on | Status |
|---|---|---|
| `gen_ai.operation.name` (`invoke_agent`, `execute_tool`, `chat`) | every lab span; also the span name prefix | development |
| `gen_ai.agent.name`, `gen_ai.agent.description` | scribe, analyst, harness spans | development |
| `gen_ai.conversation.id` (the A2A context id) | analyst span | development |
| `gen_ai.provider.name`, `gen_ai.request.model` | harness span; `gen_ai.request.model` also on the gateway span (the alias asked for) | development |
| `gen_ai.response.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens` | gateway span | development |
| `gen_ai.tool.name`, `gen_ai.tool.type` (`function`) | the two `execute_tool` spans | development |
| `gen_ai.tool.call.arguments` | the two `execute_tool` spans, only with `LARKSPUR_TRACE_TOOL_ARGS=1` | development, opt-in |
| `a2a.task.id` | scribe and analyst spans | development (A2A conventions, same repository) |
| `service.name`, `service.namespace` | resource of every process | stable |
| `server.address`, `server.port` | scribe span | stable |
| `error.type` | any span that failed or was refused | stable |
| `larkspur.identity`, `larkspur.caller_identity`, `larkspur.component`, `larkspur.trace_id`, `larkspur.refused`, `larkspur.workflow`, `larkspur.data_class`, `larkspur.region`, `larkspur.deployment`, `larkspur.served_alias`, `larkspur.fallback`, `larkspur.cost_usd` | lab-specific; no convention exists | none |

## The golden set

`golden/golden-set.yaml` has 20 cases over the fake namespace: nine `get_pod_status` questions (one for
a service that does not exist), ten `get_recent_alerts` questions with different windows, and one
request to scale a deployment, for which the right answer is no tool call. Each case records the
question, the expected tool call (name and arguments) and the exact expected answer. The runner feeds
every question to the part 1 harness with `rule_model.py` as the model and both tools allowed, and a
case passes only if the logged tool call and the answer both match.

```
cd labs/ch05
python golden/run_golden.py
```

Expected output (an in-process server; `--stdio` launches `server.py` per case under `TOOL_IDENTITY`,
`--url` uses a running HTTP server, `--gateway` sends every model call through the gateway of part 3,
`--json report.json` writes the full report):

```
PASS  pods-claims-api
PASS  pods-policy-admin
...
PASS  refuse-scale
pass rate: 20/20 (100.0%)
```

Exit status 0 means 100 percent. Change one expected answer in the YAML and run it again: the case
shows `FAIL` with the mismatch and the pass rate drops to 19/20. With a rule-based model the set is a
regression test for the tools, the lock, the harness and the gateway. Chapter 9 puts a local model
behind the same set, and chapter 15 replaces exact match on the prose with a judge.

# Part 3: the model gateway

LiteLLM's proxy (the MIT core, no database) in front of three fake OpenAI-compatible backends, with
the gateway's own rules in a callback. `gateway/litellm.config.yaml` exposes three aliases:
`larkspur-chat` (a managed model in ca-central-1), `larkspur-chat-fallback` (the same model family in
us-east-2, reached only by failover) and `larkspur-chat-restricted` (the self-hosted model of chapter
9, in Canada). Each deployment declares in `model_info` its Region, its jurisdiction and whether it is
managed or self-hosted. The rules, in `gateway_rules.py`, read that and the manifests:

1. A request carries `workflow:` and `data_class:` tags and a `trace_id` in its
   metadata. The workflow needs a manifest in `manifest/`, the alias must be one of its `models`, and
   the data class may not exceed its `data_class_max`.
2. Chapter 2's data-class grid, read against where every deployment behind the alias
   actually serves: Internal may cross a border because the gateway logs the serving Region,
   Confidential stays in Canada, Restricted goes only to the self-hosted model. Every deployment must
   also sit in a Region the manifest's `regions` list allows. Otherwise the request is refused.
3. The same test runs on the fallback chain: on every alias a failover could reach, through every
   kind of fallback the config declares. A hop that fails it does not refuse the request; the
   request runs with fallbacks disabled for that one call, so a failover never carries a prompt
   somewhere it could not have been sent directly. Fallback lists in the request body are removed
   first, because LiteLLM's router would otherwise take them from the caller.
4. Limits: a budget per run (summed by trace id from the cost LiteLLM computes) and, when the
   manifest sets one, requests per minute per workflow. Both fail closed with 429. Both live in the
   proxy's memory, so two proxies mean two budgets; a fleet keeps the counters in Redis.
   The incident workflow sets a rate too, because its Restricted calls go to the self-hosted
   alias, which costs nothing per token, so a dollar budget alone would never stop a loop there.
5. A request to an alias whose deployments are all self-hosted gets a
   `cache_salt` naming the workflow, so two workflows on the same vLLM replicas never share
   cached prompt prefixes. Whatever salt the caller sent is removed, and a managed alias never
   receives one.

`gateway_hooks.py` calls the rules from LiteLLM, writes one JSON line per decision and per call, and
emits a `chat <alias>` span per call in the caller's trace.

## Run the demo

```
cd labs/ch05
python gateway/run_demo.py
```

The script starts the three backends and the proxy, makes six calls, prints the log and stops
everything. The proxy takes ten to twenty seconds to come up. Expected output (the port, the
latencies and the trace ids are the demo's own):

```
gateway up on http://127.0.0.1:55489; cost log at .../labs/ch05/gateway.log

routed     200  [primary] Is claims-api healthy?  cost=$0.000069
fallback   200  [fallback] Is policy-admin healthy?  cost=$0.000069
no-exit    503  litellm.ServiceUnavailableError: ServiceUnavailableError: OpenAIException - primary is failing on purpose
untagged   400  request refused: missing workflow, data_class, trace_id in metadata
managed    400  request refused: data class 'restricted' may not go to 'larkspur-chat' (managed, ca-central-1, CA)
self-host  200  [self-hosted] Summarize this claim file  cost=$0.000009

gateway.log:
  {"event": "call", "trace_id": "0af7...", "workflow": "w2-ops-assistant", "data_class": "internal", "requested_alias": "larkspur-chat", "served_alias": "larkspur-chat", "fallback": false, "fallbacks_disabled": false, "deployment": "primary", "region": "ca-central-1", "served_model": "fake-primary", "prompt_tokens": 3, "completion_tokens": 4, "cost_usd": 6.9e-05, "latency_ms": 693}
  {"event": "failed", "trace_id": "1af7...", "workflow": "w2-ops-assistant", "data_class": "internal", "requested_alias": "larkspur-chat", "served_alias": "larkspur-chat", "fallback": false, "fallbacks_disabled": false, "deployment": "primary", "region": "ca-central-1", "served_model": "fake-primary", "error": "ServiceUnavailableError", "message": "..."}
  {"event": "call", "trace_id": "1af7...", "workflow": "w2-ops-assistant", "data_class": "internal", "requested_alias": "larkspur-chat", "served_alias": "larkspur-chat-fallback", "fallback": true, "fallbacks_disabled": false, "deployment": "fallback", "region": "us-east-2", "served_model": "fake-fallback", "prompt_tokens": 3, "completion_tokens": 4, "cost_usd": 6.9e-05, "latency_ms": 2}
  {"event": "fallback_disabled", "alias": "larkspur-chat", "trace_id": "2af7...", "tags": {"workflow": "w3-incident", "data_class": "confidential"}, "reason": "fallback to 'larkspur-chat-fallback' disabled for this request: data class 'confidential' may not go to 'larkspur-chat-fallback' (managed, us-east-2, US)"}
  {"event": "failed", "trace_id": "2af7...", "workflow": "w3-incident", "data_class": "confidential", "requested_alias": "larkspur-chat", "served_alias": "larkspur-chat", "fallback": false, "fallbacks_disabled": true, "deployment": "primary", "region": "ca-central-1", "served_model": "fake-primary", "error": "ServiceUnavailableError", "message": "..."}
  {"event": "refused", "alias": "larkspur-chat", "trace_id": null, "tags": {}, "reason": "request refused: missing workflow, data_class, trace_id in metadata"}
  {"event": "refused", "alias": "larkspur-chat", "trace_id": "0af7...", "tags": {"workflow": "w3-incident", "data_class": "restricted"}, "reason": "request refused: data class 'restricted' may not go to 'larkspur-chat' (managed, ca-central-1, CA)"}
  {"event": "call", "trace_id": "3af7...", "workflow": "w3-incident", "data_class": "restricted", "requested_alias": "larkspur-chat-restricted", "served_alias": "larkspur-chat-restricted", "fallback": false, "fallbacks_disabled": false, "deployment": "self-hosted", "region": "ca-central-1", "served_model": "fake-self-hosted", "prompt_tokens": 4, "completion_tokens": 5, "cost_usd": 9e-06, "latency_ms": 0}
```

## What to look at

- The alias is the contract, and a remap is a model change. A workflow asks for `larkspur-chat`
  and never names a deployment, a Region or a provider. An alias the manifest does not list (`gpt-4o`,
  say) is refused. Pointing an alias at another model is a change to this file, and the cost line and
  the span record `served_model` and `region` on every call, so the change shows. Chapter 5 says why
  Larkspur treats that change as a model change, with a golden-set rerun before it ships.
- A failover stays inside the workflow's bounds. With the primary told to fail
  (`POST /control {"fail": true}` on port 8801), W2's Internal request is served by `[fallback]` in
  us-east-2, and the line says `"fallback": true` with the serving alias and Region. W3's
  Confidential request on the same alias gets the error instead: its manifest allows only
  ca-central-1, the grid keeps Confidential in Canada, and the `fallback_disabled` line says which.
- Refusals happen before the call leaves, from the metadata alone. The hook never reads the
  prompt. That is also its limit: behind one master key, any caller can write any tag, including
  `data_class:public` on a prompt full of claim numbers. Binding a workflow and its maximum data class
  to a key needs LiteLLM's database (virtual keys) or its enterprise JWT auth.
- Every served call has a price, an owner and a place. `cost_usd` comes from the per-token prices
  in the config (stand-ins, not rates), `workflow` from the tag, `region` from the deployment, and
  `trace_id` from the metadata, so the line joins the traces and logs of parts 1 and 2 on the same id.
- The harness's model goes through it too. `python golden/run_golden.py --gateway <url>` runs the
  golden set with every model call sent through the proxy as a Chat Completions request with tool
  calls. The fake backends answer tool-carrying requests with the rule model, so the set still passes
  20/20, and each run's trace holds the harness's `invoke_agent` span with two `chat larkspur-chat`
  spans from the gateway under it.

## Run it by hand

Five terminals, from `labs/ch05`. `LITELLM_MASTER_KEY` must be set for the proxy and for the
callers; any local value will do.

```
python gateway/fake_backend.py --name primary --port 8801
python gateway/fake_backend.py --name fallback --port 8802
python gateway/fake_backend.py --name self-hosted --port 8803
cd gateway && LITELLM_MASTER_KEY=sk-local-only litellm --config litellm.config.yaml --host 127.0.0.1 --port 4010
```

The proxy listens on every interface unless given `--host`. Then one request, with the metadata the
hook requires:

```
curl -s http://127.0.0.1:4010/chat/completions -H "Authorization: Bearer sk-local-only" \
  -H "Content-Type: application/json" -d '{"model": "larkspur-chat",
  "messages": [{"role": "user", "content": "Is claims-api healthy?"}],
  "metadata": {"tags": ["workflow:w2-ops-assistant", "data_class:internal"], "trace_id": "0af7651916cd43dd8448eb211c80319c"}}'
```

The answer is `[primary] Is claims-api healthy?`, the response carries an `x-litellm-response-cost`
header, and `labs/ch05/gateway.log` gains one `call` line. With the proxy up, the golden set through
the gateway is

```
LITELLM_MASTER_KEY=sk-local-only python golden/run_golden.py --gateway http://127.0.0.1:4010
```

# Part 4: the runtime adapter

`adapter/runtime_adapter.py` is the only per-cloud code in the skeleton. It serves the HTTP contract
each managed runtime expects of an agent's container and hands the question to the part 1 harness:

| `--runtime` | Port | Health | Request | Response |
|---|---|---|---|---|
| `agentcore` | 8080 | `GET /ping` | `POST /invocations {"prompt": ...}`; a body without a prompt is a 400, an engineer other than the session's first a 403 | `{"response": ..., "status": "success"}` |
| `agent-runtime` (Google) | 8080 | none required | `POST /api/reasoning_engine {"class_method": "query", "input": {"message": ...}}` | `{"output": ...}` |
| `foundry` | 8088 | `GET /readiness` | `POST /invocations {"message": ...}`; a body without a message is a 400, a user other than the sandbox's first a 403 | `{"output": ...}`, with `x-agent-session-id` |

On AgentCore the engineer is the `oid` (else `sub`) of the Entra token the runtime validated and
passed through, and the session id, the request id and the engineer go on every audit line. The
workload access token AgentCore adds stays in `WORKLOAD_TOKEN` for that request only, for chapter
6's token vault, and is never logged. AgentCore "does not enforce session-to-user mappings", so a
session keeps to its first engineer, as a Foundry sandbox does.

The shapes are from the vendors' contract pages, read on 2026-10-29. Foundry's other protocol,
`POST /responses`, implements the OpenAI Responses API and is the one Microsoft recommends; its SDK
adapter handles history and streaming. None of the streaming variants is served here.

```
TOOL_IDENTITY=larkspur-ops-reader python adapter/runtime_adapter.py --runtime agentcore
curl -s localhost:8080/ping
curl -s localhost:8080/invocations -d '{"prompt": "Is claims-api healthy?"}'
```

```
{"status":"Healthy"}
{"response":"claims-api has 2 of 3 pods ready. Not ready: claims-api-7d9f8b6c4-t8w2c (CrashLoopBackOff, 7 restarts).","status":"success"}
```

Inside a cloud the container binds 0.0.0.0 on the runtime's port and the runtime is its only caller;
on a laptop the adapter binds 127.0.0.1. Everything behind the handler is the same on every runtime,
including the allowlist: ask the Foundry adapter about alerts and the answer is
`Refused: get_recent_alerts is not an allowed call.`, because the harness allows one tool wherever it
runs. A caller's `traceparent` header parents the run.

Foundry asks for more than the table shows. The response carries `x-agent-session-id`, the session
the request ran in, so a caller that let Foundry create the session can send it back as
`?agent_session_id=` and reach the same sandbox. The platform's `x-agent-user-id`, its identifier
for the caller, goes on every audit line of the run. On SIGTERM, on every runtime, the requests in
flight finish and the process exits normally, so the spans still waiting in the batch are sent.

A Foundry sandbox serves one user. Within delegation the platform "doesn't fence one delegated end
user from another" (Isolate hosted agent sessions per user, 2026-10-13), and chapter 4 never reuses
a session across people, so the adapter writes the first `x-agent-user-id` a sandbox sees to
`$HOME/.x-agent-user-id`. `$HOME` is the session's storage, which the platform keeps for the
session's life. A request that carries another user id gets a 403 without the harness running, and
stderr gets a `refused` line with both ids. A request without the header is served and pins nothing,
because Microsoft doesn't guarantee the platform's headers when the container runs locally. The pin
works per engineer when the caller delegates with `x-ms-user-identity`, so that the header carries
the engineer's identity. It can't stop someone who can already upload files into the session, since
uploads land under `$HOME` as well. `SESSION_STORAGE_DIR` moves the record out of `$HOME`; the tests
set it.

# What the lab leaves out

- An ingress in front of the gateway: LiteLLM also serves pass-through routes (`/vllm/...`,
  `/anthropic/...` and others) that forward a request without calling the pre-call hook. Against a
  vLLM deployment, a request to `/vllm/chat/completions` with no metadata was served; against the
  lab's own deployments that route fails. In front of a real gateway, the load balancer forwards
  only the chat and health routes.
- Authentication of the MCP HTTP server and of the gateway's callers: the MCP server accepts any
  local caller, and the gateway trusts the tags behind one master key. The A2A agents authenticate
  each other with static bearer tokens. Each needs the identity provider of chapter 6.
- An approval gate: both tools are read-only, so nothing here needs one. The chapter 4 lab has the
  approval token, and the incident workflow of chapter 12 puts it in front of the first write tool,
  together with the idempotency key that makes a retried restart restart once.
- State that survives a restart: budgets and rate counters live in the proxy's memory, tasks in
  the analyst's. A fleet needs Redis for the first and the SDK's database-backed store for the second.
- A real model: the tests use the fake backends. Chapter 9 runs the golden set against a local
  model; chapter 15 adds the judge.

## Test

```
cd labs/ch05
python -m pytest tests -q
```

173 tests, about a minute and a half. They start their own processes: one LiteLLM proxy and its three fake
backends for the whole session (ports 8801 to 8803 must be free), one analyst on a free port, and MCP
servers as stdio subprocesses. The golden pass rate is printed in the pytest summary under
`golden set`.

| File | What it proves |
|---|---|
| `test_server.py` | the identity rule; the lock covers description, schemas and annotations; key order does not change a hash; refusal at start-up |
| `test_harness.py` | the allowlist; refusal of a server whose description or schema drifted; one trace id in both logs |
| `test_tracing.py` | exporter selection; the JSON lines format; four processes appending to one file without splitting a line; a real root for an adopted trace id; `traceparent` round trip; names against the pinned registry; opt-in arguments |
| `test_golden.py` | the set is well formed; 100 percent with the rule model; a wrong expectation is counted |
| `test_a2a.py` | the task runs to completion; the card declares bearer auth; 401 without a known token; a mismatched identity claim is rejected; no token for a card that points elsewhere; the trace context arrives by header; one trace across four components |
| `test_manifest.py` | the schema; the two manifests; the harness allowlist inside the W2 manifest |
| `test_gateway_rules.py` | the grid by row; every refusal reason; the fallback check; budgets and rate limits; the fallback flag (chapter 6's `labs/ch06/tests/test_gateway_aws.py` adds a deployment that serves from two Regions, `serves_from`) |
| `test_gateway.py` | the same rules through the real proxy, including a failover that does not leave Canada, a 429, the span with and without a `traceparent`, and the routing a caller cannot steer |
| `test_gateway_model.py` | the adapter between the loop and Chat Completions |
| `test_skeleton.py` | the golden set through the gateway; one trace across harness, gateway and server |
| `test_runtime_adapter.py` | the three runtime contracts; Foundry's session headers, caller id and 400s; one user per Foundry sandbox, kept across a restart, with nothing pinned when the header is missing; AgentCore's 400s, the session, request and engineer on every audit line, the engineer from the token's `oid` or `sub`, one engineer per session, the workload token for one request and never logged; the caller's trace context and the audit log; the last spans sent on SIGTERM; `build_app`, the per-runtime code, stays under fifty lines |

## Cost and teardown

Nothing is created outside the repository folder unless you send the Foundry adapter an
`x-agent-user-id` header: it records the first one in `$HOME/.x-agent-user-id`, or under
`SESSION_STORAGE_DIR` when that is set, so delete the file after such a run. The tests keep it in a
temporary folder. The runs write `traces.jsonl`, `summary.json`,
`gateway.log`, `server.log` (the HTTP run) and `report.json` (`--json`) into `labs/ch05`; all are
git-ignored, so delete them when you are done. The analyst, the HTTP server, the adapter, the fake
backends and the proxy listen on 127.0.0.1 until you stop them. There is nothing to tear down.

Last run: 2026-10-29 on Windows 11 with Python 3.12.9, in a fresh virtual environment built from
`requirements.txt` without `litellm-enterprise`. Every pinned package except pywin32 (Windows only)
has a CPython 3.12 x86-64 Linux wheel on PyPI, checked the same day. The suite first ran on Linux on
2 November 2026, on Ubuntu 24.04 in the companion's `labs` workflow (173 passed), once `uvloop` joined
the pins for that platform: litellm's proxy picks the uvloop event loop everywhere but Windows, and a
freeze taken on Windows could not have held it. mcp 2.3.0
(Model Context Protocol Python SDK, protocol version 2026-07-28 negotiated), a2a-sdk 1.3.0 (A2A
protocol version 1.0, JSON-RPC binding), opentelemetry-sdk 1.45.1, litellm 1.106.6 with fastapi
0.162.0, PyYAML 6.0.3, jsonschema 4.26.0, pytest 9.2.0, uvicorn 0.54.0. Full list in `requirements.txt`.
