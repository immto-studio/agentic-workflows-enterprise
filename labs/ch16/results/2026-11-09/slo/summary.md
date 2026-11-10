# Chapter 16, step 6: SLOs, the simulated month, the alerts and the policy

Written by `slo/run_slo.py --summarize` from the files beside it. The first section is MEASURED on the kept runs; every section after it is SIMULATED.

## The SLIs on the kept runs (measured)

|Workflow|Runs by end|Success|Target|Latency threshold|Latency|Target|Outcome|Target|
|---|---|---|---|---|---|---|---|---|
|W1|answer 64, refusal 11|75 / 75 (100%)|99.5%|30 s|74 / 75 (98.67%)|95%|none|none|
|W2|answer 106, refusal 23, budget stop 5, error 1|129 / 135 (95.56%)|99.5%|10 s|128 / 129 (99.22%)|95%|none|none|
|W3|answer 33, refusal 2, proposal 5, budget stop 8|40 / 48 (83.33%)|95%|120 s|40 / 40 (100%)|95%|2 / 2 (100%)|90%|
|W4|proposal 48|48 / 48 (100%)|99%|60 s|48 / 48 (100%)|95%|no events|90%|
|W5|proposal 33|33 / 33 (100%)|90%|21,600 s|33 / 33 (100%)|90%|11 / 11 (100%)|80%|

|Workflow|Kept run|Runs|Runs by end|Success|Latency|Outcome|
|---|---|---|---|---|---|---|
|W1|gemma4-12b 2026-11-03|25|answer 21, refusal 4|25 / 25 (100%)|25 / 25 (100%)|none|
|W1|gpt-oss-20b 2026-10-29|25|answer 20, refusal 5|25 / 25 (100%)|25 / 25 (100%)|none|
|W1|nova-lite 2026-10-29|25|answer 23, refusal 2|25 / 25 (100%)|24 / 25 (96%)|none|
|W2|gemma4-12b 2026-11-02|25|answer 20, refusal 5|25 / 25 (100%)|25 / 25 (100%)|none|
|W2|gpt-oss-20b 2026-11-02|25|answer 21, refusal 4|25 / 25 (100%)|25 / 25 (100%)|none|
|W2|gpt-oss-20b 2026-11-02 run1|20|answer 11, refusal 4, budget stop 5|15 / 20 (75%)|14 / 15 (93.33%)|none|
|W2|gpt-oss-20b 2026-11-02 run2|20|answer 16, refusal 3, error 1|19 / 20 (95%)|19 / 19 (100%)|none|
|W2|gpt-oss-20b 2026-11-02 run3|20|answer 17, refusal 3|20 / 20 (100%)|20 / 20 (100%)|none|
|W2|gpt-oss-20b traced/2026-11-03|25|answer 21, refusal 4|25 / 25 (100%)|25 / 25 (100%)|none|
|W3|gpt-oss-20b 2026-11-02|24|answer 17, refusal 1, proposal 2, budget stop 4|20 / 24 (83.33%)|20 / 20 (100%)|no events|
|W3|gpt-oss-20b traced/2026-11-03|24|answer 16, refusal 1, proposal 3, budget stop 4|20 / 24 (83.33%)|20 / 20 (100%)|2 / 2 (100%)|
|W4|gemma4-12b 2026-11-02|8|proposal 8|8 / 8 (100%)|8 / 8 (100%)|no events|
|W4|gpt-oss-20b 2026-11-02|8|proposal 8|8 / 8 (100%)|8 / 8 (100%)|no events|
|W4|gpt-oss-20b 2026-11-02/first-run-max-tokens-200|8|proposal 8|8 / 8 (100%)|8 / 8 (100%)|no events|
|W4|gpt-oss-20b 2026-11-02/run-before-logs-kept|8|proposal 8|8 / 8 (100%)|8 / 8 (100%)|no events|
|W4|gemma4-12b traced/2026-11-03|8|proposal 8|8 / 8 (100%)|8 / 8 (100%)|no events|
|W4|gpt-oss-20b traced/2026-11-03|8|proposal 8|8 / 8 (100%)|8 / 8 (100%)|no events|
|W5|gemma4-12b 2026-11-03|3|proposal 3|3 / 3 (100%)|3 / 3 (100%)|1 / 1 (100%)|
|W5|gemma4-12b 2026-11-03/after-review|3|proposal 3|3 / 3 (100%)|3 / 3 (100%)|1 / 1 (100%)|
|W5|gemma4-12b 2026-11-03/first-run-thinking-loop|3|proposal 3|3 / 3 (100%)|3 / 3 (100%)|1 / 1 (100%)|
|W5|gemma4-12b 2026-11-03/step-5b|3|proposal 3|3 / 3 (100%)|3 / 3 (100%)|1 / 1 (100%)|
|W5|gemma4-12b 2026-11-03/step-5c|3|proposal 3|3 / 3 (100%)|3 / 3 (100%)|1 / 1 (100%)|
|W5|gpt-oss-20b 2026-11-03|3|proposal 3|3 / 3 (100%)|3 / 3 (100%)|1 / 1 (100%)|
|W5|gpt-oss-20b 2026-11-03/after-review|3|proposal 3|3 / 3 (100%)|3 / 3 (100%)|1 / 1 (100%)|
|W5|gpt-oss-20b 2026-11-03/first-run-max-tokens-1200|3|proposal 3|3 / 3 (100%)|3 / 3 (100%)|1 / 1 (100%)|
|W5|gpt-oss-20b 2026-11-03/second-run-max-tokens-4096|3|proposal 3|3 / 3 (100%)|3 / 3 (100%)|1 / 1 (100%)|
|W5|gpt-oss-20b 2026-11-03/step-5b|3|proposal 3|3 / 3 (100%)|3 / 3 (100%)|1 / 1 (100%)|
|W5|gpt-oss-20b 2026-11-03/step-5c|3|proposal 3|3 / 3 (100%)|3 / 3 (100%)|1 / 1 (100%)|

