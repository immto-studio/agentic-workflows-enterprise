# Chapter 16, step 8: the model register and the upgrade path

Written by `lifecycle/upgrade.py --only summarize` from the files beside it. Everything here is MEASURED on this workstation; nothing is simulated.

## The register

|Model|Cloud|Larkspur runs on it|Stage|Retires|Pin|Behind|
|---|---|---|---|---|---|---|
|Amazon Nova Lite|aws|yes|Active|no earlier than 2025-12-05|model id: amazon.nova-lite-v1:0|larkspur-chat, larkspur-chat-fallback|
|Mistral Large (24.02)|aws|no|Active|no earlier than 2025-02-26|model id: mistral.mistral-large-2402-v1:0|none|
|Claude Sonnet 5.5|aws|no|Active|no earlier than 2027-09-28|model id: anthropic.claude-sonnet-5-5 (no version in it)|none|
|Claude Haiku 5.5|aws|no|Active|no earlier than 2027-10-07|inference profile id: ca.anthropic.claude-haiku-5-5 (no version in it)|none|
|Claude 3 Haiku|aws|no|Legacy|2026-11-13|model id: anthropic.claude-3-haiku-20240307-v1:0|none|
|Llama 3 70B Instruct|aws|no|Legacy|2027-03-30|model id: meta.llama3-70b-instruct-v1:0|none|
|Gemini 3.5 Flash|google|yes|GA|no earlier than 2027-05-19|model id: gemini-3.5-flash|chapter 7's Memory Bank memory generation|
|text-multilingual-embedding-002|google|yes|GA|2027-04-01|model id: text-multilingual-embedding-002|chapter 7's Memory Bank similarity search|
|gpt-4o|azure|yes|Legacy|2027-04-14|model name and version: gpt-4o 2024-11-20|chapter 8's chat model, a Standard deployment in Canada East (variable chat_model)|
|gpt-4.1-mini|azure|no|Deprecated|2027-04-14|model name and version: gpt-4.1-mini 2025-04-14|none|
|gpt-oss-20b|local|yes|serving|none published|ollama digest: f38aa0c53da5|larkspur-chat, larkspur-chat-restricted|
|Gemma 4 12B|local|no|candidate|none published|ollama digest: 6114515d63c1|larkspur-chat, larkspur-chat-restricted|
|Qwen3 Embedding 0.6B|local|yes|serving|none published|ollama digest: ac6da0dfba84|larkspur-embed|

|Cloud|Models|
|---|---|
|aws|6|
|google|2|
|azure|2|
|local|3|
|all|13|

|Tag|Pinned digest|Reported by Ollama 0.40.13|Matches|Size|
|---|---|---|---|---|
|gpt-oss:20b|f38aa0c53da5|f38aa0c53da5|yes|13.79 GB|
|gemma4:12b|6114515d63c1|6114515d63c1|yes|8.02 GB|
|qwen3-embedding:0.6b|ac6da0dfba84|ac6da0dfba84|yes|0.64 GB|

Configurations checked: 14 LiteLLM files and 2 Terraform files; problems: 0; deployments: 14; pins without a version: aws-claude-sonnet-5-5, aws-claude-haiku-5-5.

## The retirement alert on three dates

|Date|Retired|Within 90 days|Within 180|Further off|No date published|Pages|Tickets|Review rows|
|---|---|---|---|---|---|---|---|---|
|2026-11-09|0|1|4|0|8|0|1|5|
|2027-02-01|1|4|0|0|8|0|3|4|
|2027-05-01|5|0|0|0|8|2|1|0|

