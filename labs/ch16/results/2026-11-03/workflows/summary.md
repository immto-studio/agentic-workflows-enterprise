# Chapter 16, step 3b: the workflows on the local models through the Collector

Every table below is computed by `collector/analyze_workflows.py --summarize` from the files in this folder and the runs' results in each workflow's `eval/traced/2026-11-03/`. The runs are `collector/run_workflows.py`: each workflow's own harness, servers and gateway on a local model, every process sending OTLP to the pinned Collector running `collector/config.yaml` with CloudWatch and Langfuse off.

## The runs

|Run |Ollama |Cases |Passed |Model calls |Input tokens |Output tokens |Model time (s) |Run (s) |Share of the rest |decision_wait |Root trigger |
|---|---|---|---|---|---|---|---|---|---|---|---|
|W2, gpt-oss-20b |Ollama 0.22.1 on 11434, serving gpt-oss-20b |25 |21 |49 |47,588 |6,438 |46.6 |57.8 |100% |30 s |off |
|W3, gpt-oss-20b |Ollama 0.22.1 on 11434, serving gpt-oss-20b |24 |14 |142 |232,833 |16,130 |128.1 |163.1 |100% |30 s |off |
|W4, gpt-oss-20b |Ollama 0.22.1 on 11434, serving gpt-oss-20b |8 |8 |8 |1,541 |1,570 |15.9 |24.2 |100% |30 s |off |
|W4, gemma4-12b |Ollama 0.40.13 on 11435, serving gemma4-12b with its thinking off |8 |8 |8 |1,118 |207 |1.9 |10.1 |100% |30 s |off |
|W5, decision_wait 30 s |Ollama 0.22.1 on 11434, serving gpt-oss-20b |1 |1 |14 |8,844 |8,134 |51.3 |54.9 |10% |30 s |off |
|W5, root trigger |Ollama 0.22.1 on 11434, serving gpt-oss-20b |1 |1 |14 |8,844 |8,134 |51.2 |54.6 |10% |300 s |10s |
|all | | | |235 |300,768 |40,613 |295.0 |364.7 | | | |

Model time is the gateway's latency summed over its calls, the time the GPU spent on them. A run's time is its cases' own, as each workflow's record keeps them, summed.

## Which processes sent spans