## The SLOs and their budgets in the simulated month

|Workflow|SLI|Target|Threshold|Valid events expected in the month|Error budget (events)|
|---|---|---|---|---|---|
|W1|success|99.5%||5,918|29.6|
|W1|latency|95%|30 s|5,918|296|
|W1|outcome|none||||
|W2|success|99.5%||42,440|212|
|W2|latency|95%|10 s|41,969|2,098|
|W2|outcome|none||||
|W3|success|95%||296|14.8|
|W3|latency|95%|120 s|247|12.3|
|W3|outcome|90%||27.7|2.77|
|W4|success|99%||197|1.97|
|W4|latency|95%|60 s|197|9.86|
|W4|outcome|90%||197|19.7|
|W5|success|90%||33.9|3.4|
|W5|latency|90%|21,600 s|33.9|3.4|
|W5|outcome|80%||18|3.6|

## The simulated month

|Workflow|Runs|Runs by end|Success|Latency|Outcome|Bad events by cause|
|---|---|---|---|---|---|---|
|W1|5,955|answer 4,684, refusal 1,217, error 54|5,901 / 5,955 (99.09%)|5,898 / 5,901 (99.95%)|none|self-hosted-down 53, throttled-hour 1|
|W2|42,133|answer 29,323, refusal 7,378, budget stop 5,161, error 271|36,701 / 42,133 (87.11%)|35,595 / 36,701 (96.99%)|none|baseline 261, model-regression 5161, throttled-hour 10|
|W3|281|answer 196, refusal 9, proposal 31, budget stop 40, unavailable 5|236 / 281 (83.99%)|236 / 236 (100%)|25 / 30 (83.33%)|baseline 42, model-regression 3, self-hosted-down 5|
|W4|190|proposal 187, error 3|187 / 190 (98.42%)|187 / 187 (100%)|152 / 161 (94.41%)|baseline 9, w4-records-refused 3|
|W5|35|proposal 35|35 / 35 (100%)|35 / 35 (100%)|14 / 17 (82.35%)|baseline 2, model-regression 1|