|Date|Action|Rule|Model|Cloud|Larkspur runs on it|Retires|Days left|
|---|---|---|---|---|---|---|---|
|2026-11-09|review|retirement-180d-review|Claude 3 Haiku|aws|no|2026-11-13|4|
|2026-11-09|review|retirement-180d-review|Llama 3 70B Instruct|aws|no|2027-03-30|141|
|2026-11-09|review|retirement-180d-review|text-multilingual-embedding-002|google|yes|2027-04-01|143|
|2026-11-09|review|retirement-180d-review|gpt-4o|azure|yes|2027-04-14|156|
|2026-11-09|ticket|legacy-notice|gpt-4o|azure|yes|2027-04-14|156|
|2026-11-09|review|retirement-180d-review|gpt-4.1-mini|azure|no|2027-04-14|156|
|2027-02-01|review|retirement-180d-review|Llama 3 70B Instruct|aws|no|2027-03-30|57|
|2027-02-01|ticket|retirement-90d|text-multilingual-embedding-002|google|yes|2027-04-01|59|
|2027-02-01|review|retirement-180d-review|text-multilingual-embedding-002|google|yes|2027-04-01|59|
|2027-02-01|ticket|retirement-90d|gpt-4o|azure|yes|2027-04-14|72|
|2027-02-01|review|retirement-180d-review|gpt-4o|azure|yes|2027-04-14|72|
|2027-02-01|ticket|legacy-notice|gpt-4o|azure|yes|2027-04-14|72|
|2027-02-01|review|retirement-180d-review|gpt-4.1-mini|azure|no|2027-04-14|72|
|2027-05-01|page|retired-still-pinned|text-multilingual-embedding-002|google|yes|2027-04-01|-30|
|2027-05-01|page|retired-still-pinned|gpt-4o|azure|yes|2027-04-14|-17|
|2027-05-01|ticket|legacy-notice|gpt-4o|azure|yes|2027-04-14|-17|

## The gate: the candidate behind the alias on staging

|Workflow|Candidate|Judge|Cases|Complete run|Seconds|Checks|Held|Regressed|Not gated|Pin problems|Verdict for the path|
|---|---|---|---|---|---|---|---|---|---|---|---|
|W2|gemma4-12b|gpt-oss-20b|25|no: workflows w2|136|11|9|trajectory.allowed|1|7|regressed|

|Check|Threshold|Baseline|Candidate|Lost|Gained|Verdict|
|---|---|---|---|---|---|---|
|scorer|not gated|22 of 25|23 of 25|w2-05|w2-14, w2-16|not gated|
|deterministic.facts|1|18 of 20|18 of 20|w2-05|w2-16|held|
|deterministic.refusal|0|4 of 5|5 of 5|-|w2-14|held|
|deterministic.route|1|5 of 5|5 of 5|-|-|held|
|deterministic.labels|0|24 of 24|24 of 24|-|-|held|
|deterministic.planted|0|3 of 3|3 of 3|-|-|held|
|deterministic.masked|0|25 of 25|25 of 25|-|-|held|
|trajectory.allowed|1|25 of 25|23 of 25|w2-01, w2-05|-|regressed|
|trajectory.order|1|25 of 25|25 of 25|-|-|held|
|trajectory.forbidden|0|25 of 25|25 of 25|-|-|held|
|trajectory.budget|0|25 of 25|25 of 25|-|-|held|

|Pins|What differs from the baseline|
|---|---|
|w2|the alias map changed: larkspur-chat ollama_chat/gpt-oss:20b -> ollama_chat/gemma4:12b|
|w2|ollama_chat/gemma4:12b: the baseline holds no digest for it|
|w2|ollama_chat/gpt-oss:20b: the baseline holds no digest for it|
|the judge|the judge's model changed: gemma4-12b -> gpt-oss-20b|
|the judge|the judge's served changed: ollama_chat/gemma4:12b -> ollama_chat/gpt-oss:20b|
|the judge|the judge's alias map changed: larkspur-chat ollama_chat/gemma4:12b -> ollama_chat/gpt-oss:20b; larkspur-chat-restricted ollama_chat/gemma4:12b -> ollama_chat/gpt-oss:20b|
|the judge|the judge's digest changed: 6114515d63c1 -> f38aa0c53da5|

|Judge|Outputs read|Withheld as sampled texts|Right|Wrong|No verdict|
|---|---|---|---|---|---|
|gpt-oss-20b|19|0|17|2|0|

|Tokens|Calls|Prompt|Completion|
|---|---|---|---|
|the candidate, W2's set|56|62,595|2,116|
|the judge|19|11,728|6,694|

## The canary

|Deployment|Arm|Model|Weight|Share asked|Thinking|num_ctx|
|---|---|---|---|---|---|---|
|local-gpt-oss-20b-chat|control|ollama_chat/gpt-oss:20b|3|75%|model default|16,384|
|candidate-gemma4-12b-chat|candidate|ollama_chat/gemma4:12b|1|25%|False|16,384|

|Passes|Cases a pass|Runs|Calls|Failed calls|Calls a run (median)|Seconds|Ollama|Swaps: loads of each model|Both models resident at once|
|---|---|---|---|---|---|---|---|---|---|
|4|25|100|196|0|2|554|0.40.13|gemma4:12b 39, gpt-oss:20b 38|no|

