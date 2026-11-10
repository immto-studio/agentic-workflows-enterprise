# Chapter 16, step 3: the local run through the Collector

Every table below is computed by `collector/analyze.py --summarize` from the files in this folder. The run is `collector/run_local.py`: chapter 5's skeleton with the rule model, every process sending OTLP to the pinned Collector running `collector/config.yaml`, and two fakes standing in for Langfuse and CloudWatch.

## What reached each store

|Phase |Share of the rest |Runs |Traces at the Collector |Kept, as the policies say |Kept in the span file |At CloudWatch's fake |At Langfuse's fake |The same runs everywhere |Spans sent |Spans of the kept runs |Kept runs with the same spans in all three |
|---|---|---|---|---|---|---|---|---|---|---|---|
|every-run |100% |25 |25 |25 |25 |25 |25 |yes |257 |257 |25 of 25 |
|sampled |10% |105 |105 |21 |21 |21 |21 |yes |1117 |218 |21 of 21 |

|Phase |Process |Spans it sent |In the span file |At CloudWatch's fake |At Langfuse's fake |
|---|---|---|---|---|---|
|every-run |gateway |48 |48 |48 |48 |
|every-run |harness |117 |117 |117 |117 |
|every-run |mcp-server |92 |92 |92 |92 |
|sampled |gateway |204 |41 |41 |41 |
|sampled |harness |509 |99 |99 |99 |
|sampled |mcp-server |404 |78 |78 |78 |

## The same trace ids in every store

|Phase |Runs |With harness log lines |With a tool call |Of those, in the tool server's log |With gateway cost lines |Kept runs with one gateway span per cost line |
|---|---|---|---|---|---|---|
|every-run |25 |25 |21 |21 |25 |25 of 25 |
|sampled |105 |105 |97 |97 |105 |21 of 21 |

## Content the manifests don't allow

|Phase |Attribute |On spans that reached the Collector |In the span file |At CloudWatch's fake |At Langfuse's fake |
|---|---|---|---|---|---|
|every-run |`gen_ai.tool.call.arguments` |42 |0 |0 |0 |
|sampled |`gen_ai.tool.call.arguments` |194 |0 |0 |0 |

## Tail sampling

Each policy, the runs whose spans it matches (computed here from what reached the Collector), the traces the Collector itself counts as sampled by it, and the kept traces that record it.

|Phase |Policy |Runs it matches |The Collector's count |Recorded on kept traces |Share recorded |
|---|---|---|---|---|---|
|every-run |failed |3 |3 |3 |1 |
|every-run |refused |1 |1 |1 |1 |
|every-run |slow |1 |1 |1 |1 |
|every-run |over-budget |1 |1 |1 |1 |
|every-run |fallback |1 |1 |0 |none |
|every-run |share-of-the-rest |25 |25 |19 |1 |
|sampled |failed |7 |7 |7 |1 |
|sampled |refused |1 |1 |1 |1 |
|sampled |slow |1 |1 |1 |1 |
|sampled |over-budget |1 |1 |1 |1 |
|sampled |fallback |1 |1 |0 |none |
|sampled |share-of-the-rest |13 |13 |11 |0.1 |

|Phase |Run |Policies it matches |Recorded policy |Share recorded |Kept everywhere |
|---|---|---|---|---|---|
|every-run |refused-alerts |refused |refused |1 |yes |
|every-run |over-budget-pasted-log |over-budget |over-budget |1 |yes |
|every-run |fallback-primary-down |failed, fallback |failed |1 |yes |
|every-run |slow-model |slow |slow |1 |yes |
|every-run |failed-both-down |failed |failed |1 |yes |
|sampled |refused-alerts |refused |refused |1 |yes |
|sampled |over-budget-pasted-log |over-budget |over-budget |1 |yes |
|sampled |fallback-primary-down |failed, fallback |failed |1 |yes |
|sampled |slow-model |slow |slow |1 |yes |
|sampled |failed-both-down |failed |failed |1 |yes |

|Phase |Runs no keep-all policy matches |Kept by the share, by FNV-1a here |Kept by the Collector |The same runs |
|---|---|---|---|---|
|every-run |19 |19 |19 |yes |
|sampled |95 |11 |11 |yes |

## The delay

Seconds, minimum / median / maximum over the kept traces: from the tap's first receipt of a trace (the Collector's receipt, before any processor) to its first arrival at each fake, and from the end of the trace's last span to its arrival at Langfuse's fake.

|Phase |Kept traces |decision_wait |Receipt to Langfuse's fake |Receipt to CloudWatch's fake |Last span's end to Langfuse's fake |
|---|---|---|---|---|---|
|every-run |25 |30 s |30.20 / 30.74 / 31.06 |30.20 / 30.74 / 31.06 |20.15 / 31.26 / 32.14 |
|sampled |21 |30 s |30.21 / 30.67 / 30.92 |30.21 / 30.68 / 30.92 |18.32 / 31.17 / 32.42 |

## Headers

|Phase |Fake |Requests |Path |Authorization |Other headers |Refused by the fake |
|---|---|---|---|---|---|---|
|every-run |Langfuse |17 |`/api/public/otel/v1/traces` |Basic, decoding to `pk-lab-dummy:sk-lab-dummy` on every request |`x-langfuse-ingestion-version: 4` on every request |0 |
|every-run |CloudWatch |17 |`/v1/traces` |`AWS4-HMAC-SHA256`, key `LARKSPURLABDUMMYKEY0`, scope `us-east-2/xray/aws4_request`, signature recomputed from the dummy secret on 17 of 17 |`X-Amz-Date` on every request; signed: `content-encoding;content-length;content-type;host;x-amz-date` |0 |
|sampled |Langfuse |19 |`/api/public/otel/v1/traces` |Basic, decoding to `pk-lab-dummy:sk-lab-dummy` on every request |`x-langfuse-ingestion-version: 4` on every request |0 |
|sampled |CloudWatch |19 |`/v1/traces` |`AWS4-HMAC-SHA256`, key `LARKSPURLABDUMMYKEY0`, scope `us-east-2/xray/aws4_request`, signature recomputed from the dummy secret on 19 of 19 |`X-Amz-Date` on every request; signed: `content-encoding;content-length;content-type;host;x-amz-date` |0 |

## Langfuse's cost

|Phase |Gateway spans with `larkspur.cost_usd` at Langfuse's fake |With `gen_ai.usage.cost` equal to it |Spans with `gen_ai.usage.cost` in the span file or at CloudWatch's fake |
|---|---|---|---|
|every-run |45 |45 |0 |
|sampled |38 |38 |0 |