|Run |Process |service.name |Spans sent |Kept in the span file |
|---|---|---|---|---|
|W2, gpt-oss-20b |the harness, in this process (eval/answer_eval.py) |w2-harness |224 |224 |
|W2, gpt-oss-20b |the kubernetes MCP server (servers/kubernetes_server.py) |larkspur-ops-kubernetes |90 |90 |
|W2, gpt-oss-20b |the metrics MCP server (servers/metrics_server.py) |larkspur-ops-metrics |60 |60 |
|W2, gpt-oss-20b |the logs MCP server (servers/logs_server.py) |larkspur-ops-logs |50 |50 |
|W2, gpt-oss-20b |the gateway (LiteLLM with chapter 5's callback, gateway/litellm.config.yaml) |gateway |49 |49 |
|W2, gpt-oss-20b |Ollama 0.22.1 on 11434, serving gpt-oss-20b |none |0 |0 |
|W3, gpt-oss-20b |the harness and the approval service, in this process (eval/lab.py) |w3-harness |480 |480 |
|W3, gpt-oss-20b |the kubernetes MCP server |larkspur-ops-kubernetes |170 |170 |
|W3, gpt-oss-20b |the metrics MCP server |larkspur-ops-metrics |96 |96 |
|W3, gpt-oss-20b |the logs MCP server |larkspur-ops-logs |84 |84 |
|W3, gpt-oss-20b |the writer MCP server |larkspur-ops-writer |52 |52 |
|W3, gpt-oss-20b |the ServiceNow MCP server |larkspur-ops-servicenow |80 |80 |
|W3, gpt-oss-20b |the gateway (LiteLLM with chapter 5's callback, W2's litellm.config.yaml) |gateway |142 |142 |
|W3, gpt-oss-20b |Ollama 0.22.1 on 11434, serving gpt-oss-20b |none |0 |0 |
|W4, gpt-oss-20b |the scribe, in this process (eval/lab.py) |scribe |8 |8 |
|W4, gpt-oss-20b |the analyst A2A server (a2a/analyst.py) |analyst |8 |8 |
|W4, gpt-oss-20b |the risk scorer A2A server (a2a/risk_scorer.py), whose rationale seam calls the gateway |risk-scorer |8 |8 |
|W4, gpt-oss-20b |the gateway (LiteLLM with chapter 5's callback, W4's manifest) |gateway |8 |8 |
|W4, gpt-oss-20b |Ollama 0.22.1 on 11434, serving gpt-oss-20b |none |0 |0 |
|W4, gemma4-12b |the scribe, in this process (eval/lab.py) |scribe |8 |8 |
|W4, gemma4-12b |the analyst A2A server (a2a/analyst.py) |analyst |8 |8 |
|W4, gemma4-12b |the risk scorer A2A server (a2a/risk_scorer.py), whose rationale seam calls the gateway |risk-scorer |8 |8 |
|W4, gemma4-12b |the gateway (LiteLLM with chapter 5's callback, W4's manifest) |gateway |8 |8 |
|W4, gemma4-12b |Ollama 0.40.13 on 11435, serving gemma4-12b with its thinking off |none |0 |0 |
|W5, decision_wait 30 s |the night's harness, in this process (harness/night.py) |w5-night |173 |173 |
|W5, decision_wait 30 s |the state reader (servers/state_reader.py) |larkspur-drift-state |10 |10 |
|W5, decision_wait 30 s |the cloud reader (servers/cloud_reader.py) |larkspur-drift-cloud |140 |140 |
|W5, decision_wait 30 s |the cost reader (servers/cost_reader.py) |larkspur-drift-cost |8 |8 |
|W5, decision_wait 30 s |the policy reader (servers/policy_reader.py) |larkspur-drift-policy |14 |14 |
|W5, decision_wait 30 s |the gateway (LiteLLM with chapter 5's callback, W5's manifest) |gateway |14 |14 |
|W5, decision_wait 30 s |Ollama 0.22.1 on 11434, serving gpt-oss-20b |none |0 |0 |
|W5, root trigger |the night's harness, in this process (harness/night.py) |w5-night |173 |173 |
|W5, root trigger |the state reader (servers/state_reader.py) |larkspur-drift-state |10 |10 |
|W5, root trigger |the cloud reader (servers/cloud_reader.py) |larkspur-drift-cloud |140 |140 |
|W5, root trigger |the cost reader (servers/cost_reader.py) |larkspur-drift-cost |8 |8 |
|W5, root trigger |the policy reader (servers/policy_reader.py) |larkspur-drift-policy |14 |14 |
|W5, root trigger |the gateway (LiteLLM with chapter 5's callback, W5's manifest) |gateway |14 |14 |
|W5, root trigger |Ollama 0.22.1 on 11434, serving gpt-oss-20b |none |0 |0 |

## What a run's trace id holds

For each case, the spans whose trace id is the case's, the roots among them (spans whose parent isn't in the trace), and the case's spans that went elsewhere: spans under another trace id whose `larkspur.trace_id` attribute names the case, with the traces they belong to. The last two columns count the traces at the Collector that name no case at all.

|Run |Cases |With spans under their trace id |Roots per trace (min / median / max) |Cases that are one tree |Cases with spans elsewhere |Traces elsewhere |Spans elsewhere |Traces naming no case |Their spans |
|---|---|---|---|---|---|---|---|---|---|
|W2, gpt-oss-20b |25 |24 |1 / 1 / 1 |24 |0 |0 |0 |0 |0 |
|W3, gpt-oss-20b |24 |24 |1 / 7 / 9 |1 |23 |121 |482 |240 |480 |
|W4, gpt-oss-20b |8 |8 |2 / 2 / 2 |0 |0 |0 |0 |0 |0 |
|W4, gemma4-12b |8 |8 |2 / 2 / 2 |0 |0 |0 |0 |0 |0 |
|W5, decision_wait 30 s |1 |1 |1 / 1 / 1 |1 |0 |0 |0 |0 |0 |
|W5, root trigger |1 |1 |1 / 1 / 1 |1 |0 |0 |0 |0 |0 |