|Injected event|When (ET)|Runs it changed|Bad events it caused|Gateway records|
|---|---|---|---|---|
|provider-outage|Mon 11 Jan 10:00 to Mon 11 Jan 10:45|W1 2, W2 55||w1 fallback 2, w1 probe fallback 1, w2 fallback 56, w3 probe fallback 1, w4 probe failed 1|
|throttled-hour|Wed 13 Jan 14:00 to Wed 13 Jan 15:00|W1 5, W2 44|W1 1, W2 10|w1 provider_429 5, w2 provider_429 44, w3 probe provider_429 1, w4 probe provider_429 1|
|model-regression|Wed 20 Jan 10:00 to Thu 04 Feb 00:00|W2 20403, W3 10, W5 15|W2 5161, W3 3, W5 1||
|self-hosted-down|Sat 30 Jan 00:00 to Mon 01 Feb 00:00|W1 53, W3 5|W1 53, W3 5|w1 failed 53, w3 failed 8|
|w4-records-refused|Thu 28 Jan 00:00 to Fri 29 Jan 00:00|W4 3|W4 3||

|Probe|Probes in the month by end|
|---|---|
|W1|answer 720|
|W3|answer 720|
|W4|answer 719, error 1|

|W5's scheduled nights|Nights|Output tokens a night, mean|Range|Seconds a night, mean|
|---|---|---|---|---|
|before|16|12,929|8,377 to 18,505|239|
|after|14|19,394|11,556 to 25,462|547|

## Which alert caught each injected event (simulated)

|Injected event|own-traffic|with-probe (proposed)|grouped|platform|
|---|---|---|---|---|
|provider-outage|none|page: W4 success fast-burn-1h, Mon 11 Jan 10:35|none|none|
|throttled-hour|page: W2 success fast-burn-1h, Wed 13 Jan 14:10|page: W2 success fast-burn-1h, Wed 13 Jan 14:10|page: W2 success fast-burn-1h, Wed 13 Jan 14:10|page: PLATFORM provider 429s provider-429-across-workflows, Wed 13 Jan 14:20|
|model-regression|page: W2 success fast-burn-1h, Wed 20 Jan 10:30|page: W2 success fast-burn-1h, Wed 20 Jan 10:30|page: W2 success fast-burn-1h, Wed 20 Jan 10:30|none|
|self-hosted-down|page: W1 success fast-burn-1h, Sat 30 Jan 00:45|page: W1 success fast-burn-1h, Sat 30 Jan 00:45|page: group:w1+w3+w4 success fast-burn-1h, Sat 30 Jan 04:50|none|
|w4-records-refused|page: W4 success fast-burn-1h, Thu 28 Jan 14:35|page: W4 success fast-burn-1h, Thu 28 Jan 14:35|none|none|

|Injected event|Workflow|SLI|Highest burn over 1 hour (page at 14.4)|Over 6 hours (page at 6)|Over 3 days (ticket at 1)|
|---|---|---|---|---|---|
|provider-outage|W1|success|0|0|0|
|provider-outage|W1|latency|0|0|0|
|provider-outage|W2|success|5.97|2.86|2.45|
|provider-outage|W2|latency|13.6|2.76|0.229|
|provider-outage|W3|success|0|4|1.03|
|provider-outage|W3|latency|0|0|0|
|provider-outage|W3|outcome|0|0|2|
|provider-outage|W4|success|100|12.5|1.06|
|provider-outage|W4|latency|0|0|0|
|provider-outage|W4|outcome|0|0|0|
|throttled-hour|W1|success|28.6|4.65|0.316|
|throttled-hour|W1|latency|12|1.62|0.107|
|throttled-hour|W2|success|31.2|9.94|2.78|
|throttled-hour|W2|latency|10|1.89|0.374|
|throttled-hour|W3|success|0|0|0.762|
|throttled-hour|W3|latency|0|0|0|
|throttled-hour|W3|outcome|0|0|1.11|
|throttled-hour|W4|success|0|0|1.07|
|throttled-hour|W4|latency|0|0|0|
|throttled-hour|W4|outcome|0|0|0|
|model-regression|W2|success|93.9|61.9|53.4|
|model-regression|W2|latency|4.44|2.31|1.49|
|model-regression|W3|success|15|6.67|2.22|
|model-regression|W3|latency|0|0|0|
|model-regression|W3|outcome|10|10|10|
|self-hosted-down|W1|success|125|57.1|16.4|
|self-hosted-down|W1|latency|0|0|0|
|self-hosted-down|W3|success|13.3|5.46|1.98|
|self-hosted-down|W3|latency|0|0|0|
|self-hosted-down|W3|outcome|0|0|0|
|w4-records-refused|W4|success|50|25|3.61|
|w4-records-refused|W4|latency|0|0|0|
|w4-records-refused|W4|outcome|0.732|0.732|0.732|

