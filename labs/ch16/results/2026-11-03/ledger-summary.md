# The ledger, steps 2 and 3b: 3 November 2026

Chapter 16's lab, step 2 (companion #14: O-D5, O-D6, and the plan's consistency notes), run again with step 3b's cost lines. Every model call the workflows kept, 1,189 calls in 379 runs of 30 kept runs, 26 of them read through chapter 15's registry and 4 made by step 3b through the Collector, is one cost line, priced at chapter 6's design from the dated table (49 entries). The ledger itself uses no model, gateway, network, or cloud account.

This file is the companion's dated record, so it prints prices; the book prints none, and section 12 lists what it may print. Per-run figures are measured on the kept runs. Monthly volumes are Larkspur's estimates where the book states one and lab assumptions where it doesn't (`ledger/volumes.yaml`). The golden sets were written to test the workflows, so their mix of cases isn't production's: W1's set puts three of its 25 cases on Restricted pages, and W2's has five refusal cases in 25. Per-run figures inherit that mix.

## 1. The price table

`ledger/prices.yaml`, in US dollars. Chapter 6's design names the deployment for each alias: `larkspur-chat` is `nova-lite-ca`, `larkspur-chat-fallback` is `nova-lite-us`, `larkspur-chat-restricted` is `vllm-gpt-oss-20b`, `larkspur-embed` is `titan-embed-v2-ca`, and a fallback from `larkspur-chat` is priced at `nova-lite-us`, in its own Region. Every entry carries its source, the date that source records, and the page it cites; the entries copied from a cost sheet name the place in the sheet, and the rest quote section 8.8 of the fact sheet.

### Deployments: what serves an alias where

|Entry |What |Price (USD) |Source |Date |
|---|---|---|---|---|
|`nova-lite-ca` |Amazon Nova Lite through its Canadian geographic profile |0.064 in, 0.256 out, per million tokens |labs/ch06/cost/cost-sheet.yaml |2026-10-29 |
|`nova-lite-us` |Amazon Nova Lite In-Region in us-east-2, the Internal fallback |0.06 in, 0.24 out, per million tokens |labs/ch06/cost/cost-sheet.yaml |2026-10-29 |
|`vllm-gpt-oss-20b` |gpt-oss-20b on chapter 9's two vLLM replicas in ca-central-1 |0.0 in, 0.0 out, per million tokens |labs/ch09/gateway/litellm.k8s.yaml |2026-10-29 |
|`titan-embed-v2-ca` |Amazon Titan Text Embeddings V2 in ca-central-1, the Knowledge Base's embedding model |0.1 in, 0.0 out, per million tokens |labs/ch06/cost/cost-sheet.yaml |2026-10-29 |
|`gpt-4o-canada-east` |gpt-4o 2024-11-20, a Standard deployment in Canada East |3.025 in, 12.1 out, per million tokens |labs/ch08/cost/cost-sheet.yaml |2026-10-29 |
|`gemini-3.5-flash-montreal` |Gemini 3.5 Flash in Montréal (ch07:88) |none |labs/ch07/cost/cost-sheet.yaml |2026-10-29 |
|`bedrock-gpt-oss-120b-use1` |gpt-oss-120b on Amazon Bedrock's Standard tier in us-east-1 |0.15 in, 0.6 out, per million tokens |labs/ch09/cost/cost-sheet.yaml |2026-10-28 |

### The guardrail on the managed aliases

|Entry |What |Price (USD) |Source |Date |
|---|---|---|---|---|
|`bedrock-guardrail-ca` |Amazon Bedrock Guardrails in ca-central-1, before and after each call on the managed aliases |content filters 0.15, denied topics 0.15, sensitive information 0.1, contextual grounding 0.1, word filters 0.0, per 1,000 text units |labs/ch06/cost/cost-sheet.yaml |2026-10-29 |

### GPU hours

|Entry |What |Price (USD) |Source |Date |
|---|---|---|---|---|
|`aws-g6e.xlarge-l40s` |one L40S on an on-demand g6e.xlarge in us-east-1, the lower bound chapter 9 uses |1.861 an hour |labs/ch09/cost/cost-sheet.yaml |2026-10-28 |
|`aws-g6e.2xlarge-l40s-cac1` |the node chapter 9 names for a replica, a g6e.2xlarge or larger in ca-central-1 (ch09:94) |none |book ch09:94 |2026-10-28 |
|`aws-p5.4xlarge-h100` |one H100 on an on-demand p5.4xlarge in us-east-1, chapter 9's crossover for gpt-oss-120b |6.88 an hour |labs/ch09/cost/cost-sheet.yaml |2026-10-28 |
|`gcp-g2-standard-4-l4` |one L4 on an on-demand g2-standard-4 in us-central1 |0.7068 an hour |labs/ch09/cost/cost-sheet.yaml |2026-10-28 |

### The platform's fixed costs