|Run |The roots of the cases' traces |
|---|---|
|W2, gpt-oss-20b |w2-harness: invoke_agent w2-harness (24) |
|W3, gpt-oss-20b |gateway: chat larkspur-chat (133); gateway: chat larkspur-chat-restricted (9) |
|W4, gpt-oss-20b |gateway: chat larkspur-chat (8); scribe: invoke_agent change-management (8) |
|W4, gemma4-12b |gateway: chat larkspur-chat (8); scribe: invoke_agent change-management (8) |
|W5, decision_wait 30 s |w5-night: invoke_agent w5-night (1) |
|W5, root trigger |w5-night: invoke_agent w5-night (1) |

## At config.yaml's 10 percent

W2, W3 and W4 ran with the share of the rest at 100 percent, so every trace was kept. What 10 percent would keep, computed trace by trace with `collector/policies.py`:

|Run |Traces |Kept at 10% |By policy |Spans kept |Cases with spans |Kept whole |Kept in part |Kept not at all |
|---|---|---|---|---|---|---|---|---|
|W2, gpt-oss-20b |24 |6 |failed 4, share-of-the-rest 2 |111 of 473 |24 |6 |0 |18 |
|W3, gpt-oss-20b |385 |39 |failed 1, share-of-the-rest 35, slow 3 |128 of 1104 |24 |0 |11 |13 |
|W4, gpt-oss-20b |8 |1 |share-of-the-rest 1 |4 of 32 |8 |1 |0 |7 |
|W4, gemma4-12b |8 |1 |share-of-the-rest 1 |4 of 32 |8 |1 |0 |7 |

## W5's night under the two settings

One night each, the same fixture night on gpt-oss-20b, at config.yaml's 10 percent. Times are seconds at the Collector: when a span reached the tap, before any processor, and when it reached the sink, beside the span file, after the sampler.

|Setting |Night (s) |Spans sent |Kept |Policy recorded |Share recorded |First span in to first out |Root in, after the first span |Root in to root out |Spans in before the first left |Their decision |The whole trace's decision |Held per span (min / median / max) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
|decision_wait 30 s |54.9 |359 |359 |slow |1 |30.5 |58.0 |0.1 |352 |kept by slow |kept by slow |0 / 27.6 / 30.5 |
|decision_wait 300 s, root trigger 10s |54.7 |359 |359 |slow |1 |68.4 |57.9 |10.5 |359 (root among them) |kept by slow |kept by slow |10.4 / 65.6 / 68.4 |

## fig-16-01

W2's w2-01, "Is claims-api healthy?", on gpt-oss-20b: 2 model calls and 1 read, 2.58 s, trace `3601c1d046e346ff8c20b5d7c08e6c9d`. `join.py 3601c1d046e346ff8c20b5d7c08e6c9d --stores results/2026-11-03/workflows/w2` prints:

```
trace 3601c1d046e346ff8c20b5d7c08e6c9d

harness log: 5 records
  {"ts": "2026-11-03T21:22:28.773+00:00", "event": "tools_verified", "trace_id": "3601c1d046e346ff8c20b5d7c08e6c9d", "workflow": "w2-ops-assistant", "case": "w2-01", "persona": "oncall.engineer", "server": "kubernetes-mcp", "tools": {"get_pod_status": "c64470f5a52b", "get_recent_alerts": "502afe3a8c2d", "get_recent_events": "cc174bce993e", "get_pod_logs": "f5984552e9c3"}, "lock": "workflows/w2-ops-assistant/servers/kubernetes.lock.json"}
  {"ts": "2026-11-03T21:22:28.787+00:00", "event": "tools_verified", "trace_id": "3601c1d046e346ff8c20b5d7c08e6c9d", "workflow": "w2-ops-assistant", "case": "w2-01", "persona": "oncall.engineer", "server": "metrics-mcp", "tools": {"query_metric": "0fa1a6df5c5d"}, "lock": "workflows/w2-ops-assistant/servers/metrics.lock.json"}
  {"ts": "2026-11-03T21:22:28.789+00:00", "event": "tools_verified", "trace_id": "3601c1d046e346ff8c20b5d7c08e6c9d", "workflow": "w2-ops-assistant", "case": "w2-01", "persona": "oncall.engineer", "server": "logs-mcp", "tools": {"search_logs": "cdeef8c373df"}, "lock": "workflows/w2-ops-assistant/servers/logs.lock.json"}
  {"ts": "2026-11-03T21:22:29.944+00:00", "event": "tool_call", "trace_id": "3601c1d046e346ff8c20b5d7c08e6c9d", "workflow": "w2-ops-assistant", "case": "w2-01", "persona": "oncall.engineer", "tool": "get_pod_status", "args": {"service": "claims-api"}, "transport": "http", "ok": true}
  {"ts": "2026-11-03T21:22:31.264+00:00", "event": "answer", "trace_id": "3601c1d046e346ff8c20b5d7c08e6c9d", "workflow": "w2-ops-assistant", "case": "w2-01", "persona": "oncall.engineer", "refused": false, "answer": "The **claims‑api** deployment is not fully healthy.  \nIn the last 5 minutes it has 3 desired pods, but only 2 are ready.  \nOne pod (`claims-api-7d9f8b6c4-t8w2c`) is in `CrashLoopBackOff` with 7 restarts.  \nThe other two pods are running with no restarts.  \nThis indicates a health issue with the failing pod.  \nFor anything the assistant can't see, ask the team that owns the service, or the incident commander during an incident. Reference 3601c1d0."}

tool server log: 1 record
  {"ts": "2026-11-03T21:22:29.872+00:00", "event": "tool_call", "trace_id": "3601c1d046e346ff8c20b5d7c08e6c9d", "trace_source": "request", "tool": "get_pod_status", "args": {"service": "claims-api"}, "identity": "larkspur-ops-kubernetes-reader", "caller": "d0e14fb7-ba16-51e9-80c6-8c233ac4c455", "transport": "streamable-http", "ok": true}

gateway cost lines: 2 records: 2 served, 0.000000 USD, 1,881 tokens in, 198 out
  {"ts": "2026-11-03T21:22:29.867+00:00", "event": "call", "trace_id": "3601c1d046e346ff8c20b5d7c08e6c9d", "workflow": "w2-ops-assistant", "data_class": "internal", "requested_alias": "larkspur-chat", "served_alias": "larkspur-chat", "fallback": false, "fallbacks_disabled": false, "deployment": "local-gpt-oss-20b-chat", "region": "ca-central-1", "served_model": "gpt-oss:20b", "prompt_tokens": 848, "completion_tokens": 42, "cost_usd": 0.0, "latency_ms": 585}
  {"ts": "2026-11-03T21:22:31.264+00:00", "event": "call", "trace_id": "3601c1d046e346ff8c20b5d7c08e6c9d", "workflow": "w2-ops-assistant", "data_class": "internal", "requested_alias": "larkspur-chat", "served_alias": "larkspur-chat", "fallback": false, "fallbacks_disabled": false, "deployment": "local-gpt-oss-20b-chat", "region": "ca-central-1", "served_model": "gpt-oss:20b", "prompt_tokens": 1033, "completion_tokens": 156, "cost_usd": 0.0, "latency_ms": 1097}

spans: 19 kept by share-of-the-rest, at a share of 1
  invoke_agent w2-harness  [w2-harness]  +0 ms, 2580 ms  (kept at a share of 1)
    MCP send server/discover  [w2-harness]  +89 ms, 0 ms
      server/discover  [larkspur-ops-kubernetes]  +89 ms, 0 ms
    MCP send tools/list  [w2-harness]  +89 ms, 0 ms
      tools/list  [larkspur-ops-kubernetes]  +89 ms, 0 ms
    MCP send server/discover  [w2-harness]  +89 ms, 11 ms
      server/discover  [larkspur-ops-metrics]  +89 ms, 11 ms
    MCP send tools/list  [w2-harness]  +99 ms, 2 ms
      tools/list  [larkspur-ops-metrics]  +101 ms, 0 ms
    MCP send server/discover  [w2-harness]  +103 ms, 2 ms
      server/discover  [larkspur-ops-logs]  +105 ms, 0 ms
    MCP send tools/list  [w2-harness]  +105 ms, 0 ms
      tools/list  [larkspur-ops-logs]  +105 ms, 0 ms
    chat larkspur-chat  [gateway]  +595 ms, 585 ms
    execute_tool get_pod_status  [w2-harness]  +1182 ms, 78 ms
      MCP send tools/call get_pod_status  [w2-harness]  +1182 ms, 8 ms
        tools/call get_pod_status  [larkspur-ops-kubernetes]  +1182 ms, 5 ms
          execute_tool get_pod_status  [larkspur-ops-kubernetes]  +1188 ms, 0 ms
    chat larkspur-chat  [gateway]  +1479 ms, 1097 ms
```