|Arm|Calls|Share served|Failed|Latency ms, median|p95|Calls after a swap|Median after a swap|Median with no swap|Load s, median|Load s, max|Load s, total|
|---|---|---|---|---|---|---|---|---|---|---|---|
|control|142|72.45%|0|928|5,751|38|5,228|647|4.4|6.35|166|
|candidate|54|27.55%|0|4,678|5,192|39|4,718|372|4.4|5.86|174|

|Runs served by|Runs|Ends|Success|Latency under 10 s|Latency, loads taken out|Seconds, median|Without loads, median|Runs with a load|
|---|---|---|---|---|---|---|---|---|
|candidate|11|answer 6, refusal 5|11 / 11 (100%)|11 / 11 (100%)|11 / 11 (100%)|4.8|0.7|7|
|control|49|answer 41, refusal 8|49 / 49 (100%)|49 / 49 (100%)|49 / 49 (100%)|1.7|1.6|8|
|mixed|36|answer 36|36 / 36 (100%)|20 / 36 (55.56%)|36 / 36 (100%)|9.8|1.7|36|
|none|4|refusal 4|4 / 4 (100%)|4 / 4 (100%)|4 / 4 (100%)|0.2|0.2|0|

|Arm, over the runs it served|Runs|Ends|Success|Latency|Latency, loads taken out|Seconds, median|Without loads, median|Load s in its runs|
|---|---|---|---|---|---|---|---|---|
|control|85|answer 77, refusal 8|85 / 85 (100%)|69 / 85 (81.18%)|85 / 85 (100%)|5.3|1.7|309|
|candidate|47|answer 42, refusal 5|47 / 47 (100%)|31 / 47 (65.96%)|47 / 47 (100%)|7.5|1.5|305|

## The decision

|SLI|Read from|Control|Candidate|Candidate not below control|
|---|---|---|---|---|
|success|success|85 / 85 (100%)|47 / 47 (100%)|yes|
|latency|latency_without_loads|85 / 85 (100%)|47 / 47 (100%)|yes|

|Decision|Gate|Minimum runs|As measured, loads included|Because|
|---|---|---|---|---|
|remap back|9 held, 1 regressed, 1 not gated|20|remap back|the gate: trajectory.allowed regressed past the threshold|

## The remap

|Change|Kind|Lever|Alias|From|To|By|Authority|Document by|Review|Takes effect|
|---|---|---|---|---|---|---|---|---|---|---|
|CH-20261109-01|emergency|alias remap, back|larkspur-chat|local-gpt-oss-20b-chat (weight 3), candidate-gemma4-12b-chat (weight 1)|local-gpt-oss-20b-chat|oncall.lead@larkspur.example|on-call lead|2026-11-10T11:54:11.440+00:00|the next board meeting|at the proxy's next start, which reads the configuration once|

|After the remap|Cases|Calls|Served by|Every call on the expected deployment|Ends|Seconds|
|---|---|---|---|---|---|---|
|litellm.restored.yaml|w2-01, w2-02, w2-03|6|local-gpt-oss-20b-chat|yes|answer, answer, answer|8.64, 0.9, 2.05|

## fig-16-04

|Stage|Name|What gates it|The run's numbers|
|---|---|---|---|
|register|the register|the register and the gateways name the same deployments (lifecycle/register.py --check)|models 13; pinned 6; deployments 14; problems 0; candidate local-gemma4-12b; candidate_pin 6114515d63c1|
|staging|the candidate behind the alias on a staging gateway|the gate of E-D9 (labs/ch15/ci/gate.py): no check may lose more cases against the baseline than its threshold allows (the baseline built from the kept runs, until a live run is accepted); the pins are listed for the review that accepts the new baseline|cases 25; checks 11; held 9; not_gated 1; pin_problems 7; verdict regressed; seconds 136.4|
|canary|a canary weight in the gateway|O-D12's SLIs over each arm's runs (slo/slis.py): the candidate's success and latency ratios not below the control's on the same traffic, with at least 20 valid runs on the candidate|share 0.25; passes 4; runs 100; calls 196; candidate_calls 54; seconds 553.9|
|decision|promote, remap back, or extend|the rule above|decision remap back; latency_read_from latency_without_loads; as_measured remap back|
|remap|the alias remapped|the change record (ch02:163)|change CH-20261109-01; kind emergency; lever alias remap, back; probe_calls 6|
|after|after the remap|the review that accepts the baseline (labs/ch15/ci/live.py --accept)|ran False; waits_for the live job on the new map and the review that accepts it (E-D9)|
