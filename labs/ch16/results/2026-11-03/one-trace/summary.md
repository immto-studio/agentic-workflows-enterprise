# Chapter 16, a follow-up to step 3b: one W3 incident and one W4 change as one trace each

Each case ran again through its workflow's own harness, servers and gateway on gpt-oss-20b, every process sending OTLP to the pinned Collector (`collector/run_workflows.py --only`), after W3's eval/lab.py began opening one `invoke_agent w3-incident` span an incident and W4's risk scorer began handing its span's traceparent to the rationale seam. Every table below is computed by `collector/one_trace.py --summarize` from the files in this folder; step 3b's columns come from `../workflows/workflows.json`.

## What the case's trace id holds

|Run |Case |Passed |Model calls |Spans sent |Under the case's trace id |Roots |The root |Spans elsewhere naming the case |Traces naming no case |One tree |
|---|---|---|---|---|---|---|---|---|---|---|
|W3, gpt-oss-20b |w3-01 |yes |7 |56 |56 |1 |w3-harness: invoke_agent w3-incident (1) |0 |0 |yes |
|W4, gpt-oss-20b |w4-01 |yes |1 |4 |4 |1 |scribe: invoke_agent change-management (1) |0 |0 |yes |

## The same case in step 3b

|Run |Case |Under the case's trace id |Roots |The roots |Traces elsewhere naming the case |Their spans |The whole run's traces naming no case (cases) |
|---|---|---|---|---|---|---|---|
|W3, gpt-oss-20b |w3-01 |4 |4 |gateway: chat larkspur-chat (2); gateway: chat larkspur-chat-restricted (2) |4 |15 |240 of 480 spans (24) |
|W4, gpt-oss-20b |w4-01 |4 |2 |gateway: chat larkspur-chat (1); scribe: invoke_agent change-management (1) |0 |0 |0 of 0 spans (8) |

## Which processes sent spans

|Run |service.name |Spans sent |
|---|---|---|
|W3, gpt-oss-20b |gateway |7 |
|W3, gpt-oss-20b |larkspur-ops-kubernetes |10 |
|W3, gpt-oss-20b |larkspur-ops-logs |2 |
|W3, gpt-oss-20b |larkspur-ops-metrics |4 |
|W3, gpt-oss-20b |larkspur-ops-servicenow |4 |
|W3, gpt-oss-20b |larkspur-ops-writer |4 |
|W3, gpt-oss-20b |w3-harness |25 |
|W4, gpt-oss-20b |analyst |1 |
|W4, gpt-oss-20b |gateway |1 |
|W4, gpt-oss-20b |risk-scorer |1 |
|W4, gpt-oss-20b |scribe |1 |