|Design|Alerts by action and cause|
|---|---|
|own-traffic|page baseline 52, page model-regression 2, page self-hosted-down 24, page throttled-hour 2, page w4-records-refused 4, ticket baseline 5, ticket model-regression 2, ticket self-hosted-down 1, ticket w4-records-refused 1|
|with-probe|page baseline 7, page model-regression 2, page provider-outage 2, page self-hosted-down 21, page throttled-hour 2, page w4-records-refused 4, ticket baseline 6, ticket model-regression 2, ticket provider-outage 1, ticket self-hosted-down 1, ticket w4-records-refused 1|
|grouped|page baseline 5, page model-regression 2, page self-hosted-down 1, page throttled-hour 1, ticket baseline 1, ticket model-regression 1, ticket self-hosted-down 1|
|platform|page throttled-hour 1|

|Design|Scope|Pages by cause|Tickets by cause|
|---|---|---|---|
|own-traffic|W1|self-hosted-down 21, throttled-hour 1|self-hosted-down 1|
|own-traffic|W2|baseline 5, model-regression 2, throttled-hour 1|baseline 1, model-regression 1|
|own-traffic|W3|baseline 47, self-hosted-down 3|baseline 4, model-regression 1|
|own-traffic|W4|w4-records-refused 4|w4-records-refused 1|
|with-probe|W1|self-hosted-down 21, throttled-hour 1|self-hosted-down 1|
|with-probe|W2|baseline 5, model-regression 2, throttled-hour 1|baseline 1, model-regression 1|
|with-probe|W3|baseline 2|baseline 5, model-regression 1|
|with-probe|W4|provider-outage 2, w4-records-refused 4|provider-outage 1, w4-records-refused 1|
|grouped|group:w1+w3+w4|self-hosted-down 1|self-hosted-down 1|
|grouped|W2|baseline 5, model-regression 2, throttled-hour 1|baseline 1, model-regression 1|
|platform|platform|throttled-hour 1|none|

## The error-budget policy over the simulated month

|Workflow|SLI|Budget (events)|Bad events in the month|Budget used|Spent at|Bad events when spent|
|---|---|---|---|---|---|---|
|W1|success|29.6|54|182.5%|Sat 30 Jan 21:56|throttled-hour 1, self-hosted-down 29|
|W1|latency|296|3|1.01%|||
|W2|success|212|5,432|2560%|Sun 17 Jan 04:24|baseline 203, throttled-hour 10|
|W2|latency|2,098|1,106|52.71%|||
|W3|success|14.8|45|304.2%|Fri 22 Jan 21:38|baseline 15|
|W3|latency|12.3|0|0%|||
|W3|outcome|2.77|5|180.2%|Wed 20 Jan 11:18|baseline 2, model-regression 1|
|W4|success|1.97|3|152.1%|Thu 28 Jan 18:00|w4-records-refused 2|
|W4|latency|9.86|0|0%|||
|W4|outcome|19.7|9|45.63%|||
|W5|success|3.4|0|0%|||
|W5|latency|3.4|0|0%|||
|W5|outcome|3.6|3|83.33%|||