|Entry |What |Price (USD) |Source |Date |
|---|---|---|---|---|
|`rds-postgres-db.t4g.micro-cac1` |RDS for PostgreSQL, db.t4g.micro (2 vCPU, 1 GiB), Single-AZ, ca-central-1 |0.018 an hour |fact sheet, section 8.8 |2026-11-03 |
|`rds-postgres-db.t4g.small-cac1` |RDS for PostgreSQL, db.t4g.small (2 GiB), Single-AZ, ca-central-1 |0.035 an hour |fact sheet, section 8.8 |2026-11-03 |
|`rds-postgres-db.t4g.medium-cac1` |RDS for PostgreSQL, db.t4g.medium (4 GiB), Single-AZ, ca-central-1 |0.07 an hour |fact sheet, section 8.8 |2026-11-03 |
|`rds-gp3-storage-cac1` |RDS gp3 storage for PostgreSQL, ca-central-1 |0.127 a GB-month |fact sheet, section 8.8 |2026-11-03 |
|`elasticache-t4g.micro-valkey-cac1` |ElastiCache, cache.t4g.micro running Valkey (0.5 GiB), ca-central-1 |0.0144 an hour |fact sheet, section 8.8 |2026-11-03 |
|`elasticache-t4g.micro-redis-cac1` |ElastiCache, cache.t4g.micro running Redis, ca-central-1 |0.018 an hour |fact sheet, section 8.8 |2026-11-03 |
|`elasticache-t4g.small-valkey-cac1` |ElastiCache, cache.t4g.small running Valkey, ca-central-1 |0.028 an hour |fact sheet, section 8.8 |2026-11-03 |
|`elasticache-serverless-valkey-storage-cac1` |ElastiCache Serverless for Valkey, data storage, ca-central-1 |0.092 a GB-hour |fact sheet, section 8.8 |2026-11-03 |
|`elasticache-serverless-valkey-ecpu-cac1` |ElastiCache Serverless for Valkey, ElastiCache Processing Units, ca-central-1 |0.0025 a million ECPUs |fact sheet, section 8.8 |2026-11-03 |
|`ec2-t3.xlarge-use2` |EC2 t3.xlarge, Linux on demand (4 vCPU, 16 GiB, Langfuse's example size), us-east-2 |0.1664 an hour |fact sheet, section 8.8 |2026-11-03 |
|`ec2-t4g.xlarge-use2` |EC2 t4g.xlarge, Linux on demand (Arm, 16 GiB), us-east-2 |0.1344 an hour |fact sheet, section 8.8 |2026-11-03 |
|`ec2-m7i-flex.xlarge-use2` |EC2 m7i-flex.xlarge, Linux on demand, us-east-2 |0.19152 an hour |fact sheet, section 8.8 |2026-11-03 |
|`ec2-m7i-flex.large-use2` |EC2 m7i-flex.large, Linux on demand (8 GiB, the largest free-tier-eligible type), us-east-2 |0.09576 an hour |fact sheet, section 8.8 |2026-11-03 |
|`ebs-gp3-use2` |EBS gp3 storage, us-east-2 |0.08 a GB-month |fact sheet, section 8.8 |2026-11-03 |
|`public-ipv4-use2` |an in-use public IPv4 address, us-east-2 (the plan's Langfuse VM uses none) |0.005 an hour |fact sheet, section 8.8 |2026-11-03 |
|`vpc-interface-endpoint-cac1` |one interface endpoint in one Availability Zone, ca-central-1 (chapter 6's shared endpoints) |0.011 an hour |labs/ch06/cost/cost-sheet.yaml |2026-10-29 |
|`kms-key-cac1` |one customer managed KMS key, ca-central-1 |1.0 a month |labs/ch06/cost/cost-sheet.yaml |2026-10-29 |
|`psc-endpoint-google` |chapter 7's Private Service Connect endpoint for Google APIs (ch07:88) |none |labs/ch07/cost/cost-sheet.yaml |2026-10-29 |
|`private-endpoints-azure` |chapter 8's private endpoints |none |labs/ch08/cost/cost-sheet.yaml |2026-10-29 |
|`litellm-enterprise` |LiteLLM's enterprise license |none |fact sheet, section 8.8 |2026-11-03 |
|`langfuse-enterprise` |Langfuse's enterprise features, self-hosted; the open-source edition is free |none |fact sheet, section 8.8 |2026-11-03 |

### Traces and the reconciliation

|Entry |What |Price (USD) |Source |Date |
|---|---|---|---|---|
|`cloudwatch-span-ingestion-use2` |CloudWatch Application Signals data ingested (spans), first 10 TB, us-east-2 |0.35 a GB |fact sheet, section 8.8 |2026-11-03 |
|`cloudwatch-span-ingestion-cac1` |CloudWatch Application Signals data ingested (spans), first 10 TB, ca-central-1 |0.35 a GB |fact sheet, section 8.8 |2026-11-03 |
|`cloudwatch-span-indexing-use2` |Transaction Search spans indexed, us-east-2 |0.00000075 a span |fact sheet, section 8.8 |2026-11-03 |
|`cloudwatch-span-indexing-cac1` |Transaction Search spans indexed, ca-central-1 |0.00000075 a span |fact sheet, section 8.8 |2026-11-03 |
|`cloudwatch-otlp-logs-use2` |CloudWatch OTLP log data processed, us-east-2 |0.5 a GB |fact sheet, section 8.8 |2026-11-03 |
|`cloudwatch-logs-insights-cac1` |CloudWatch Logs Insights, data scanned, ca-central-1 |0.0055 a GB |fact sheet, section 8.8 |2026-11-03 |
|`cloudwatch-log-storage-cac1` |CloudWatch Logs storage, ca-central-1 |0.033 a GB-month |fact sheet, section 8.8 |2026-11-03 |
|`cost-explorer-api` |one Cost Explorer API request |0.01 a request |fact sheet, section 8.8 |2026-11-03 |

### Committed capacity, for step 5

|Entry |What |Price (USD) |Source |Date |
|---|---|---|---|---|
|`nova-lite-pt-nocommit-use1` |Nova Lite Provisioned Throughput, no commitment, per model unit, us-east-1 |60.5 an hour |fact sheet, section 8.8 |2026-11-03 |
|`nova-lite-pt-1month-use1` |Nova Lite Provisioned Throughput, one-month commitment, per model unit, us-east-1 |55.0 an hour |fact sheet, section 8.8 |2026-11-03 |
|`nova-lite-pt-6months-use1` |Nova Lite Provisioned Throughput, six-month commitment, per model unit, us-east-1 |30.25 an hour |fact sheet, section 8.8 |2026-11-03 |
|`claude-sonnet-4.5-reserved-1month-cac1` |Claude Sonnet 4.5 Reserved tier, one month, geographic cross-Region inference, per 1K tokens a minute, ca-central-1 |0.198 in, 0.99 out, per 1K tokens a minute an hour |fact sheet, section 8.8 |2026-11-03 |
|`claude-sonnet-4.5-reserved-3month-cac1` |Claude Sonnet 4.5 Reserved tier, three months, geographic cross-Region inference, per 1K tokens a minute, ca-central-1 |0.1782 in, 0.891 out, per 1K tokens a minute an hour |fact sheet, section 8.8 |2026-11-03 |
|`azure-ptu-gpt-5.5-regional-canadaeast` |Azure provisioned throughput, GPT-5.5 Regional, Canada East, per PTU (at least 50) |2.36 an hour; 338 a month or 3444 a year reserved, at least 50 PTUs |fact sheet, section 8.8 |2026-11-03 |
|`azure-ptu-global-canadaeast` |Azure provisioned throughput, the Global rows, Canada East, per PTU (at least 15) |1.0 an hour; 260 a month or 2652 a year reserved, at least 15 PTUs |fact sheet, section 8.8 |2026-11-03 |
|`google-gsu` |Google Provisioned Throughput, per GSU per hour, global and non-global |1 week: 7.14 global, 7.854 non-global; 1 month: 3.698630137 global, 4.068493151 non-global; 3 month: 3.287671233 global, 3.616438356 non-global; 1 year: 2.739726027 global, 3.01369863 non-global, an hour per GSU |fact sheet, section 8.8 |2026-11-03 |

A price no vendor publishes, or no source has, is null and stays a parameter: `gemini-3.5-flash-montreal` (labs/ch07/cost/cost-sheet.yaml prices Agent Platform's runtime, gateway, sessions and memory, not Gemini's tokens, and section 8.8 has no Gemini token price); `aws-g6e.2xlarge-l40s-cac1` (no cost sheet and no section of the fact sheet prices it); `psc-endpoint-google` (labs/ch07/cost/cost-sheet.yaml doesn't price it, and section 8.8 has no Google network price); `private-endpoints-azure` (labs/ch08/README.md: "The registry, the private endpoints and the workspace bill too, and the sheet doesn't price them."); `litellm-enterprise` (Pricing depends on your deployment size. Get in touch to scope it.); `langfuse-enterprise` (Custom Pricing).

## 2. The cost lines

`ledger/costlines.py` reads every kept run through chapter 15's registry, and the runs step 3b made through the Collector from each workflow's `eval/traced/`, which chapter 15's registry doesn't hold, and writes each model call as one line of one shape (`costlines.jsonl` here): run id, trace id, workflow and the workflow tag the gateway saw, the kept run and the case, the call's place in the run, the model as recorded, the alias asked for and the one that served, the data class, input and output tokens, the call's time, and whether a fallback served it. A run's id is its trace id where it kept one, and otherwise `<workflow>:<model>:<kept run>:<case>`.

|Workflow |Kept runs |Of them, step 3b's |Runs |Model calls |With tokens |With time |Runs with a trace id |Fallbacks |Tool calls, as kept |
|---|---|---|---|---|---|---|---|---|---|
|skeleton |2 |0 |40 |77 |77 |77 |0 |0 |every tool call, with its arguments |
|W1 |3 |0 |75 |163 |163 |163 |0 |0 |the searches the model calls imply |
|W2 |6 |1 |135 |281 |281 |281 |25 |0 |every read, with whether it returned data |
|W3 |2 |1 |48 |279 |142 |142 |24 |0 |the reads that returned data |
|W4 |6 |2 |48 |48 |16 |16 |48 |0 |not kept |
|W5 |11 |0 |33 |341 |341 |341 |33 |0 |every read in the night's log |
|all |30 |4 |379 |1189 |1020 |1020 |130 |0 | |

Chapter 15's kept runs of W3 and W4 hold no tokens: their gateways wrote the lines to the labs' scratch folders (`eval/_lab/`, which `.gitignore` leaves out), and only W5 committed its gateway's lines beside its results. Step 3b ran W3's incidents and W4's changes again through the Collector, with W2's golden set for fig-16-01, and committed the gateway's lines beside each run in the workflow's `eval/traced/2026-11-03/`, as W5 does. Those lines are the gateway's own, one per call, joined to each case by its trace id, so 142 of W3's 279 lines and 16 of W4's 48 carry tokens and a time: step 3b's, and none of the earlier runs'. O-D5's rule that the cost lines are never sampled assumes they are kept, and from step 3b on W3's and W4's are. Every step 3b run kept a trace id, as W4's and W5's earlier runs did, and no kept call was served by a fallback; `tests/test_price.py` prices one on a line made for it.

## 3. Cost per run, by workflow and model

Every kept run of each model, the early ones included. Each cell is the median and the 95th percentile (nearest rank, a value some run had). Calls count every run, and tokens and cost every run that kept them: for W3 and W4 those are step 3b's runs alone. Cost is in US dollars at chapter 6's design; the share is of the manifest's `per_run_usd` (the skeleton's is chapter 5's W2 manifest). The recounted column prices each call's tokens multiplied by section 5's ratios for its model, the way Nova Lite would have counted them. The guardrail column is section 8's estimate, which the cost lines don't carry.

|Workflow |Model |Runs |With tokens |Model calls |Tool calls |Input tokens |Output tokens |Cost per run |Share of per_run_usd |Recounted as Nova Lite |Guardrail estimate |
|---|---|---|---|---|---|---|---|---|---|---|---|
|skeleton |gemma4-12b |20 |20 |2 / 2 |1 / 1 |678 / 753 |121 / 180 |0 / 0 |0% / 0% |0 / 0 |0 / 0 |
|skeleton |gpt-oss-20b |20 |20 |2 / 2 |1 / 1 |730 / 804 |118 / 200 |0 / 0 |0% / 0% |0 / 0 |0 / 0 |
|W1 |gemma4-12b |25 |25 |2 / 3 |1 / 2 |2,423 / 6,072 |337 / 457 |0.000243 / 0.000488 |0.12% / 0.24% |0.000249 / 0.000571 |0.00325 / 0.00700 |
|W1 |gpt-oss-20b |25 |25 |2 / 3 |1 / 2 |2,359 / 5,528 |283 / 583 |0.000241 / 0.000407 |0.12% / 0.20% |0.000250 / 0.000510 |0.00325 / 0.00675 |
|W1 |nova-lite |25 |25 |2 / 3 |1 / 2 |3,163 / 6,930 |200 / 317 |0.000253 / 0.000496 |0.13% / 0.25% |same |0.00375 / 0.00800 |
|W2 |gemma4-12b |25 |25 |2 / 3 |1 / 2 |2,163 / 3,841 |183 / 314 |0.000183 / 0.000326 |0.037% / 0.065% |0.000209 / 0.000371 |0.00275 / 0.00500 |
|W2 |gpt-oss-20b |110 |110 |2 / 5 |1 / 4 |1,848 / 4,685 |262 / 698 |0.000187 / 0.000453 |0.037% / 0.091% |0.000198 / 0.000464 |0.00275 / 0.00675 |
|W3 |gpt-oss-20b |48 |24 |7 / 9 |6 / 8 |11,802 / 15,671 |620 / 1,169 |0.000887 / 0.00118 |0.044% / 0.059% |0.00109 / 0.00138 |0.0141 / 0.0182 |
|W4 |gemma4-12b |16 |8 |1 / 1 |not kept |136 / 155 |23.5 / 43 |0.0000147 / 0.0000205 |0.0015% / 0.0021% |0.0000148 / 0.0000185 |0.000500 / 0.000500 |
|W4 |gpt-oss-20b |32 |8 |1 / 1 |not kept |190 / 208 |190 / 300 |0.0000610 / 0.0000884 |0.0061% / 0.0088% |0.0000431 / 0.0000572 |0.000500 / 0.000750 |
|W5 |gemma4-12b |15 |15 |14 / 14 |82 / 82 |8,902 / 9,509 |1,662 / 108,426 |0.00100 / 0.0284 |0.10% / 2.8% |0.000992 / 0.0155 |0.0142 / 0.121 |
|W5 |gpt-oss-20b |18 |18 |14 / 14 |82 / 82 |8,850 / 8,991 |8,972 / 25,462 |0.00286 / 0.00709 |0.29% / 0.71% |0.00201 / 0.00429 |0.0215 / 0.0382 |

The skeleton's calls cost nothing per token: chapter 9's runner sent them to `larkspur-chat-restricted`, whose price is zero. W1's Restricted calls, six in each kept run, are priced at zero for the same reason. No median run costs more than 0.29% of its per-run budget. The highest 95th percentile, 2.8%, is W5's on gemma4-12b, whose kept runs include one where the model looped in its reasoning: the per-run budgets sit far above an ordinary run and bind on a loop.

## 4. W2 against chapter 3

Chapter 3 says "the operations assistant's median at Larkspur is two model calls and one tool call" (ch03:58). Over W2's 135 kept runs the median is 2 model calls and 1 read; over the 108 answers alone (the cases chapter 15's set doesn't mark as a refusal) it is 2 and 1, and each of the six kept runs has the medians 2 and 1, so the claim holds. Of the 135 runs, 77 made two model calls and 94 made one read. The 95th percentile on gpt-oss-20b is 5 calls and 4 reads: in its kept run `gpt-oss-20b 2026-11-02 run1`, seven of 20 runs made five calls. Chapter 5's skeleton, W2's first form, has the same medians over its 40 runs.

Chapter 11's prompt sizes hold as well (ch11:361: "about 850 prompt tokens for the first and 1,000 for the second; Gemma 4 12B's run to about 1,000 and 1,200"). Over the answers with at least two calls, the medians of the first two prompts are 841 and 1,008 tokens on gpt-oss-20b, and 991.5 and 1,181 on Gemma 4 12B.

## 5. Token counts across models

W1's golden set ran on gpt-oss-20b, Gemma 4 12B and Nova Lite (book D-033, companion #55 and #100). Of its 25 cases, 17 are compared: 3 are left out because a call went to `larkspur-chat-restricted`, which served gpt-oss-20b even in the Nova Lite run, and 5 because gpt-oss-20b's run of them ended at the step budget with the harness's refusal. All 17 compared cases took the same number of calls on every model.

|Model |Calls |Input tokens |Output tokens |
|---|---|---|---|
|gpt-oss-20b |34 |38,157 |6,320 |
|gemma4-12b |34 |38,975 |6,442 |
|nova-lite |34 |52,039 |3,401 |

|Ratio |Input, totals (median per case) |Output, totals (median per case) |First call's input |
|---|---|---|---|
|nova-lite over gpt-oss-20b |1.36 (1.37) |0.54 (0.57) |1.71 |
|nova-lite over gemma4-12b |1.34 (1.32) |0.53 (0.59) |1.97 |
|gemma4-12b over gpt-oss-20b |1.02 (1.03) |1.02 (0.93) |0.87 |

The first call's prompt is the same text on every model, so its ratio, 1.71 for Nova Lite over gpt-oss-20b, is the tokenizer and the chat template alone; over whole cases, with the pages each model's searches returned, it is 1.36. Output goes the other way, 0.54: gpt-oss-20b's completion tokens include its reasoning, and Nova Lite writes shorter answers. The ratios the priced estimates carry: a cost priced from gpt-oss-20b's counts multiplies input by 1.36 and output by 0.54 to approach Nova Lite's count, and one from Gemma 4 12B's by 1.34 and 0.53. They come from one workflow's 17 cases; W2's and W5's prompts are shaped differently, so elsewhere they are an estimate.

## 6. The table as LiteLLM's custom prices

`ledger/litellm.prices.yaml` is generated from the table: every priced deployment with `input_cost_per_token` and `output_cost_per_token` in `litellm_params`, one `model_list` per gateway pair. Each list was loaded into LiteLLM 1.106.6's Router in a fresh process with `LITELLM_LOCAL_MODEL_COST_MAP=True` and the network blocked, and each alias answered one mocked call of known usage. The cost was read as the gateway's callback receives it (`response_cost`) and from `completion_cost` with the deployment's id, as the proxy calls it.

|Gateway |Alias |Deployment |Tokens in / out |Expected |response_cost |completion_cost by id |Budget checks skipped |
|---|---|---|---|---|---|---|---|
|aws |`larkspur-chat` |`nova-lite-ca` |1,000 / 100 |0.00008960 |0.00008960 |0.00008960 |no |
|aws |`larkspur-chat-fallback` |`nova-lite-us` |1,000 / 100 |0.00008400 |0.00008400 |0.00008400 |no |
|aws |`larkspur-chat-restricted` |`vllm-gpt-oss-20b` |1,000 / 100 |0 |0 |0 |yes |
|aws |`larkspur-embed` |`titan-embed-v2-ca` |10 / 0 |0.000001000 |0.000001000 |embedding |no |
|azure |`larkspur-chat` |`gpt-4o-canada-east` |1,000 / 100 |0.004235 |0.004235 |0.004235 |no |

The custom price takes effect on every deployment, the Canadian profile included, which the built-in map doesn't know (section 7). Priced by its model name alone in the same process, the Canadian deployment comes to zero: registering the deployment leaves an empty entry under its model name, so a cost computed from the name anywhere in the gateway's process is zero, with no error. The ledger prices by deployment, as the gateway's cost line does.

The self-hosted alias is priced at exactly zero, and LiteLLM's own predicate (`is_model_cost_zero`) says its requests skip every budget check (fact sheet 8.1). Chapter 5's callback sums the same zero into its per-run budget, so that budget never stops a run on the alias either. What stops a loop there is the request rate of each manifest that lists the alias (`w2-ops-assistant` 120 a minute, `w1-knowledge` 120 a minute, `w3-incident` 60 a minute) and each harness's step budget (ch09:198).

## 7. LiteLLM's built-in map against the table

`ledger/litellm_map.py`, LiteLLM 1.106.6 with `LITELLM_LOCAL_MODEL_COST_MAP=True`; the map in use is the wheel's own file (`model_prices_and_context_window_backup.json`): yes. Prices per million tokens, input / output; the last column is the table's price over LiteLLM's.

|Deployment |Name |What |Map entry |LiteLLM prices it at |Table |Difference |Table / LiteLLM |
|---|---|---|---|---|---|---|---|
|`nova-lite-ca` |`bedrock/ca.amazon.nova-lite-v1:0` |the Canadian profile, called in ca-central-1, as chapter 6 calls it |none |ModelNotMappedError |0.064 / 0.256 |missing | |
|`nova-lite-ca` |`bedrock/us.amazon.nova-lite-v1:0` |the US profile, called in ca-central-1 |0.06 / 0.24 |0.06 / 0.24 |0.064 / 0.256 |different |1.0667 |
|`nova-lite-us` |`bedrock/us.amazon.nova-lite-v1:0` |the US profile, called in us-east-2 |0.06 / 0.24 |0.06 / 0.24 |0.06 / 0.24 |equal |1.0000 |
|`nova-lite-us` |`bedrock/amazon.nova-lite-v1:0` |the bare model In-Region in us-east-2, as the fallback calls it |0.06 / 0.24 |0.06 / 0.24 |0.06 / 0.24 |equal |1.0000 |
|`nova-lite-ca` |`bedrock/ca-central-1/amazon.nova-lite-v1:0` |the bare model with ca-central-1 as LiteLLM's Region prefix |none |0.06 / 0.24 |0.064 / 0.256 |base price |1.0667 |
|`nova-lite-us` |`bedrock/us-east-2/amazon.nova-lite-v1:0` |the bare model with us-east-2 as LiteLLM's Region prefix |none |0.06 / 0.24 |0.06 / 0.24 |base price |1.0000 |
|`vllm-gpt-oss-20b` |`hosted_vllm/gpt-oss-20b` |chapter 9's self-hosted model behind vLLM |none |ModelNotMappedError |0.0 / 0.0 |missing | |
|`titan-embed-v2-ca` |`bedrock/amazon.titan-embed-text-v2:0` |Titan Text Embeddings V2, called in ca-central-1 |0.02 / 0.0 |0.02 / 0.0 |0.1 / 0.0 |different |5.0000 |
|`gpt-4o-canada-east` |`azure/gpt-4o-2024-11-20` |gpt-4o 2024-11-20, a Standard deployment in Canada East |2.5 / 10.0 |2.5 / 10.0 |3.025 / 12.1 |different |1.2100 |
|`gemini-3.5-flash-montreal` |`vertex_ai/gemini-3.5-flash` |Gemini 3.5 Flash in Montréal |1.5 / 9.0 |1.5 / 9.0 |none |no table price | |
|`bedrock-gpt-oss-120b-use1` |`bedrock/openai.gpt-oss-120b-1:0` |gpt-oss-120b on Bedrock's Standard tier in us-east-1, chapter 9's crossover |0.15 / 0.6 |0.15 / 0.6 |0.15 / 0.6 |equal |1.0000 |

It reproduces section 8.1's probe: the map has no entry for the Canadian profile, which LiteLLM can't price (`ModelNotMappedError`), and a name with a Region prefix prices at the base model's entry. The differences, one by one:

- Missing: the Canadian profile, `ca.amazon.nova-lite-v1:0`. Without the custom price a call to `larkspur-chat` has no cost at all. The self-hosted model has no entry either and needs its explicit zero.
- A price the map can't hold: Bedrock bills a profile at the price of the Region it is called in (ch06:162), and the map keys one price to a name. Every Nova Lite name LiteLLM can price comes to us-east-2's rate, so the Canadian price, 6.7 percent higher, is out of its reach, whether the name is the US profile called in ca-central-1 or the bare model with LiteLLM's ca-central-1 prefix.
- Different prices: Titan Text Embeddings V2 costs 5 times the map's price in ca-central-1, and the regional gpt-4o deployment in Canada East 1.21 times the map's Azure entry, which is the Global price. The map keys neither to a Region.
- Equal: the bare Nova Lite model and the US profile in us-east-2, and gpt-oss-120b on Bedrock in us-east-1. Gemini 3.5 Flash has a map price and no table price, since no source the table may use prices it.

## 8. What the cost lines leave out: the guardrail

Chapter 6's gateway runs a Bedrock guardrail before and after every call on the managed aliases (`labs/ch06/gateway/litellm.aws.yaml`), with a content policy and a sensitive-information policy (`labs/ch06/terraform/guardrail.tf`), at 0.25 US dollars per 1,000 text units together in ca-central-1. A text unit is up to 1,000 characters, per policy, and LiteLLM sends the guardrail the text of every message, tool results included. The gateway's cost line records the model's tokens and not the guardrail, so `price.guardrail_estimate` prices it from each call's tokens at LiteLLM's 4 characters a token. It is an estimate: prompt tokens also count the tool definitions and the chat template, which the guardrail doesn't read, and four characters a token is LiteLLM's rule of thumb, not a measurement of these prompts.

|Workflow |Model |Tokens' cost per run |Guardrail estimate per run |Guardrail over tokens |
|---|---|---|---|---|
|W1 |gemma4-12b |0.000243 / 0.000488 |0.00325 / 0.00700 |13.96 |
|W1 |gpt-oss-20b |0.000241 / 0.000407 |0.00325 / 0.00675 |14.24 |
|W1 |nova-lite |0.000253 / 0.000496 |0.00375 / 0.00800 |15.63 |
|W2 |gemma4-12b |0.000183 / 0.000326 |0.00275 / 0.00500 |15.38 |
|W2 |gpt-oss-20b |0.000187 / 0.000453 |0.00275 / 0.00675 |13.99 |
|W3 |gpt-oss-20b |0.000887 / 0.00118 |0.0141 / 0.0182 |15.53 |
|W4 |gemma4-12b |0.0000147 / 0.0000205 |0.000500 / 0.000500 |32.12 |
|W4 |gpt-oss-20b |0.0000610 / 0.0000884 |0.000500 / 0.000750 |8.99 |
|W5 |gemma4-12b |0.00100 / 0.0284 |0.0142 / 0.121 |5.61 |
|W5 |gpt-oss-20b |0.00286 / 0.00709 |0.0215 / 0.0382 |6.23 |

At Nova Lite's price the guardrail costs 6 to 32 times the tokens it screens, less where the calls write more (W5's calls on gpt-oss-20b carry long reasoning, which the tokens' cost counts at the output price). Over a month, W2's guardrail comes to 63% of its `per_month_usd` at chapter 9's volume, against 4.5% for its tokens (section 9). A ledger that sums the cost lines misses the larger part of chapter 6's per-call cost, so the guardrail needs a line of its own, from ApplyGuardrail's own usage or the bill's guardrail usage types.

## 9. A month

`ledger/volumes.yaml` gives each workflow's month with a source for each number. Chapters 1 to 14 were searched for each workflow's volume first; where the book states one, the line is cited, and where it doesn't, the number is a lab assumption, not in the book. A month is 730 hours, as in the cost sheets.

|Workflow |A month |Source |Basis |
|---|---|---|---|
|W1 |6,000 questions |lab assumption, not in the book |about two questions a month for each of the roughly three thousand people in technology (ch01:298) |
|W2 |100,000,000 tokens |ch09:405 |at Larkspur's estimate of 100 million tokens a month |
|W3 |300 incidents |lab assumption, not in the book |about ten incidents a day reach the incident workflow |
|W4 |200 changes |ch13:9 |Marcus Bell's board approves about two hundred changes a month |
|W5 |30 nights plus 4 alarms |nights: ch14:29; alarms: lab assumption, not in the book |nights: A nightly schedule or a budget alert starts the harness; alarms: about one budget or anomaly alarm a week; chapter 14 names the trigger (ch14:29) and not its rate |

The per-run figures are the reference model's, gpt-oss-20b, over every kept run on it that kept tokens. W2's month is chapter 9's 100 million tokens, 43,030 questions at W2's measured tokens per run; chapter 12's "hundred questions an hour" (ch12:18) would be 73,000 a month, the same order. W3's and W4's runs are priced at step 3b's measured tokens, the only runs of theirs that kept any: W3 made 5.92 calls a run there, 0.38 of them to the restricted alias, at 1,640 input tokens a call, and W4 one call of 193. Section 13 sets them against step 2's proxies.

|Workflow |Runs a month |Calls a month |Tokens a month |Direct cost (USD) |Share of per_month_usd |Range over kept runs |Recounted as Nova Lite |Guardrail estimate |Basis |
|---|---|---|---|---|---|---|---|---|---|
|W1 |6,000 |13,200 |19,181,280 |1.44 |1.4% |1.4% |1.6% |21% |measured |
|W2 |43,030 |89,580 |100,000,000 |9.01 |4.5% |4.3% to 4.9% |4.7% |63% |measured |
|W3 |300 |1,775 |3,112,038 |0.213 |0.043% |0.043% |0.051% |0.66% |measured on the 24 of 48 runs with tokens |
|W4 |200 |200 |77,775 |0.0125 |0.0063% |0.0063% |0.0044% |0.056% |measured on the 8 of 32 runs with tokens |
|W5 |34 |351 |604,660 |0.112 |0.11% |0.068% to 0.16% |0.072% |0.70% |measured |

Direct costs, the cost lines summed, are a small share of every monthly budget: W2's is the largest, at 4.5%. The range is the month priced from each kept run on its own. The recounted column multiplies the managed calls' tokens by section 5's ratios. The guardrail's estimate is larger than the tokens for every workflow (section 8).

## 10. Allocating what isn't a call

### The restricted alias's tenants

Which workflows use `larkspur-chat-restricted` is one of the plan's consistency notes. Each source says:

- The manifests: W1, W2, W3 list the alias.
- The kept runs: W1 sent 18 calls and W3 sent 20 calls to it, and the skeleton 77, chapter 9's own test of the path. W2 sent none: its class is Internal at most, and all 281 of its calls went to `larkspur-chat`.
- Chapter 9 (ch09:18, ch09:200): two workflows, the incident workflow and the operations assistant, whose manifest lists the alias.
- Chapter 10 (ch10:72, ch10:78): W1's Restricted calls go to the self-hosted model from month six.

The GPUs cost two replicas at the smallest g6e size's price, the lower bound chapter 9 uses, every hour of the month: 2,717.06 US dollars. The tenants' busy time is the tokens each sent the alias at chapter 9's measured throughput of gpt-oss-20b (5,575.4 prompt and 181.0 output tokens a second on the workstation's GPU, a stand-in for one L40S and an upper bound on the time, since vLLM batches). That share of the hours is split among the tenants by their share of the alias's tokens, and the rest is idle, the platform team's line (O-D6). Both readings:

Read with chapter 9 (W2, W3 as the tenants), they used 0.0048% of the GPUs' hours, and 99.995% were idle.

|Tenant |Tokens a month |Token share |GPU share (USD) |Share of per_month_usd |Without an idle line (USD) |Without an idle line, share |
|---|---|---|---|---|---|---|
|W2 |0 |0% |0 |0% |0 |0% |
|W3 |284,075 |100% |0.129 |0.026% |2,717.06 |543% |
|idle, the platform team | | |2,716.93 | | | |

Read with the manifests and chapter 10 (W1, W2, W3 as the tenants), they used 0.034% of the GPUs' hours, and 99.966% were idle.

|Tenant |Tokens a month |Token share |GPU share (USD) |Share of per_month_usd |Without an idle line (USD) |Without an idle line, share |
|---|---|---|---|---|---|---|
|W1 |1,933,440 |87.2% |0.795 |0.80% |2,368.99 |2,370% |
|W2 |0 |0% |0 |0% |0 |0% |
|W3 |284,075 |12.8% |0.117 |0.023% |348.07 |69.6% |
|idle, the platform team | | |2,716.15 | | | |

With an idle line, the tenants' share is cents and the platform team carries almost all of the GPUs. Without one, the whole cost split by tokens would put 2,370% of W1's monthly budget on W1, or, read as chapter 9 reads it, 543% of W3's on W3, which is why O-D6 keeps the idle line apart. W1's share is large here because its golden set puts three of 25 cases on Restricted pages; production's share isn't measured.

Recommendation, for the chapter and not made in the book here: state three tenants, the workflows whose manifests list the alias (W1, W2, W3), and split the GPU hours by each month's measured tokens, so the list can't drift from the bill. W1 and W3 send Restricted prompts (chapters 10 and 12), and W2 sends nothing in its kept runs, so it pays nothing until it does. Chapter 9's "two workflows" (ch09:18, ch09:200) leaves out W1, which in this month sends most of the alias's tokens; correcting it is a note for book #23.

### The platform's fixed costs

|Item |Quantity |Per |Unit price (USD) |A month (USD) |Basis |Source |
|---|---|---|---|---|---|---|
|the gateway's database |1 |hour |0.07 |51.10 |priced |lab assumption, not in the book |
|the database's storage |20 |GB-month |0.127 |2.54 |priced |lab assumption, not in the book |
|Redis |1 |hour |0.018 |13.14 |priced |lab assumption, not in the book |
|the gateway's compute |2 |hour |0.09576 |139.81 |stand-in |lab assumption, not in the book |
|Langfuse's stores |1 |hour |0.1664 |121.47 |stand-in |lab assumption, not in the book |
|Langfuse's disk |100 |GB-month |0.08 |8.00 |stand-in |lab assumption, not in the book |
|chapter 6's interface endpoints |16 |hour |0.011 |128.48 |priced |labs/ch06/cost/cost-sheet.yaml |
|chapter 6's two KMS keys |2 |month |1.0 |2.00 |priced |labs/ch06/cost/cost-sheet.yaml |
|chapter 7's Private Service Connect endpoint |1 |hour |none |none |parameter |ch07:88 |
|chapter 8's private endpoints |3 |hour |none |none |parameter |ch08:59 |
|LiteLLM's enterprise license |1 |month |none |none |parameter |ch05:502 |
|Langfuse's enterprise features |1 |month |none |none |parameter |ch05:502 |

Priced lines come to 466.54 US dollars a month, 269.28 of them at us-east-2's EC2 prices standing in for ca-central-1's, which no source has. The lines with no price stay parameters: chapter 7's Private Service Connect endpoint; chapter 8's private endpoints; LiteLLM's enterprise license; Langfuse's enterprise features. The sizes are lab assumptions, each with its basis in `volumes.yaml`.

|Workflow |Share of calls |By calls (USD) |Of per_month_usd |Share of tokens |By tokens (USD) |Of per_month_usd |Direct (USD) |GPU share (USD) |
|---|---|---|---|---|---|---|---|---|
|W1 |12.6% |58.59 |58.6% |15.6% |72.77 |72.8% |1.44 |0.795 |
|W2 |85.2% |397.62 |199% |81.3% |379.38 |190% |9.01 |0 |
|W3 |1.69% |7.88 |1.58% |2.53% |11.81 |2.36% |0.213 |0.117 |
|W4 |0.190% |0.888 |0.444% |0.0632% |0.295 |0.148% |0.0125 |0 |
|W5 |0.334% |1.56 |1.56% |0.492% |2.29 |2.29% |0.112 |0 |

Split by gateway calls (O-D6), the fixed costs put 199% of W2's monthly budget on W2, about 44 times its direct cost, so they are shown apart from the direct costs its owner controls. Chapter 2 splits the shared costs "in proportion to tokens" (ch02:144) and O-D6 by calls; here the two give nearly the same shares, because tokens per call vary little across the workflows. Calls are the better driver for these lines, since the database, Redis, the gateway's compute and the trace store grow with requests, while tokens are already the direct costs. The chapter should name one; if it keeps O-D6's calls, ch02:144 is a second correction for book #23. O-D6 was amended on 3 November 2026 (companion #14): the fixed costs are split by tokens, 190% of W2's monthly budget and about 42 times its direct cost, and chapter 18 prints that split.

## 11. Sampling: the month from traces

For W1, W2 and W5, a month of runs is drawn from the workflow's kept runs on every model, with seed 20261103 and as many runs as section 9 gives it, each priced by its cost lines; their total is the truth. Then, over 1,000 seeds, traces are kept by head sampling and the kept runs' cost is scaled back up. The error is the estimate over the truth, less one. W3 and W4 aren't sampled: only step 3b's runs of theirs kept tokens.

|Workflow |Runs |Head rate |Mean error |5th to 95th percentile |Spread (std) |Runs whose cost is unknown |Seeds with no trace |
|---|---|---|---|---|---|---|---|
|W1 |6,000 |1% |0.36% |-22% to 23% |14% |99.0% |0 |
|W1 |6,000 |10% |-0.015% |-7.5% to 7.2% |4.4% |90.0% |0 |
|W1 |6,000 |50% |-0.044% |-2.5% to 2.3% |1.5% |50.0% |0 |
|W1 |6,000 |100% |0% |0% to 0% |0% |0% |0 |
|W2 |43,030 |1% |0.068% |-9.4% to 9.3% |5.7% |99.0% |0 |
|W2 |43,030 |10% |0.075% |-2.8% to 3.0% |1.8% |90.0% |0 |
|W2 |43,030 |50% |0.019% |-0.92% to 0.98% |0.58% |50.0% |0 |
|W2 |43,030 |100% |0% |0% to 0% |0% |0% |0 |
|W5 |34 |1% |4.3% |-100% to 331% |340% |99.0% |707 |
|W5 |34 |10% |-0.039% |-99% to 166% |96% |89.9% |34 |
|W5 |34 |50% |-0.71% |-56% to 55% |32% |50.0% |0 |
|W5 |34 |100% |0% |0% to 0% |0% |0% |0 |

Head sampling is unbiased at every rate, and exact at 100 percent. Its spread grows as the month shrinks: at 1 percent W2's 43,030 runs give a month between 9.4% below and 9.3% above the truth nine times in ten, and W5's 34 nights keep no trace at all in 707 of 1,000 seeds. At any rate below 100 percent, the unsampled runs' own cost is unknown from the traces, which is why the cost of a run comes from its cost lines (O-D5).

Tail sampling, as the collector does it (O-D3), keeps every failed run and every run over its budget, and a share of the rest. A failed run is one whose output failed its golden check, standing in for the error status a sampler reads; no kept run costs more than its per-run budget at these prices. W2's failed runs cost 1.7 times the rest, mostly budget stops.

|Workflow |Failed |Share of the rest kept |Traces kept |Naive mean error |Weighted mean error (5th to 95th) |
|---|---|---|---|---|---|
|W1 |14.3% |1% |15.2% |-1.80% |-0.36% (-21% to 22%) |
|W1 |14.3% |10% |22.9% |-1.09% |-0.083% (-6.7% to 6.0%) |
|W2 |21.6% |1% |22.3% |48.2% |-0.024% (-6.7% to 6.2%) |
|W2 |21.6% |10% |29.4% |33.3% |0.052% (-2.0% to 2.0%) |
|W5 |64.7% |1% |65.1% |44.9% |-0.49% (-5.8% to 7.5%) |
|W5 |64.7% |10% |68.2% |39.2% |0.044% (-5.8% to 15%) |

Scaled naively, by the share of runs kept, the estimate takes the failed runs' cost for everyone's and overstates W2's month by 48% when one in a hundred of the rest is kept, and by 33% at one in ten. Weighted, each run kept from the rest counting for the runs its share stands for, the estimate is unbiased; a trace store can apply that weight only if each trace records the share it was kept at.

## 12. What the book may print

The book prints ratios and shares of the manifests' budgets and never a price (style guide 12.4); the prices stay in `ledger/prices.yaml`, `ledger.json`, and this record. From this ledger it may print:

- Cost per run as a share of `per_run_usd` (section 3), and the month as a share of `per_month_usd` (section 9), for example W2's month at 4.5% of its budget.
- W2's medians against chapter 3: two model calls and one read, from the kept runs (section 4).
- The token ratios: Nova Lite counted 1.36 times gpt-oss-20b's input and 0.54 times its output on W1's cases (section 5).
- The guardrail's estimate as a multiple of the tokens' cost, and as a share of a monthly budget (section 8).
- The GPUs' idle share, 99.966%, and the tenants' token shares (section 10).
- The fixed costs' shares of calls, W2's 85.2%, and their share of each monthly budget (section 10).
- The sampling errors, for example W2's month within about 9 percent nine times in ten at 1 percent, and the naive tail estimate's bias (section 11).
- W3's and W4's tokens per call as multiples of step 2's proxies, and their months as shares of their budgets before and after (section 13).

## 13. What step 3b's measured tokens changed

Step 2 priced W3's and W4's calls by proxy, each at W2's or W5's mean tokens per call on gpt-oss-20b (`volumes.yaml`, `tokens_proxy`), because their kept runs held no tokens. Step 3b's runs kept the gateway's lines, and the month now prices both at their own. Step 2's figures here are computed again from chapter 15's kept runs alone, which reproduces them.

|Workflow |Figures |Basis |Runs |Calls a run |Restricted calls a run |Input tokens a call |Output tokens a call |Cost per run (USD) |
|---|---|---|---|---|---|---|---|---|
|W3 |step 2's proxy |proxy: W2's tokens per call |24 |5.71 |0.46 |963 |157 |0.000535 |
|W3 |step 3b, measured |measured on the 24 of 48 runs with tokens |24 |5.92 |0.38 |1,640 |114 |0.000708 |
|W4 |step 2's proxy |proxy: W5's tokens per call |24 |1.00 |0 |640 |1,081 |0.000318 |
|W4 |step 3b, measured |measured on the 8 of 32 runs with tokens |8 |1.00 |0 |193 |196 |0.0000626 |

W3's calls carried 1.70 times the proxy's input tokens and 0.72 times its output; W4's one call 0.30 times its input and 0.18 times its output. Each pair below is step 2's figure, then step 3b's, for every workflow: W2's moves because its golden set ran once more for fig-16-01, and the shares move with W3's and W4's tokens. The GPU column is the manifests' and chapter 10's reading of the tenants.

|Workflow |Tokens a month |Direct share of per_month_usd |Share of calls |Share of tokens |Fixed costs by calls (USD) |Fixed costs by tokens (USD) |GPU share (USD) |
|---|---|---|---|---|---|---|---|
|W1 |19,181,280 / 19,181,280 |1.4% / 1.4% |12.6% / 12.6% |15.7% / 15.6% |58.79 / 58.59 |73.32 / 72.77 |0.794 / 0.795 |
|W2 |100,000,000 / 100,000,000 |4.5% / 4.5% |85.2% / 85.2% |81.9% / 81.3% |397.66 / 397.62 |382.26 / 379.38 |0 / 0 |
|W3 |1,918,095 / 3,112,038 |0.032% / 0.043% |1.63% / 1.69% |1.57% / 2.53% |7.63 / 7.88 |7.33 / 11.81 |0.0632 / 0.117 |
|W4 |344,209 / 77,775 |0.032% / 0.0063% |0.191% / 0.190% |0.282% / 0.0632% |0.891 / 0.888 |1.32 / 0.295 |none / none |
|W5 |604,660 / 604,660 |0.11% / 0.11% |0.335% / 0.334% |0.495% / 0.492% |1.56 / 1.56 |2.31 / 2.29 |none / none |

W3's month went from 0.032% to 0.043% of its `per_month_usd` and W4's from 0.032% to 0.0063%. Split by tokens, W3's share of the platform's fixed costs went from 1.57% to 2.53% and W4's from 0.282% to 0.0632%. Split by calls, which step 2 counted from the kept runs, W3's went from 1.63% to 1.69%: step 3b's run made 5.92 calls an incident where the kept run made 5.71.

## 14. The judge's tokens, under the workflow judged

Chapter 15's judge made 1,439 judgments in three runs on 3 November 2026, 1,231,927 prompt and 338,238 completion tokens, each through chapter 5's gateway under the judged workflow's tag and with the case's class, so each is one cost line here under the workflow judged (ch15:305), marked `judge`, with the kept run it read (`judged`) and its slice. Chapter 15 kept the first and second runs in `judge-v1/` and `judge-v2/` and the third as its current files, which judged W1, W2 and W3 again and hold W4 and W5's files of the second run; 361 lines of the current log are that run's judgments, counted once, under the run that made them (`labs/ch15/judge/run_judge.py`'s reading of its folder). The calls went to `larkspur-chat-restricted` (restricted 230) and `larkspur-chat` (confidential 782, internal 312, restricted 115); the last column of the first table prices each at its alias's deployment in the dated table (0.142 USD in all).

|Run |Judge |Judgments |Prompt tokens |Completion tokens |Total |Completion a judgment, median |Seconds |USD at the table |
|---|---|---|---|---|---|---|---|---|
|v1 |Gemma 4 12B |360 |321,810 |10,799 |332,609 |30 |188.0 |0.0234 |
|v1 |gpt-oss-20b |240 |210,383 |139,746 |350,129 |563 |904.4 |0.0492 |
|v2 |Gemma 4 12B |360 |322,176 |10,828 |333,004 |30 |189.5 |0.0202 |
|v2 |gpt-oss-20b |240 |210,805 |138,566 |349,371 |563 |882.6 |0.0406 |
|v3 |Gemma 4 12B |152 |105,984 |4,078 |110,062 |28 |67.20 |0.00464 |
|v3 |gpt-oss-20b |87 |60,769 |34,221 |94,990 |337 |225.3 |0.00404 |

Against what it judged. Each judgment is set beside the tokens of the output it read: the kept run's own cost lines for the case, every model call of the run for W1 to W4 and the one call that wrote the pull request body for W5, paired to the night's pull requests in the order it wrote them; a padded copy counts the original's tokens. W3 and W4's judged outputs are chapter 15's kept runs, which kept no tokens (step 2), so step 3b's run of the same case on the same model stands in for them, and the basis column says so; a ratio never mixes the two. The ratios are the judge's tokens over the judged outputs' tokens, in total over the group's judgments: prompt, completion, and total:

|Workflow |Judge |Judgments |Judge's tokens, prompt / completion / total |Judged outputs' tokens, prompt / completion / total |Ratio, prompt / completion / total |Basis |
|---|---|---|---|---|---|---|
|W1 |Gemma 4 12B |165 |118,984 / 4,625 / 123,609 |470,352 / 49,236 / 519,588 |0.25 / 0.09 / 0.24 |measured |
|W1 |gpt-oss-20b |171 |123,707 / 68,260 / 191,967 |531,852 / 49,308 / 581,160 |0.23 / 1.38 / 0.33 |measured |
|W1 |both judges |336 |242,691 / 72,885 / 315,576 |1,002,204 / 98,544 / 1,100,748 |0.24 / 0.74 / 0.29 |measured |
|W2 |Gemma 4 12B |222 |144,666 / 5,731 / 150,397 |480,663 / 69,603 / 550,266 |0.30 / 0.08 / 0.27 |measured |
|W2 |gpt-oss-20b |90 |57,810 / 32,946 / 90,756 |224,457 / 18,024 / 242,481 |0.26 / 1.83 / 0.37 |measured |
|W2 |both judges |312 |202,476 / 38,677 / 241,153 |705,120 / 87,627 / 792,747 |0.29 / 0.44 / 0.30 |measured |
|W3 |Gemma 4 12B |69 |53,571 / 2,039 / 55,610 |645,669 / 48,132 / 693,801 |0.08 / 0.04 / 0.08 |stand-in |
|W3 |both judges |69 |53,571 / 2,039 / 55,610 |645,669 / 48,132 / 693,801 |0.08 / 0.04 / 0.08 |stand-in |
|W4 |Gemma 4 12B |54 |27,353 / 1,418 / 28,771 |9,900 / 9,136 / 19,036 |2.76 / 0.16 / 1.51 |stand-in |
|W4 |gpt-oss-20b |32 |17,758 / 8,895 / 26,653 |4,902 / 2,474 / 7,376 |3.62 / 3.60 / 3.61 |stand-in |
|W4 |both judges |86 |45,111 / 10,313 / 55,424 |14,802 / 11,610 / 26,412 |3.05 / 0.89 / 2.10 |stand-in |
|W5 |Gemma 4 12B |362 |405,396 / 11,892 / 417,288 |233,934 / 307,636 / 541,570 |1.73 / 0.04 / 0.77 |measured |
|W5 |gpt-oss-20b |274 |282,682 / 202,432 / 485,114 |180,488 / 68,476 / 248,964 |1.57 / 2.96 / 1.95 |measured |
|W5 |both judges |636 |688,078 / 214,324 / 902,402 |414,422 / 376,112 / 790,534 |1.66 / 0.57 / 1.14 |measured |

Chapter 15 says (ch15:156) that a judge that thinks before it answers writes more tokens than the answer it judges. The result files record gpt-oss-20b thinking at the model's default and Gemma 4 12B thinking off. The median completion tokens a judgment is 551 for gpt-oss-20b over 567 and 29 for Gemma 4 12B over 872 judgments, the three runs' judgments that the ledger counts; chapter 15's own medians are over its current files' calls: 559 for gpt-oss-20b over 240 calls and 29 for Gemma 4 12B over 360 calls.

In completion tokens, in total, gpt-oss-20b wrote more than the outputs it read in every workflow it judged: the ratios of its completion tokens to the outputs' are W1 (1.38), W2 (1.83), W4 (3.60, on the stand-in) and W5 (2.96); W3 was judged by Gemma 4 12B alone. Judgment by judgment it wrote more than the output in 117 of 171 W1 judgments, 84 of 90 W2 judgments, 27 of 32 W4 judgments and 254 of 274 W5 judgments. So the sentence holds as written, for completion tokens, in every workflow that judge judged.

In all tokens, which count a prompt token like a completion token, gpt-oss-20b's total is above the output's for W4 (3.61, on the stand-in) and W5 (1.95) and below it for W1 (0.33) and W2 (0.37). These are token figures and not prices.

In completion tokens, in total, Gemma 4 12B, with its thinking off, wrote fewer than the outputs it read in every workflow it judged: the ratios are W1 (0.09), W2 (0.08), W3 (0.04, on the stand-in), W4 (0.16, on the stand-in) and W5 (0.04); judgment by judgment it wrote more than the output in 6 of 54 W4 judgments. In all tokens its total is above the output's for W4 (1.51, on the stand-in) and below it for W1 (0.24), W2 (0.27), W3 (0.08, on the stand-in) and W5 (0.77).

|Workflow |Judge |Basis |Judgments |Ratio, prompt / completion / total |In total: more than the output's tokens |In total: more completion tokens |In total: more prompt tokens |Judgments with more completion tokens than the output |
|---|---|---|---|---|---|---|---|---|
|W1 |Gemma 4 12B |measured |165 |0.25 / 0.09 / 0.24 |no |no |no |0 |
|W1 |gpt-oss-20b |measured |171 |0.23 / 1.38 / 0.33 |no |yes |no |117 |
|W2 |Gemma 4 12B |measured |222 |0.30 / 0.08 / 0.27 |no |no |no |0 |
|W2 |gpt-oss-20b |measured |90 |0.26 / 1.83 / 0.37 |no |yes |no |84 |
|W3 |Gemma 4 12B |stand-in |69 |0.08 / 0.04 / 0.08 |no |no |no |0 |
|W4 |Gemma 4 12B |stand-in |54 |2.76 / 0.16 / 1.51 |yes |no |yes |6 |
|W4 |gpt-oss-20b |stand-in |32 |3.62 / 3.60 / 3.61 |yes |yes |yes |27 |
|W5 |Gemma 4 12B |measured |362 |1.73 / 0.04 / 0.77 |no |no |yes |0 |
|W5 |gpt-oss-20b |measured |274 |1.57 / 2.96 / 1.95 |yes |yes |yes |254 |

By slice, over the judgments whose outputs kept tokens:

|Slice |Judgments |Judge's tokens, prompt / completion / total |Completion a judgment, median |With the output's tokens |Judged outputs' tokens, prompt / completion / total |Ratio, prompt / completion / total |
|---|---|---|---|---|---|---|
|cross |1,227 |1,058,957 / 282,414 / 1,341,371 |36 |1,116 |1,803,030 / 496,348 / 2,299,378 |0.55 / 0.56 / 0.55 |
|self |120 |93,070 / 33,431 / 126,501 |96 |104 |194,957 / 45,558 / 240,515 |0.44 / 0.69 / 0.48 |
|padded |92 |79,900 / 22,393 / 102,293 |35 |64 |123,759 / 20,377 / 144,136 |0.48 / 0.92 / 0.54 |

By workflow, run, and judge:

|Workflow |Run |Judge |Judgments |Judge's tokens, prompt / completion / total |Judged outputs' tokens, prompt / completion / total |Ratio, prompt / completion / total |Basis |
|---|---|---|---|---|---|---|---|
|W1 |v1 |Gemma 4 12B |55 |39,478 / 1,547 / 41,025 |156,784 / 16,412 / 173,196 |0.25 / 0.09 / 0.24 |measured |
|W1 |v1 |gpt-oss-20b |57 |40,869 / 22,779 / 63,648 |177,284 / 16,436 / 193,720 |0.23 / 1.39 / 0.33 |measured |
|W1 |v2 |Gemma 4 12B |55 |39,713 / 1,548 / 41,261 |156,784 / 16,412 / 173,196 |0.25 / 0.09 / 0.24 |measured |
|W1 |v2 |gpt-oss-20b |57 |41,339 / 22,242 / 63,581 |177,284 / 16,436 / 193,720 |0.23 / 1.35 / 0.33 |measured |
|W1 |v3 |Gemma 4 12B |55 |39,793 / 1,530 / 41,323 |156,784 / 16,412 / 173,196 |0.25 / 0.09 / 0.24 |measured |
|W1 |v3 |gpt-oss-20b |57 |41,499 / 23,239 / 64,738 |177,284 / 16,436 / 193,720 |0.23 / 1.41 / 0.33 |measured |
|W2 |v1 |Gemma 4 12B |74 |48,100 / 1,934 / 50,034 |160,221 / 23,201 / 183,422 |0.30 / 0.08 / 0.27 |measured |
|W2 |v1 |gpt-oss-20b |30 |19,270 / 10,982 / 30,252 |74,819 / 6,008 / 80,827 |0.26 / 1.83 / 0.37 |measured |
|W2 |v2 |Gemma 4 12B |74 |48,259 / 1,922 / 50,181 |160,221 / 23,201 / 183,422 |0.30 / 0.08 / 0.27 |measured |
|W2 |v2 |gpt-oss-20b |30 |19,270 / 10,982 / 30,252 |74,819 / 6,008 / 80,827 |0.26 / 1.83 / 0.37 |measured |
|W2 |v3 |Gemma 4 12B |74 |48,307 / 1,875 / 50,182 |160,221 / 23,201 / 183,422 |0.30 / 0.08 / 0.27 |measured |
|W2 |v3 |gpt-oss-20b |30 |19,270 / 10,982 / 30,252 |74,819 / 6,008 / 80,827 |0.26 / 1.83 / 0.37 |measured |
|W3 |v1 |Gemma 4 12B |23 |17,817 / 675 / 18,492 |215,223 / 16,044 / 231,267 |0.08 / 0.04 / 0.08 |stand-in |
|W3 |v2 |Gemma 4 12B |23 |17,870 / 691 / 18,561 |215,223 / 16,044 / 231,267 |0.08 / 0.04 / 0.08 |stand-in |
|W3 |v3 |Gemma 4 12B |23 |17,884 / 673 / 18,557 |215,223 / 16,044 / 231,267 |0.08 / 0.04 / 0.08 |stand-in |
|W4 |v1 |Gemma 4 12B |27 |13,717 / 697 / 14,414 |4,950 / 4,568 / 9,518 |2.77 / 0.15 / 1.51 |stand-in |
|W4 |v1 |gpt-oss-20b |16 |8,903 / 4,769 / 13,672 |2,451 / 1,237 / 3,688 |3.63 / 3.86 / 3.71 |stand-in |
|W4 |v2 |Gemma 4 12B |27 |13,636 / 721 / 14,357 |4,950 / 4,568 / 9,518 |2.75 / 0.16 / 1.51 |stand-in |
|W4 |v2 |gpt-oss-20b |16 |8,855 / 4,126 / 12,981 |2,451 / 1,237 / 3,688 |3.61 / 3.34 / 3.52 |stand-in |
|W5 |v1 |Gemma 4 12B |181 |202,698 / 5,946 / 208,644 |116,967 / 153,818 / 270,785 |1.73 / 0.04 / 0.77 |measured |
|W5 |v1 |gpt-oss-20b |137 |141,341 / 101,216 / 242,557 |90,244 / 34,238 / 124,482 |1.57 / 2.96 / 1.95 |measured |
|W5 |v2 |Gemma 4 12B |181 |202,698 / 5,946 / 208,644 |116,967 / 153,818 / 270,785 |1.73 / 0.04 / 0.77 |measured |
|W5 |v2 |gpt-oss-20b |137 |141,341 / 101,216 / 242,557 |90,244 / 34,238 / 124,482 |1.57 / 2.96 / 1.95 |measured |