|When (ET)|Workflow|Action|SLI|Decided by|Record|
|---|---|---|---|---|---|
|Sun 17 Jan 04:24|W2|freeze|success|the policy, agreed in advance||
|Wed 20 Jan 11:18|W3|freeze|outcome|the policy, agreed in advance||
|Wed 20 Jan 11:18|W3|rung down|outcome|the on-call lead (oncall.lead@larkspur.example)|EC-SIM-01: rung 3 to 2, dropped record_change, restart_deployment, scale_deployment; document by 2027-01-21T16:18:16.815+00:00|
|Fri 22 Jan 21:38|W3|budget spent|success|||
|Thu 28 Jan 18:00|W4|freeze|success|the policy, agreed in advance||
|Sat 30 Jan 21:56|W1|freeze|success|the policy, agreed in advance||

## The hourly probe and its cost over the simulated month

|Workflow|Case|Tokens a probe (in / out)|Probes|Served|Probe tokens in the month|The workflow's own tokens|Probe over own|USD in the month|
|---|---|---|---|---|---|---|---|---|
|W1|gq-14/oncall.engineer|404 / 44|720|720|322,560|18,918,523|1.7%|0.02673|
|W3|w3-02|981 / 43|720|720|737,280|3,069,407|24.02%|0.05313|
|W4|w4-01|200 / 253|720|719|325,707|76,710|424.6%|0.05577|

## fig-16-03 (simulated)

|Workflow|Injected events that changed its runs|Kinds of alert|Kinds of policy action|SLIs|Sum|Chosen|
|---|---|---|---|---|---|---|
|W1|3|3|1|2|9||
|W2|3|4|1|2|10||
|W3|2|4|3|3|12|yes|
|W4|1|3|1|3|8||
|W5|1|0|0|3|4||

## The dashboard's panels

|Row|Panel|Status|Source|
|---|---|---|---|
|workflow|the three SLIs against their targets|derived|slo/slis.py over the harness logs, the run state, the cost lines and the spans slos.yaml names|
|workflow|the error budget left|derived|slo/budget_policy.py (budgets, spent)|
|workflow|the burn rates|derived|slo/burn.py (Stream.burn)|
|workflow|the alerts|derived|slo/burn.py (evaluate); W5's failed and late nights; nothing pages anyone (O-D17)|
|workflow|the budget events|emitted|the harnesses' stop sentences and chapter 5's `refused` cost line; LiteLLM's soft_budget_crossed webhook and its 422 (step 4, budget/receiver.py); the policy's log|
|workflow|the 429s its owner sees|emitted|the gateway's `failed` cost lines for the provider's 429 (chapter 5's gateway_hooks), chapter 5's `refused` line for the request rate, LiteLLM's key limiter's refusals (step 5); each client's waits (step 5b)|
|workflow|the calls a fallback served|emitted|the gateway's cost line, `fallback`, `served_alias`, `region`; step 5b's `fallback_in_jurisdiction` line|
|workflow|the hourly probe|emitted|slo/probe.py's log, one line a probe with its trace id and its cost line|
|workflow|the controls|derived|slis.incidents over the runs; the gateway's region and refusal lines, the harness's refusals|
|platform|the provider's 429s across workflows|emitted|the gateway's `failed` cost lines whose error is the provider's rate limit|
|platform|the gateway itself|emitted|LiteLLM's readiness endpoint; step 5b's limiter_store_unreachable and limiter_store_reachable alerts|
|platform|the fallbacks and the self-hosted path|emitted|the gateway's cost lines; ledger/month.py's GPU allocation|
|platform|the models behind each alias|emitted|the gateway's cost line, `served_model` and `deployment`|
|platform|the probes and their cost|emitted|slo/probe.py's cost lines, priced by ledger/price.py|
|platform|Foundry hosted-agent sessions per subscription and region, against their quota|open|open: chapter 16's fact sheet names no metric or API that reports the count, and the lab runs no Foundry hosted agent. The panel's source is a fact for the chapter's fact check; the quota's two error codes are the only signal named so far, and they come only once the quota is spent.|
|platform|the month's spend against the budgets|emitted|the cost lines and ledger/month.py; LiteLLM's key spend in its database|
