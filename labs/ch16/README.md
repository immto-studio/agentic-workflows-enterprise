# Chapter 16: observability, cost, capacity and continuity

Chapter 16 puts numbers on running the five workflows and chapter 5's skeleton: what a run and a month
cost, who pays for what isn't a call, how a trace joins the stores and the bill, the budgets and the kill
switch, capacity and continuity, the SLOs, and the monthly review with Ingrid Holm. The plan's
numbered decisions, O-D1 to O-D18 as amended on 3 November 2026, are in [DECISIONS.md](DECISIONS.md); the
pages behind the fact sheet are under chapter 16 in [LINKS.md](../../LINKS.md), with the addendum of
3 November as its section 8 and the vendor re-read of 9 November as its section 9. `vendors.md` in this folder
holds the chapter's comparison of the three clouds, eight questions each.

The nine steps are done. Step 1 was the fact sheet's addendum, its section 8. Step 2 is the ledger in `ledger/`,
built from the runs the workflows already kept, with no model, no gateway process, no network, and no
cloud account: a dated price table, every kept model call as a cost line, cost per run and per month, the
token counts across models, the table in LiteLLM and against its built-in map, the allocation of what
isn't a call, and the drift of a month estimated from sampled traces (O-D5, O-D6, and the plan's
consistency notes). Step 3 is the Collector in `collector/`: the pinned OpenTelemetry Collector between
chapter 5's processes and the trace stores, run on this workstation with chapter 5's rule model, two fakes
for Langfuse and CloudWatch, and `join.py` over the local stores (O-D2, O-D3, O-D4). Step 3b ran W2, W3, W4
and W5 on the local models through the same Collector: the real trace for fig-16-01, the cost lines W3 and W4
never kept, which the ledger now prices in place of its proxies, a root span for W5's night, and the sampler
measured on that night under two settings. Step 4 is the budgets and switches in `budget/`: LiteLLM's database
on this workstation after a smoke test, a key per workflow with its monthly budget and the 80 percent alert,
the kill switch at the gateway timed both ways, the rung-down switch, and the identity half of the kill switch
as scripts for step 7 (O-D7). Step 5 is capacity and continuity in `capacity/`, against fakes on this workstation
with no model and no cloud call: a fake provider with a tokens-per-minute quota, W2 and W3 contending for it through
step 4's gateway under three kinds of limit, the cache LiteLLM's limiter counts in, retries, the gateway's own
latency, the outage drill, PostgreSQL stopped under the gateway, the repeated-write check with W3's own code, the
continuity table, and the calculator for committed capacity (O-D8, O-D9, O-D10). Step 5b makes the four fixes step 5's
drills called for and runs the drills again: the limiter's windows on a shared store, Microsoft's Garnet on this
workstation, with an alert when the store stops answering; a 429's Retry-After waited out within a cap by every
workflow's model client; W3 ending a run it can't wait for as model unavailable; and a fallback inside Canada for W3
(O-D8, O-D10). Step 6 is the SLOs in `slo/` and the playbook in `playbook/`, with no model and no network: three SLIs
for each workflow, measured on the kept runs, the lab's targets and error budgets, a simulated month built from the kept
runs with five events injected, the workbook's burn-rate alerts, W5's failed nights and an hourly probe run over it, the
error-budget policy applied to it with a rung down through step 4's switch in a dry run, the dashboard's panels and the
data for fig-16-03, and the misbehaving-agent playbook (O-D12, O-D13). Step 7 is the cloud session in `cloud/`: one
session in the lab account in us-east-2 on 9 November 2026, the budget first, Transaction Search and the Collector's export
to CloudWatch and to Langfuse on one VM, Bedrock's invocation log with the trace id in `requestMetadata`, the US profile's
serving Region, the tool role assumed with the trace id and joined through CloudTrail, the deny-all timed on real
credentials, Cost Explorer against the ledger, and everything destroyed and swept in the same session (O-D1, O-D2, O-D4,
O-D6, O-D7, O-D11). Step 8 is the model register and the upgrade path in `lifecycle/`: one register for the three
clouds and the local models, merged from chapters 6 to 9, with each model's stage, retirement date, replacement, and pin,
checked against every gateway configuration and Terraform file that names a model; the 90-day rule of chapters 7 and 8
as an alert, with O-D15's 180-day review window beside it; and the upgrade path run once for real on this workstation,
Gemma 4 12B as the candidate behind W2's alias on a staging gateway under chapter 15's gate, then a canary weight in the
gateway watched against O-D12's SLIs, the decision, and the remap with its change record (O-D14, O-D18's fig-16-04). Step 9
is the monthly review in `review/`: one generator writes the month's review for Ingrid Holm from the files the other steps
kept, the register, and W5's ledger, with no model and no network. Per workflow it gives the runs and the cost per run
against the budgets, the month against the monthly budget, the shared lines, the error budget left, the incidents, the budget
events and the switches pulled, the models within 180 days of retirement, and W5's savings with what finding them cost, every
figure marked measured, priced, estimated, simulated, or recorded, with its source (O-D15). Step 9 also puts chapter 15's
judge into the ledger: every judgment as a cost line under the workflow it judged, marked as the judge's, set against the
tokens of the output it read (ch15:305, ch15:156).

```
ledger/
  prices.yaml            the dated price table: every price with its source, the date, and the page it cites
  volumes.yaml           the month: each workflow's volume with its source, and the platform's quantities
  costlines.py           every model call in every kept run as one cost line, through chapter 15's registry
  price.py               a line priced at chapter 6's design; the guardrail's estimate; the custom prices in LiteLLM
  litellm.prices.yaml    the table as LiteLLM custom prices, one model_list per gateway pair (generated)
  litellm_map.py         the table against LiteLLM 1.106.6's built-in price map
  tokens.py              W1's golden set on three models: the token counts compared
  month.py               the month, and the allocation of the GPU hours and the fixed costs
  sampling.py            the month estimated from sampled traces, against the cost lines
  report.py              all of it, written to results/<date>/
  render.py              the summary's Markdown
  offline.py             refuses every connection that would leave the machine
  judge_lines.py         step 9: chapter 15's judge as cost lines under the workflow judged, marked as the judge's, and its
                         tokens against the tokens of the outputs it judged
collector/
  config.yaml            the Collector's configuration: the content drop, tail sampling, the file, CloudWatch, Langfuse
  fetch.py               the pinned contrib Collector v0.164.0, checked against its SHA-256, into bin/ (git-ignored)
  otelcol.py             starts and stops it with config.yaml and a run's overlay, with dummy credentials only
  fake_otlp.py           fake OTLP/HTTP receivers for Langfuse and CloudWatch; the span file read back; SigV4 checked
  policies.py            the sampling policies and the content list, written again in Python to check the Collector
  run_local.py           chapter 5's skeleton through its gateway and the Collector, in two phases
  analyze.py             the run's raw records to the results, and the results to the summary
  join.py                every record of one run by its trace id, and the run behind a CloudTrail event
  samples/               CloudTrail events in the shapes AWS documents, for join.py
  semconv-genai/         the GenAI span definitions at chapter 5's pinned commit, which say what is opt-in
  run_workflows.py       step 3b: W2, W3, W4 and W5 on the local models, every process exporting to the Collector
  analyze_workflows.py   step 3b's raw records to the results, and the results to the summary and fig-16-01
  one_trace.py           the follow-up's runs of w3-01 and w4-01, each one trace, kept beside step 3b's
budget/
  postgres.py            PostgreSQL 16.15 from EDB's zip, checked against its SHA-256, into pg/ (git-ignored); a cluster
  smoke.py               the Prisma smoke test: the proxy with its database on Windows, two calls, a key blocked
  litellm.config.yaml    step 4's gateway: chapter 5's aliases, the database, the webhook alert, Toronto's month
  keys.py                a virtual key per workflow from its manifest, and the admin calls the drills and the lead use
  key_binding.py         the callback that refuses tags that disagree with the key (ch05:164)
  ch05_callback.py       chapter 5's callback, imported unchanged so that this step's config can name it
  receiver.py            the webhook receiver that stands in for the owner's and FinOps's channels
  stops.py               the harness's side: a 422 counted as a budget stop and never retried
  oncall.py              the on-call lead's levers, each with its change record: the key blocked, the rung lowered
  rungs.py               the rung override, read before each run: it only lowers, and a bad file stops the run
  rung_harness.py        chapter 1's loop with the override read first
  identity.py            the identity half: a deny-all with aws:TokenIssueTime on the harness and tool roles, for step 7
  drills.py              the drills against the proxy and its database, written to results/<date>/budget/
  procs.py, record.py    the proxy's own console and its whole tree stopped; results with no path or key of this machine
capacity/
  fake_provider.py       a provider with a tokens-per-minute quota: reserved up front, settled after, 429 with Retry-After
  load.py                W2's and W3's calls, sized by the ledger's tokens per call, sent under a retry policy
  retry.py               the two policies: Retry-After honored with jitter and six attempts at most, and naive retries
  stack.py               a drill's processes on 127.0.0.1: the fake providers, PostgreSQL when needed, the proxy
  litellm.outage.yaml    chapter 5's aliases and callback, with allowed_fails 2 and cooldown_time 30
  litellm.deployment.yaml  step 4's gateway with tpm, rpm and max_parallel_requests on the deployment
  litellm.retry.yaml     LiteLLM's router alone: one deployment in one group, two in order in the other
  litellm.census.yaml    step 4's gateway with census_hooks.py after its callbacks
  litellm.census-no-alerts.yaml  the same without step 4's budget alerts
  ch05_hooks.py          chapter 5's callback, imported unchanged, so this folder's configs can name it
  binding_hooks.py       step 4's key-binding callback, loaded unchanged, for the same reason
  census_hooks.py        a callback that writes what the proxy holds in the cache its rate limiter counts in
  repeat_write.py        what stops a repeated run from writing again: W3's approval service, writer, store and harness
  run_drills.py          every drill, written to results/<date>/capacity/
  summary.py             the summary's Markdown
  units.yaml             committed capacity's units, minimums and burndowns, in the fact sheet's words
  busy_hour.yaml         W2's and W3's busy hours, stated, and chapter 9's measured speeds for the self-hosted path
  calculator.py          the provisioned calculator: utilization, the break-even, and the discount a commitment needs
  continuity.yaml        each platform component's failure mode, recovery objective and evidence
  garnet.py              step 5b: Garnet 2.2.5, checked against GitHub's SHA-256, into garnet/ (git-ignored); a store
  litellm.store.yaml     step 4's gateway with its limiter, spend counters and router state on the store
  litellm.store-deployment.yaml  litellm.deployment.yaml on the store
  litellm.store-census.yaml      litellm.census.yaml on the store; -no-alerts and -fail-closed vary it
  store_hooks.py         an alert through step 4's webhook when the limiter's store goes, and another when it's back
  litellm.outage-canada.yaml     litellm.outage.yaml plus a fallback in Canada where chapter 5's rules turn a chain off
  fallback_hooks.py      the callback that gives such a request the named fallback its class and Regions allow
  run_5b.py              step 5b's drills, written to results/<date>/capacity/
  summary_5b.py          step 5b's summary's Markdown
slo/
  slos.yaml              the SLIs and SLOs: what is valid, good and bad, each event's source, what the kept runs lack,
                         each target with its reason; the controls, which get no error budget
  slis.py                a run as one event of one shape, the three SLIs over events, and the kept runs' events
  month.yaml             SIMULATED: the month's seed, volumes, pools, assumed decisions, and the five injected events
  simulate.py            the simulated month, seeded, from the kept runs at the ledger's volumes, with the injections
  alerts.yaml            the burn-rate rules, W5's failed nights, the probe, the three designs, the platform's pages
  burn.py                the alerts over the month: burn rates, episodes, attribution, nights, the platform's 429s
  probe.py               the hourly probe: a golden case's first call through the gateway, its verdict, its cost lines
  policy.yaml            the error-budget policy: the freeze, the rung down, the incident, who decides, the records
  budget_policy.py       the policy applied to the month, the rung down through step 4's switch in a dry run
  dashboard.yaml         fig-16-03's panels, each with its source and whether the lab emits it
  run_slo.py             step 6's results and their summary, written to results/<date>/slo/
playbook/
  playbook.yaml          the misbehaving-agent playbook as a table: symptom, signal, levers, who, record
  runbook.md             the on-call lead's runbook, with the commands
cloud/
  terraform/             step 7's resources, tagged: the budget first (budget.tf), the network with no inbound rule from the
                         internet, the Instance Connect endpoint, the Langfuse VM, the tool role, invocation logging
  terraform/templates/   the VM's user data and Langfuse's environment
  langfuse/              Langfuse v4.74.0's Compose file, vendored at step 1 (its SHA-256 is in the tests), and the override
                         that pins its two floating images
  cloud_session.py       the account from the environment alone, the redaction every kept file goes through, the clock
  cloud_budget.py        the budget read back through the API at the start and at the end
  transaction_search.py  Transaction Search on, its status, and off, in a step of its own
  export_run.py          chapter 5's skeleton through the Collector to CloudWatch and Langfuse, with the tap and the sink;
                         cloudwatch_spans.py and langfuse_check.py poll the two stores and compare
  request_metadata_hooks.py  the gateway's requestMetadata callback (O-D2); ch05_bedrock_callback.py imports chapter 5's
  litellm.bedrock-ca.yaml, litellm.bedrock-us.yaml  the gateway's configs for the Bedrock calls: chapter 6's design, and
                         the In-Region deployment behind the alias for the two logged calls
  bedrock_calls.py       the four Nova Lite calls, the invocation log read back, CloudTrail's events with inferenceRegion
  tool_role.py           the tool role assumed with the trace id, the refused shapes, the deny-all timed, CloudTrail and
                         join.py both ways
  langfuse_vm.py, tunnel.py  the VM over the Instance Connect endpoint: the markers read back, the tunnel held for the run
  cost_explorer.py       Cost Explorer's Nova Lite days against the ledger's cost lines
  leftovers.py           the sweep of step 7's kinds after the destroy, beside chapter 6's
  cloud_summary.py       the summary's Markdown, and the spend estimate at the dated table's prices
lifecycle/
  register.yaml          the register: 13 models of the three clouds and the workstation, each with its stage, retirement
                         date, replacement, pin, and deployments, every fact with its source and date; the gateways it must
                         agree with, and the configurations it excludes as fakes
  register.py            the loader, the check against every LiteLLM configuration and the two Terraform files both ways,
                         and the local pins against the digests an Ollama reports
  alerts.yaml            the retirement alert's rules, in slo/alerts.yaml's form: the page, the 90-day ticket, the 180-day
                         review row, the Legacy notice, and what the providers promise as notice
  retirement.py          the alert computed from the register for a date: every model's state, and what fires
  litellm.current.yaml   W2's alias map before the upgrade, on the portable Ollama
  litellm.staging.yaml   the candidate behind larkspur-chat for chapter 15's live job
  litellm.canary.yaml    larkspur-chat with the current model at weight 3 and the candidate at weight 1
  canary.py              W2's golden set through the weighted alias, the arms from the cost lines, the SLIs three ways,
                         and the model swaps the one server made, watched on /api/ps
  decision.py            the rule: the gate first, then enough runs, then the candidate not below the control on each SLI
  remap.py               the alias remapped to the candidate or back, written whole, with the change record it leaves
  upgrade.py             the path run end to end, each stage a step that can run alone, written to results/<date>/lifecycle/
  upgrade_path.yaml      fig-16-04's stages and what gates each
  lifecycle_summary.py   the summary's Markdown
review/
  monthly_review.py      step 9: the month's review for Ingrid Holm from the kept files, the register, and W5's ledger,
                         every figure marked measured, priced, estimated, simulated, or recorded, with its source; the
                         page and its JSON, written together to results/<date>/review/
results/2026-11-03/      ledger-summary.md (every table), ledger.json (their data), costlines.jsonl (every line: the
                         workflows' 1,189, then the judge's 1,439)
results/2026-11-03/collector/   step 3: summary.md, collector.json, each phase's stores
results/2026-11-03/workflows/   step 3b: summary.md, workflows.json, fig-16-01-trace.json, each run's span file
results/2026-11-03/one-trace/   the follow-up: one W3 incident and one W4 change, each one trace (one_trace.py)
results/2026-11-03/budget/      step 4: smoke.json, drills.json, summary.md
results/2026-11-03/capacity/    step 5: drills.json, calculator.json, limiter-cache.json, summary.md, and every request
                                or call behind them (contention-requests.jsonl, limiter-cache-requests.jsonl,
                                outage-events.jsonl, database-events.jsonl)
results/2026-11-04/capacity/    step 5b: summary-5b.md, store-probe.json, store.json, outage.json, garnet-fetch.json,
                                and every request or event behind them (store-contention-requests.jsonl,
                                store-cache-requests.jsonl, store-stopped-requests.jsonl, outage-events.jsonl)
results/2026-11-09/slo/         step 6: kept.json (MEASURED), and SIMULATED month.json, alerts.json, policy.json,
                                policy-actions.jsonl, probe.json, probe-costlines.jsonl, fig-16-03.json; summary.md
results/2026-11-09/cloud/       step 7: summary.md, one JSON per check (budget, transaction-search, export-run, langfuse-vm,
                                bedrock, tool-role, cost-explorer, teardown, leftovers), the live run's stores (export-run/),
                                cloudtrail-events.json, join.txt, and the first apply's errors
results/2026-11-09/lifecycle/   step 8: summary.md, register-check.json, retirement.json, gate.json and gate.md with the live
                                job's result (live-w2-gemma4-12b.json), canary.json with every call and run behind it
                                (canary-calls.jsonl, canary-runs.jsonl), decision.json, remap.json with changes.jsonl and the
                                configuration the remap wrote, and fig-16-04.json
results/2026-11-09/review/      step 9: review-2026-11.md, the month's review, the page whose shape the chapter prints, and
                                review-2026-11.json, every figure with its basis and its source
tests/                   593 tests, none of which needs a model, a gateway, a network beyond 127.0.0.1, or a
                         cloud account; the 24 that run the Collector skip without its binary, the one that
                         runs PostgreSQL without budget/pg/, the two that run Garnet without capacity/garnet/,
                         and the one that runs terraform validate without an initialized cloud/terraform/
.gitattributes           LF for the results, the generated prices, and the vendored Compose file in every checkout
.gitignore               the Collector's binary, PostgreSQL's and Garnet's zips and binaries, the runs' raw records, and
                         the live probe's log
```

Every table is in `results/2026-11-03/ledger-summary.md`, the price table included, and the main ones are
below. The prices appear there, in `ledger/prices.yaml` and in `ledger.json`, the companion's dated
record. The book prints none of them (style guide 12.4); it may print the ratios and the shares of
the manifests' budgets, which section 12 of the summary lists. The judge's token ratios, in section 14, are token
figures and not prices.

## The price table

`ledger/prices.yaml` holds 49 entries, each with its source, the date that source records, and the page it
cites. An entry copied from a cost sheet of chapters 6 to 9 names its place in the sheet, and a test reads
the sheet and compares. Prices no cost sheet has come from section 8.8 of the fact sheet and carry its
quote: CloudWatch's spans, RDS for PostgreSQL, ElastiCache, the EC2 VM, Cost Explorer's API, and committed
capacity on the three clouds. Each of the 42 quotes, with its page, appears word for word in the fact
sheet as of 3 November. A price no vendor publishes, or no source has, is null with the vendor's words or the
reason: LiteLLM's enterprise license ("Pricing depends on your deployment size. Get in touch to scope
it."), Langfuse's enterprise features ("Custom Pricing"), Gemini's tokens in Montréal, the g6e.2xlarge
chapter 9 names for a replica, and the private endpoints of chapters 7 and 8.

Chapter 6's design (`design` in the table) names the deployment that serves each alias:
`larkspur-chat` is Nova Lite through the Canadian profile, called in ca-central-1; `larkspur-chat-fallback`
is Nova Lite In-Region in us-east-2; `larkspur-chat-restricted` is chapter 9's gpt-oss-20b at zero per
token; `larkspur-embed` is Titan Text Embeddings V2. A fallback is priced at the deployment it fell back
to, in that deployment's own Region. The ledger's price reproduces the cost the gateway itself recorded on
all 48 Nova Lite calls of W1's Bedrock run (`tests/test_price.py`).

## The cost lines

`ledger/costlines.py` imports chapter 15's registry (`labs/ch15/layers/registry.py`), which finds every
kept run and reads it, and reads the four runs step 3b made through the Collector from each workflow's
`eval/traced/2026-11-03/` (step 3b, below). Each of the 314 outputs of chapter 15's 26 kept runs, and each of
the 65 cases of step 3b's four, is one run of a workflow, the unit a trace id names, and each of its model
calls is one line of one shape: run id (the trace id where the run kept one), workflow and the workflow tag
the gateway saw, the kept run and the case, the call's place in the run, the model as recorded, the alias
asked for and the one that served, the data class, input and output tokens, the call's time where kept, and
whether a fallback served it. Tool calls are counted per run beside them.

|Workflow |Kept runs |Of them, step 3b's |Runs |Model calls |With tokens |With time |Runs with a trace id |Fallbacks |Tool calls, as kept |
|---|---|---|---|---|---|---|---|---|---|
|skeleton |2 |0 |40 |77 |77 |77 |0 |0 |every tool call, with its arguments |
|W1 |3 |0 |75 |163 |163 |163 |0 |0 |the searches the model calls imply |
|W2 |6 |1 |135 |281 |281 |281 |25 |0 |every read, with whether it returned data |
|W3 |2 |1 |48 |279 |142 |142 |24 |0 |the reads that returned data |
|W4 |6 |2 |48 |48 |16 |16 |48 |0 |not kept |
|W5 |11 |0 |33 |341 |341 |341 |33 |0 |every read in the night's log |
|all |30 |4 |379 |1189 |1020 |1020 |130 |0 | |

Chapter 15's kept runs of W3 and W4 hold no tokens: their gateways wrote the lines to the labs' scratch
folders (`eval/_lab/`, ignored by git), and only W5 committed its gateway's lines beside its results. Step 3b
ran W3's 24 incidents and W4's 8 changes again through the Collector and committed the gateway's lines beside
each run, as W5 does, so 142 of W3's 279 lines and 16 of W4's 48 carry tokens and a time, all of them step
3b's. Those lines are the gateway's own, joined to each case by its trace id, and the month prices W3 and W4
from them (what step 3b's measured tokens changed, below). W4's tool calls aren't kept: its analyst reads its
sources in its own process. No kept call was served by a fallback, so the fallback price is tested on a line
made for it.

`costlines.jsonl` holds more than this table counts. The 1,189 lines above come first, and after them the 1,439 of
chapter 15's judge (step 9, below), one a judgment, each with three fields the workflows' lines don't have: `judge` (the
run, v1, v2 or v3), `judged` (the kept run whose output the judge read) and `judge_slice`. A judge line's `workflow` is
the workflow it judged, so a sum of the file by `workflow` adds the judge's tokens to the workflow's own, and only the
`judge` field tells the two apart. `costlines.collect()` leaves the judge's lines out, and so do cost per run, the
month, and the allocation.

## Cost per run

The table counts every kept run of each model, the early ones included, and each cell gives the median
and the 95th percentile (nearest rank). Calls count every run, and tokens and cost the runs that kept them,
which for W3 and W4 are step 3b's alone. The share is of the manifest's `per_run_usd`. The recounted column
multiplies each call's tokens by the next section's ratios, the way Nova Lite would have counted them, and
the guardrail column is an estimate the cost lines don't carry (see the guardrail, below).

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

No median run costs more than 0.29 percent of its per-run budget. The highest 95th percentile, 2.8
percent, is W5's on Gemma 4 12B, whose first kept run looped in its reasoning for about 7,400 output tokens
a call. The skeleton's calls, and W1's six Restricted calls in each kept run, went to the self-hosted alias
at zero per token. Step 3b's runs put W3's median incident at 0.044 percent of its per-run budget and W4's
median change at 0.0061 percent on gpt-oss-20b.

## W2 against chapter 3

Chapter 3 says "the operations assistant's median at Larkspur is two model calls and one tool call"
(ch03:58). Over W2's 135 kept runs, step 3b's run of the golden set among them, the median is two model calls
and one read; over the 108 answers alone it is two and one, and so is each of the six kept runs, so the claim
holds. Of the 135 runs, 77 made two model calls and 94 made one read; the 95th percentile on gpt-oss-20b,
five calls and four reads, comes from its first kept run, where seven of 20 runs made five calls. Chapter 11's
prompt sizes hold as well (ch11:361): the medians of the first two prompts are 841 and 1,008 tokens on
gpt-oss-20b, and 991.5 and 1,181 on Gemma 4 12B, against "about 850" and "1,000", and "about 1,000 and 1,200".

## Token counts across models

W1's golden set ran on gpt-oss-20b, Gemma 4 12B and Nova Lite (book D-033, companion #55 and #100).
`ledger/tokens.py` compares the 17 cases all three answered with the same number of calls, leaving out the
three whose calls went to the restricted alias (gpt-oss-20b served them even in the Nova Lite run) and the
five gpt-oss-20b ended at the step budget.

|Ratio |Input, totals (median per case) |Output, totals (median per case) |First call's input |
|---|---|---|---|
|nova-lite over gpt-oss-20b |1.36 (1.37) |0.54 (0.57) |1.71 |
|nova-lite over gemma4-12b |1.34 (1.32) |0.53 (0.59) |1.97 |
|gemma4-12b over gpt-oss-20b |1.02 (1.03) |1.02 (0.93) |0.87 |

The first call's prompt is the same text on every model, so its ratio is the tokenizer and the chat
template alone. Output runs the other way because gpt-oss-20b's completion tokens include its reasoning.
A cost priced from gpt-oss-20b's counts carries 1.36 on input and 0.54 on output to approach Nova Lite's
count, and one from Gemma 4 12B's, 1.34 and 0.53; both pairs come from one workflow's 17 cases.

## The table in LiteLLM, and LiteLLM's own map

`ledger/price.py --write-litellm` turns the table into `ledger/litellm.prices.yaml`: every priced
deployment with `input_cost_per_token` and `output_cost_per_token`, one `model_list` per gateway pair.
Loaded into LiteLLM 1.106.6's Router in a fresh process, with `LITELLM_LOCAL_MODEL_COST_MAP=True` and the
network blocked, each alias answered one mocked call of known usage:

|Gateway |Alias |Deployment |Tokens in / out |Expected |response_cost |completion_cost by id |Budget checks skipped |
|---|---|---|---|---|---|---|---|
|aws |`larkspur-chat` |`nova-lite-ca` |1,000 / 100 |0.00008960 |0.00008960 |0.00008960 |no |
|aws |`larkspur-chat-fallback` |`nova-lite-us` |1,000 / 100 |0.00008400 |0.00008400 |0.00008400 |no |
|aws |`larkspur-chat-restricted` |`vllm-gpt-oss-20b` |1,000 / 100 |0 |0 |0 |yes |
|aws |`larkspur-embed` |`titan-embed-v2-ca` |10 / 0 |0.000001000 |0.000001000 |embedding |no |
|azure |`larkspur-chat` |`gpt-4o-canada-east` |1,000 / 100 |0.004235 |0.004235 |0.004235 |no |

The custom price takes effect everywhere, the Canadian profile included. Priced by its model name alone in
the same process, the Canadian deployment comes to zero, with no error, because registering it leaves an
empty map entry under that name; the ledger prices by deployment, as the gateway's cost line does. The
self-hosted alias, priced at exactly zero, skips every budget check by LiteLLM's own predicate
(`is_model_cost_zero`), and chapter 5's callback sums the same zero, so the only stops on that alias are
each listing manifest's request rate (W1 and W2 at 120 a minute, W3 at 60) and each harness's step
budget (ch09:198).

`ledger/litellm_map.py` sets the table against LiteLLM's built-in map, read from the wheel itself, Nova
Lite's names first:

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

It reproduces section 8.1's probe: no entry for the Canadian profile (`ModelNotMappedError`), and a name
with a Region prefix priced at the base model's entry. Without the custom price a call to `larkspur-chat`
has no cost at all. The map keys one price to a name while Bedrock bills a profile at the price of the
Region it is called in (ch06:162), so the Canadian price, 6.7 percent above us-east-2's, is one the map
can't hold. Titan V2 in ca-central-1 costs five times the map's price, the regional gpt-4o in Canada East
1.21 times the map's Global price, and gpt-oss-20b on vLLM needs its explicit zero.

## The guardrail

Chapter 6 runs a Bedrock guardrail, a content policy and a sensitive-information policy, before and after
every call on the managed aliases, and it bills text units of up to 1,000 characters per policy. The
gateway's cost line doesn't carry it. `price.guardrail_estimate` prices it from each call's tokens at
LiteLLM's four characters a token: at Nova Lite's price it comes to 6 to 32 times the tokens it screens, the
most on W4's one-sentence calls on Gemma 4 12B,
and over a month to 63 percent of W2's `per_month_usd` against 4.5 percent for its tokens. It is an
estimate, since prompt tokens include tool definitions the guardrail doesn't read, and at that size the
guardrail needs a line of its own in the ledger, from ApplyGuardrail's usage or the bill's guardrail usage
types.

## A month

`ledger/volumes.yaml` gives each workflow's month, with a source for every number: a line of the book, or
"lab assumption, not in the book" with its basis. Chapters 1 to 14 were searched first; they give W2's
tokens (ch09:405), W4's changes (ch13:9) and W5's nights (ch14:29), and no volume for W1, W3 or W5's
alarms. A month is 730 hours, as in the cost sheets, and the per-run figures are gpt-oss-20b's.

|Workflow |Runs a month |Calls a month |Tokens a month |Direct cost (USD) |Share of per_month_usd |Range over kept runs |Recounted as Nova Lite |Guardrail estimate |Basis |
|---|---|---|---|---|---|---|---|---|---|
|W1 |6,000 |13,200 |19,181,280 |1.44 |1.4% |1.4% |1.6% |21% |measured |
|W2 |43,030 |89,580 |100,000,000 |9.01 |4.5% |4.3% to 4.9% |4.7% |63% |measured |
|W3 |300 |1,775 |3,112,038 |0.213 |0.043% |0.043% |0.051% |0.66% |measured on the 24 of 48 runs with tokens |
|W4 |200 |200 |77,775 |0.0125 |0.0063% |0.0063% |0.0044% |0.056% |measured on the 8 of 32 runs with tokens |
|W5 |34 |351 |604,660 |0.112 |0.11% |0.068% to 0.16% |0.072% |0.70% |measured |

Direct costs are a small share of every monthly budget; W2's, the largest, is 4.5 percent. Chapter 12's
"hundred questions an hour" (ch12:18) would be 73,000 questions a month against the 43,030 that chapter 9's
100 million tokens buy at W2's measured tokens per run, the same order. W3's and W4's rows are priced at
step 3b's measured tokens, which replace step 2's proxies (below).

## Allocating what isn't a call

The restricted alias's tenants are one of the plan's consistency notes. The manifests list it for W1, W2
and W3. In the kept runs W1 sent it 18 calls and W3 20, 11 in chapter 15's run and 9 in step 3b's, and W2
none: its class is Internal at most, and all 281 of its calls went to `larkspur-chat`. Chapter 9 says two workflows share the replicas, the incident
workflow and the operations assistant (ch09:18, ch09:200); chapter 10 sends W1's Restricted calls there from
month six (ch10:72). The table splits the GPUs (two replicas at the smallest g6e size's price, every hour of
the month) by tokens, with the idle remainder on the platform team's line (O-D6), on the reading of the
manifests and chapter 10:

|Tenant |Tokens a month |Token share |GPU share (USD) |Share of per_month_usd |Without an idle line (USD) |Without an idle line, share |
|---|---|---|---|---|---|---|
|W1 |1,933,440 |87.2% |0.795 |0.80% |2,368.99 |2,370% |
|W2 |0 |0% |0 |0% |0 |0% |
|W3 |284,075 |12.8% |0.117 |0.023% |348.07 |69.6% |
|idle, the platform team | | |2,716.15 | | | |

The tenants use 0.034 percent of the GPUs' hours, so the idle line carries almost all of them; without it,
the split by tokens would put 2,370 percent of W1's monthly budget on W1. Read as chapter 9 reads it, W3
alone would carry 543 percent of its own. W1's share is large because its golden set puts three of 25
cases on Restricted pages; production's isn't measured. Recommendation for the chapter (this step doesn't
edit the book): state three tenants, the workflows whose manifests list the alias, and split the hours by
each month's measured tokens, so W2 pays nothing until it sends anything. Chapter 9's "two workflows"
(ch09:18, ch09:200) then needs correcting, a note for book #26.

The platform's fixed costs (the gateway's database, Redis and compute, Langfuse's stores, chapter 6's
endpoints and keys) come to 466.54 US dollars a month at the table's prices, 269.28 of them at us-east-2's
EC2 prices standing in for ca-central-1's. Four lines stay parameters with no price: chapter 7's and
chapter 8's private endpoints and the two licenses. Split by tokens, the rule O-D6 took when it was amended on 3
November 2026 (chapter 2's rule, ch02:144), and by gateway calls, O-D6's first rule, for comparison:

|Workflow |Share of calls |By calls (USD) |Of per_month_usd |Share of tokens |By tokens (USD) |Of per_month_usd |Direct (USD) |GPU share (USD) |
|---|---|---|---|---|---|---|---|---|
|W1 |12.6% |58.59 |58.6% |15.6% |72.77 |72.8% |1.44 |0.795 |
|W2 |85.2% |397.62 |199% |81.3% |379.38 |190% |9.01 |0 |
|W3 |1.69% |7.88 |1.58% |2.53% |11.81 |2.36% |0.213 |0.117 |
|W4 |0.190% |0.888 |0.444% |0.0632% |0.295 |0.148% |0.0125 |0 |
|W5 |0.334% |1.56 |1.56% |0.492% |2.29 |2.29% |0.112 |0 |

By tokens, W2 carries 81 percent, 190 percent of its monthly budget and about 42 times its direct cost (by calls,
85 percent, 199 percent, and about 44 times), so the shared lines stay apart from the direct costs its owner
controls. Calls would be the better driver for lines that grow with requests, but O-D6 was amended on 3 November 2026
to split them by tokens, as ch02:144 says, and chapter 18 prints the token split.

## Sampling

`ledger/sampling.py` draws a month of runs from each workflow's kept runs with a fixed seed, prices each by
its cost lines, and estimates the month from traces kept at 1, 10 and 50 percent by head sampling, over
1,000 seeds:

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

Head sampling is unbiased, and its spread grows as the month shrinks: at 1 percent, W2's 43,030 runs give
a month within about 9 percent nine times in ten, and W5's 34 nights keep no trace at all in 707 of
1,000 seeds. Tail sampling keeps every failed and over-budget run and a share of the rest; a failed run is
one whose output failed its golden check, standing in for the error status a sampler reads.

|Workflow |Failed |Share of the rest kept |Traces kept |Naive mean error |Weighted mean error (5th to 95th) |
|---|---|---|---|---|---|
|W1 |14.3% |1% |15.2% |-1.80% |-0.36% (-21% to 22%) |
|W1 |14.3% |10% |22.9% |-1.09% |-0.083% (-6.7% to 6.0%) |
|W2 |21.6% |1% |22.3% |48.2% |-0.024% (-6.7% to 6.2%) |
|W2 |21.6% |10% |29.4% |33.3% |0.052% (-2.0% to 2.0%) |
|W5 |64.7% |1% |65.1% |44.9% |-0.49% (-5.8% to 7.5%) |
|W5 |64.7% |10% |68.2% |39.2% |0.044% (-5.8% to 15%) |

Scaled naively by the share of runs kept, the tail-sampled month overstates W2's cost by 48 percent at one
in a hundred of the rest and 33 percent at one in ten, because W2's failed runs cost 1.7 times the rest.
Weighted by the share each kept run stands for, the estimate is unbiased, and a trace store can weight it
only if each trace records the share it was kept at.

## What step 3b's measured tokens changed

Step 2 priced W3's and W4's calls by proxy, at W2's and W5's mean tokens per call on gpt-oss-20b
(`ledger/volumes.yaml`, `tokens_proxy`). Step 3b's runs kept the gateway's lines, and the month now prices
both at their own. The report computes step 2's figures again from chapter 15's kept runs alone, which gives
step 2's month back (`tests/test_month.py`), and sets them beside step 3b's:

|Workflow |Figures |Basis |Runs |Calls a run |Restricted calls a run |Input tokens a call |Output tokens a call |Cost per run (USD) |
|---|---|---|---|---|---|---|---|---|
|W3 |step 2's proxy |proxy: W2's tokens per call |24 |5.71 |0.46 |963 |157 |0.000535 |
|W3 |step 3b, measured |measured on the 24 of 48 runs with tokens |24 |5.92 |0.38 |1,640 |114 |0.000708 |
|W4 |step 2's proxy |proxy: W5's tokens per call |24 |1.00 |0 |640 |1,081 |0.000318 |
|W4 |step 3b, measured |measured on the 8 of 32 runs with tokens |8 |1.00 |0 |193 |196 |0.0000626 |

W3's calls carried 1.70 times the proxy's input tokens and 0.72 times its output: an incident's prompt carries
the triage's reads so far, six at the median by its end, where a W2 question carries one. W4's one call
carried 0.30 times the proxy's input and 0.18 times its output: it writes one sentence of rationale from a
short record, where the proxy was the pull request body a W5 call writes from a finding. Each pair below is
step 2's figure, then step 3b's; the GPU column takes the tenants as the manifests and chapter 10 have them:

|Workflow |Tokens a month |Direct share of per_month_usd |Share of calls |Share of tokens |Fixed costs by calls (USD) |Fixed costs by tokens (USD) |GPU share (USD) |
|---|---|---|---|---|---|---|---|
|W1 |19,181,280 / 19,181,280 |1.4% / 1.4% |12.6% / 12.6% |15.7% / 15.6% |58.79 / 58.59 |73.32 / 72.77 |0.794 / 0.795 |
|W2 |100,000,000 / 100,000,000 |4.5% / 4.5% |85.2% / 85.2% |81.9% / 81.3% |397.66 / 397.62 |382.26 / 379.38 |0 / 0 |
|W3 |1,918,095 / 3,112,038 |0.032% / 0.043% |1.63% / 1.69% |1.57% / 2.53% |7.63 / 7.88 |7.33 / 11.81 |0.0632 / 0.117 |
|W4 |344,209 / 77,775 |0.032% / 0.0063% |0.191% / 0.190% |0.282% / 0.0632% |0.891 / 0.888 |1.32 / 0.295 |none / none |
|W5 |604,660 / 604,660 |0.11% / 0.11% |0.335% / 0.334% |0.495% / 0.492% |1.56 / 1.56 |2.31 / 2.29 |none / none |

W3's month went from 0.032 to 0.043 percent of its `per_month_usd` and W4's from 0.032 to 0.0063 percent, both
still far inside their budgets. Split by tokens, W3's share of the platform's fixed costs went from 1.57 to
2.53 percent and W4's from 0.282 to 0.0632 percent. Split by calls, which step 2 counted from the kept runs,
W3's went from 1.63 to 1.69 percent: step 3b's run made 5.92 calls an incident where the kept run made 5.71.
W2's shares move a little because its golden set ran once more for fig-16-01, and W1's and W5's only with the
others'.

## The judge's tokens in the ledger (step 9)

Chapter 15 says the ledger "carries the judge's tokens under the workflow that was judged" (ch15:305) and that a
judge that thinks before it answers writes more tokens than the answer it judges (ch15:156). Step 9 makes the first
true and measures the second. `ledger/judge_lines.py` reads chapter 15's judge logs where chapter 15 keeps them
(`labs/ch15/results/2026-11-03/judge-gateway-<judge>.jsonl`, with the first two runs in `judge-v1/` and `judge-v2/`
beside the current files, read through `run_judge.runs` and `run_judge.origins`, chapter 15's own account of its
folder) and joins each judgment to its result file by trace id. The judge's calls went through chapter 5's gateway
with the judged workflow's tag and the case's class, so each is one cost line under the workflow judged: the judge's
model as the line's model, the alias and class the call carried, the tokens and latency the gateway recorded, and
three fields the workflows' own lines never carry, `judge` (the run), `judged` (the kept run whose output it read),
and `judge_slice`. The current log holds the second run's W4 and W5 judgments as well as the third run's W1 to W3,
and those 361 lines are counted once, under the run that made them. `costlines.collect()` leaves the judge's runs
out, so nothing above moved: cost per run, the month, and the allocation are the workflows' own. `report.py` prices
the judge's lines like any other, writes them after the workflows' 1,189 lines in `costlines.jsonl`, and the summary's
section 14 sets them against what they judged. `python ledger/judge_lines.py` prints the same sums and the conclusion
below from the logs alone.

|Run |Judge |Judgments |Prompt tokens |Completion tokens |Total |Completion a judgment, median |Seconds |USD at the table |
|---|---|---|---|---|---|---|---|---|
|v1 |Gemma 4 12B |360 |321,810 |10,799 |332,609 |30 |188.0 |0.0234 |
|v1 |gpt-oss-20b |240 |210,383 |139,746 |350,129 |563 |904.4 |0.0492 |
|v2 |Gemma 4 12B |360 |322,176 |10,828 |333,004 |30 |189.5 |0.0202 |
|v2 |gpt-oss-20b |240 |210,805 |138,566 |349,371 |563 |882.6 |0.0406 |
|v3 |Gemma 4 12B |152 |105,984 |4,078 |110,062 |28 |67.20 |0.00464 |
|v3 |gpt-oss-20b |87 |60,769 |34,221 |94,990 |337 |225.3 |0.00404 |

The 1,439 judgments carry 1,231,927 prompt and 338,238 completion tokens, chapter 15's own totals for its three runs.
Each is then set beside the tokens of the output it read: the kept run's own cost lines for the case, every model call
of the run for W1 to W4 and, for W5, the one call that wrote the pull request body, paired to the night's pull
requests in the order it wrote them; a padded copy counts the original's tokens. W3's and W4's judged outputs come
from chapter 15's kept runs, which kept no tokens (their gateway logs stayed in the scratch folders), so step 3b's run
of the same case on the same model stands in for them, the basis column says so, and no ratio mixes the two. For six W4
judgments the stand-in is further from the output than a rerun is: W4's first gpt-oss-20b run, kept as
`first-run-max-tokens-200`, spent its budget of 200 tokens on reasoning and returned the stub's sentence for five of its
eight rationales (W4's README), and those six judgments read its output.

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

Chapter 15's sentence is about the tokens a judge writes, and for completion tokens it holds as written. The result
files record gpt-oss-20b thinking at the model's default and Gemma 4 12B thinking off. In total, gpt-oss-20b wrote more
completion tokens than the outputs it read in every workflow it judged: 1.38 times the output's in W1, 1.83 in W2, 3.60
in W4 (on the stand-in) and 2.96 in W5. W3 had no such judge, since its kept run is gpt-oss-20b's and chapter 15 has the
other model judge it. Judgment by judgment the count is lower: 117 of 171 W1 judgments, 84 of 90 W2 judgments, 27 of 32
W4 judgments, and 254 of 274 W5 judgments wrote more completion tokens than the output, so the ratios compare totals and
a single judgment can come out the other way. Gemma 4 12B wrote fewer completion tokens than the outputs it read in
every workflow it judged (0.04 to 0.16 times), and more than the output in 6 of its 54 W4 judgments.

In all tokens, which count a prompt token like a completion token, the finding is separate. gpt-oss-20b's total is above
the output's for W4 (3.61, on the stand-in) and W5 (1.95), where the output is one short call, a W4 rationale or a W5
body. For W1 and W2 it is about a third of the run's tokens (0.33, 0.37), since a question's run carries two or three
calls of tool definitions and context in its prompts and the judge reads one output. Gemma 4 12B's total is above the
output's for W4 alone (1.51, on the stand-in). These are token figures and not prices.

The medians in chapter 15 and in the ledger are two populations. The ledger counts the three runs' judgments: 551
completion tokens a judgment at the median for gpt-oss-20b over 567 judgments, and 29 for Gemma 4 12B over 872. Chapter
15's README and ch15:156 give 559 and 29, the medians over the current files' calls alone, 240 for gpt-oss-20b and 360
for Gemma 4 12B. The summary gives both, each with its count.

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

The summary also gives the judge's tokens by slice (cross, self, padded) and by workflow, run, and judge. Priced at
chapter 6's design, the three runs' 1,439 calls come to 0.142 US dollars; W1's cases are Restricted and went to the
restricted alias at zero from the second run on, so the price says less than the tokens do.

## The Collector (step 3)

Step 3 runs O-D3's OpenTelemetry Collector on this workstation, between chapter 5's processes and three
trace stores. Chapter 5's skeleton answers its golden set through the gateway with its rule model, so no GPU
and no language model are involved, and every process sends its spans to the Collector over OTLP. Two fakes
take the place of Langfuse and CloudWatch in this step, which calls no cloud, and step 7 later reached the real ones.
`collector/join.py` reads the stores back by trace id.

### The binary

`collector/fetch.py` downloads `otelcol-contrib_0.164.0_windows_amd64.tar.gz` (105,170,298 bytes) from the
v0.164.0 release, checks it against the SHA-256 the release publishes for it,
`1fb8163f9036126a1bdc59eab2d7aef4e6cda36f6c1e618f2359663cae8b0f4a` (fact sheet 8.4), and unpacks the one
binary into `collector/bin/`, which git ignores. A tarball that doesn't match is deleted before anything is
unpacked. The tarball stays beside the binary, and every start, the run's and each test's, checks both again
in about two seconds: the tarball against the pinned digest, and the binary against the copy inside the
tarball. A binary replaced after unpacking stops the run before the Collector starts. The distribution
builds its core components at v0.164.0 and its contrib ones at v0.164.1, and the settings below follow those
versions' documentation.

### The pipeline

```
harness, gateway, MCP server  --OTLP/HTTP-->  otlp receiver on 127.0.0.1:4318
traces/sample     transform/drop-content -> tail_sampling -> batch -> forward/sampled
traces/stores     forward/sampled -> file, otlp_http/cloudwatch (sigv4auth: xray, us-east-2)
traces/langfuse   forward/sampled -> transform/langfuse-cost -> otlp_http/langfuse (basicauth, ingestion v4)
```

The sampler decides once, and the `forward` connector hands each kept trace to both output pipelines. The
logs and the gateway's cost lines never pass through the Collector, so nothing samples them (ch03:58).

### The content drop

`transform/drop-content` deletes 15 attributes from every span and every span event:
`gen_ai.tool.call.arguments` and `gen_ai.tool.call.result`, the input and output messages, the system
instructions and the tool definitions, each with its `_ref` variant, the retrieval documents and query, the
memory query and records, and every `gen_ai.prompt.variable.<key>`. They are the attributes the GenAI span
definitions mark opt-in at the commit chapter 5 pinned. Chapter 5's copy of the registry carries no
requirement levels, so `collector/semconv-genai/` pins the GenAI and MCP span definitions at the same
commit, and a test derives the list from them and holds the config to it. Three attributes the registry says
may hold sensitive information are opt-in in no span definition and stay: `gen_ai.tool.description`,
`gen_ai.skill.description` and `gen_ai.skill.source.uri`. Every manifest in the companion, nine files across
the labs and the workflows, says `trace_content: false`, so the drop has no exception; a workflow whose
manifest allowed content would get a `where` clause naming it. The statements sit in two groups, one per
context. Merged into one list, they take the span-event context the processor infers for them all and run
once per event, and a test that runs the merged list finds the arguments still on a span without events.
`error_mode: propagate` makes a statement that fails drop its batch, so content never leaves on an error.

### Tail sampling

Six policies, any one of which keeps a trace: `failed` (a span with status ERROR or an `error.type`),
`refused` (the harness's `larkspur.refused`), `slow` (more than 10 seconds from the first span's start to
the last span's end), `over-budget` (one condition per workflow, from its manifest: a gateway span whose
`larkspur.cost_usd` is at least the run's `per_run_usd`), `fallback` (the gateway's `larkspur.fallback`),
and `share-of-the-rest` (10 percent, by an FNV-1a hash of the trace id with the salt `larkspur-ch16`;
`LARKSPUR_TRACE_SHARE_PERCENT` changes it). Two alpha feature gates, off by default and passed on the
command line, record on each kept trace why it was kept. `usetracestate` writes the share it was kept at
into every span's tracestate as OpenTelemetry's sampling threshold, `ot=th:0` for a share of one and
`ot=th:e6666666666666` for ten percent, which is what step 2 found a store needs to weight a trace.
`recordpolicy` names the policy in the scope attribute `tailsampling.policy`: the first in the list among
those that kept the trace at the lowest threshold. Every keep-all policy reports a share of one, so only a
trace the share kept alone records `share-of-the-rest`.

The Collector sees one span at a time and can't add up a run's calls, so `over-budget` keeps a run one of
whose calls cost the whole budget. A run the gateway stopped at its budget fails, and `failed` keeps it. A
run that crossed its budget on its last call, by the sum of several, is marked on no span; its cost lines,
which are never sampled, still show it.

### The exporters

The span file is appended to, as chapter 5's processes append to theirs. CloudWatch gets OTLP/HTTP at
`https://xray.us-east-2.amazonaws.com/v1/traces`, signed by `sigv4auth` with service `xray` and Region
us-east-2, AWS's documented pattern (fact sheet 8.2), which step 7 then used. Langfuse gets OTLP/HTTP at
`LANGFUSE_OTLP_ENDPOINT`, its `/api/public/otel`, to which the exporter adds `/v1/traces`, with basic auth
from `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` and the header `x-langfuse-ingestion-version: 4`. On
that pipeline alone, `transform/langfuse-cost` copies `larkspur.cost_usd` into `gen_ai.usage.cost`, which
Langfuse prefers to its own estimate (O-D4), so chapter 5's span and its attribute test stay as they are.

### Which settings are the defaults

Whatever `config.yaml` leaves out is the component's default at v0.164, and some values it writes down are
defaults too.

- The OTLP receiver takes HTTP on `127.0.0.1:4318`; the default is `localhost:4318`, and gRPC, left out,
  doesn't listen.
- `decision_wait: 30s` and `num_traces: 50000` are the tail sampler's defaults. It keeps its defaults for
  `decision_wait_after_root_received` (0, off), `sampling_strategy` (`trace-complete`), the decision caches
  (none) and `sample_on_first_match` (off). The share's `hash_salt` replaces `default-hash-seed`.
- `transform/drop-content` sets `error_mode: propagate`; `transform/langfuse-cost` keeps the default,
  `ignore`.
- `batch: {}` takes its defaults: a batch at 8,192 spans or after 200 ms, with no maximum. The run's spans
  come to about 430 bytes each before compression, so 8,192 of them make about 3.5 MB, under the 10,000 spans
  and 5 MB CloudWatch takes in one request (fact sheet 8.2). The request that carried the failed run's stack
  traces averaged 1.5 KB a span, and `send_batch_max_size` would cap a batch if Larkspur's spans grow.
- The file exporter's `append: true` replaces the default, which truncates the file at every start. Its
  format (`json`), its one-second flush and no rotation are the defaults, and the exporter is alpha (fact
  sheet 8.4).
- Both `otlp_http` exporters keep their defaults: protobuf, gzip (which AWS's example sets explicitly), a
  30-second timeout, retries from 5 seconds that give up after 300, and a queue of 1,000 requests.
- `sigv4auth` gets its Region and service written out; the extension would otherwise try to infer them from
  the endpoint.

### Validation

`otelcol-contrib validate` accepts `config.yaml` and rejects a transform statement that doesn't parse. It
doesn't parse the tail sampler's conditions: a policy that names `STATUS_CODE_EROR` passes `validate` and
stops the Collector at start. So the tests start the Collector with the config as well as validate it.

### The local run

`collector/run_local.py` starts chapter 5's three fake backends, its LiteLLM gateway with the callback that
writes the cost lines and the `chat` spans, and its MCP server over Streamable HTTP with its call log, and
runs the harness in its own process, all as chapter 5 wrote them. The gateway, the MCP server and the
harness each export their spans to the Collector, and `LARKSPUR_TRACE_TOOL_ARGS=1` makes the harness and the
server put the tool arguments on their spans, so the drop has content to drop. The Collector runs
`config.yaml` with an overlay for the run alone: the ports, CloudWatch's endpoint pointed at its fake, and a
tap, a pipeline straight from the receiver to a third fake that shows what arrived before any processor, and
when. Its environment holds only dummy credentials, an AWS key named `LARKSPURLABDUMMYKEY0` and Langfuse
keys `pk-lab-dummy` and `sk-lab-dummy`, and points the AWS SDK away from this machine's shared files and the
instance metadata. The fakes record each request with its path, its headers and its spans, and CloudWatch's
keeps the raw body, so the SigV4 signature can be computed again from the dummy secret.

The run has two phases, each with a Collector of its own on the same port:

- every-run, with the share of the rest at 100 percent, so every run is kept: chapter 5's golden set of 20
  questions and five runs made to be kept. `refused-alerts` asks for alerts while the harness allows only
  `get_pod_status`. `over-budget-pasted-log` is a restart request padded to 170,003 words, as if someone
  pasted a log, and its one call costs 0.51 US dollars at the fakes' stand-in prices against W2's 0.50.
  `fallback-primary-down` runs with the primary backend told to fail, `slow-model` waits 12 seconds before
  its first model call, and `failed-both-down` runs with the primary and the fallback failing.
- sampled, at the configured 10 percent: the golden set five times and the same five runs, 105 runs.

Runs start 1.1 seconds apart, to stay under W2's 120 requests a minute. The run takes about four minutes,
and `collector/analyze.py` turns its raw records into `results/2026-11-03/collector/`.

### What reached each store

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

All three processes sent spans, every run's trace reached the Collector, and the three stores kept the runs
the policies say to keep, each with every span it sent. The trace ids are the ones in the harness's log, the
tool server's log and the gateway's cost lines:

|Phase |Runs |With harness log lines |With a tool call |Of those, in the tool server's log |With gateway cost lines |Kept runs with one gateway span per cost line |
|---|---|---|---|---|---|---|
|every-run |25 |25 |21 |21 |25 |25 of 25 |
|sampled |105 |105 |97 |97 |105 |21 of 21 |

The last column counts the cost lines of calls the gateway sent, `call` and `failed`; a refusal before a
call has a line and no span. The failed run has one harness line, `tools_verified`, because chapter 5's
harness writes no line when a run raises. Its failure shows in its spans and in the gateway's `failed` line.

### Content

|Phase |Attribute |On spans that reached the Collector |In the span file |At CloudWatch's fake |At Langfuse's fake |
|---|---|---|---|---|---|
|every-run |`gen_ai.tool.call.arguments` |42 |0 |0 |0 |
|sampled |`gen_ai.tool.call.arguments` |194 |0 |0 |0 |

Chapter 5's processes put no other content attribute on their spans. The tests send the other 14, on spans
with events and without and on the events themselves, and none of them reaches a store either.

### The decisions

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

Each decision is the one `collector/policies.py` gives when it computes the policies again from what reached
the Collector, and the Collector's own count for each policy agrees. In the sampled phase `failed` matches
seven runs: the golden set's question about a service that doesn't exist, five times, whose tool call ends
in an error, and the two runs that fail. The fallback run's primary failed first and its span carries the
error, so `failed` keeps it and is the policy it records; in the tests, a fallback with no error records
`fallback`. At 10 percent the share kept 11 of the 95 runs no other policy matched, exactly the 11 FNV-1a
gives. The hash mixes a trace id's last bytes poorly: 1,000 ids that differ only there all fall on the same
side of the share, so it needs the random trace ids W3C asks for, which chapter 5's `new_trace_id` makes.

### The delay

|Phase |Kept traces |decision_wait |Receipt to Langfuse's fake |Receipt to CloudWatch's fake |Last span's end to Langfuse's fake |
|---|---|---|---|---|---|
|every-run |25 |30 s |30.20 / 30.74 / 31.06 |30.20 / 30.74 / 31.06 |20.15 / 31.26 / 32.14 |
|sampled |21 |30 s |30.21 / 30.67 / 30.92 |30.21 / 30.68 / 30.92 |18.32 / 31.17 / 32.42 |

The times are in seconds, as minimum / median / maximum. The tail sampler holds each trace for its
`decision_wait` of 30 seconds, counted from the trace's first span, and then up to a second for its timer
and 200 ms for the batch: 30.2 to 31.1 seconds from the Collector's receipt to the fakes. Counted from the
end of a run, the delay was 18 to 20 seconds for the slow run, whose first spans reached the Collector while
it waited on its model, and up to 32.4 seconds for the others, which adds each process's export delay of up
to 5 seconds.

The same 30 seconds bounds what the policies see. A decision is made on the spans that have arrived, so a
run longer than about 25 seconds, the wait less the export delay, can be judged on its first spans, and its
later spans follow that decision. A test sends a 40-second root span after a 2-second decision, and the
trace isn't kept, although the trace as a whole lasts longer than the threshold. With
`decision_wait_after_root_received` set, the decision comes a set time after the root span arrives, with
`decision_wait` as the cap, and the same test keeps the trace as slow a few seconds after its root. Every
run here has the harness's `invoke_agent` span as its root, but W5's gateway calls send a bare trace id with
no `traceparent`, so by chapter 5's rule each of its `chat` spans is a root of its own, and a root trigger
would decide a night on its first model call. The config keeps the plan's 30 seconds (O-D3, amended), and
the chapter can weigh a root trigger against that. Step 3b gives W5's night one root and measures both
settings on it (below).

### What the fakes prove, and what they can't

|Phase |Fake |Requests |Path |Authorization |Other headers |Refused by the fake |
|---|---|---|---|---|---|---|
|every-run |Langfuse |17 |`/api/public/otel/v1/traces` |Basic, decoding to `pk-lab-dummy:sk-lab-dummy` on every request |`x-langfuse-ingestion-version: 4` on every request |0 |
|every-run |CloudWatch |17 |`/v1/traces` |`AWS4-HMAC-SHA256`, key `LARKSPURLABDUMMYKEY0`, scope `us-east-2/xray/aws4_request`, signature recomputed from the dummy secret on 17 of 17 |`X-Amz-Date` on every request; signed: `content-encoding;content-length;content-type;host;x-amz-date` |0 |
|sampled |Langfuse |19 |`/api/public/otel/v1/traces` |Basic, decoding to `pk-lab-dummy:sk-lab-dummy` on every request |`x-langfuse-ingestion-version: 4` on every request |0 |
|sampled |CloudWatch |19 |`/v1/traces` |`AWS4-HMAC-SHA256`, key `LARKSPURLABDUMMYKEY0`, scope `us-east-2/xray/aws4_request`, signature recomputed from the dummy secret on 19 of 19 |`X-Amz-Date` on every request; signed: `content-encoding;content-length;content-type;host;x-amz-date` |0 |

|Phase |Gateway spans with `larkspur.cost_usd` at Langfuse's fake |With `gen_ai.usage.cost` equal to it |Spans with `gen_ai.usage.cost` in the span file or at CloudWatch's fake |
|---|---|---|---|
|every-run |45 |45 |0 |
|sampled |38 |38 |0 |

Every request to the Langfuse fake carried basic auth from the environment and
`x-langfuse-ingestion-version: 4`, and each gateway span with a cost carried `gen_ai.usage.cost` equal to
`larkspur.cost_usd`. No other store got the copy, and the gateway spans without a cost are calls that
failed. Every request to the CloudWatch fake was signed with SigV4 for `xray` in us-east-2 with the dummy
key, and the signature, computed again from the dummy secret over the gzip body as it was sent, matched each
time; a test checks that computation against botocore's signer. A matching signature shows the Collector
follows SigV4 with the key it holds. Whether AWS accepts a real key's requests, and what the backends do
with the spans, step 7 answered on 9 November: CloudWatch took every span and Transaction Search kept them in `aws/spans`
with Logs Insights finding all of them, the agent and service views stayed unmeasured, Langfuse read the cost and built
the trace tree and the token counts, and neither kept the tracestate that holds the share (the cloud session, below).

### join.py

`collector/join.py <trace id>` prints every record of one run from the four local stores: the harness log,
the tool server's log, the gateway's cost lines with their total, and the spans the Collector kept, as a
tree with offsets, durations and the share. On the first phase's stores, for the run that stood in for
fig-16-01 until step 3b:

```
trace aa25e8a155834076a5bc9aeb8b2e8b73

harness log: 3 records
  {"ts": "2026-11-03T19:36:45.517+00:00", "event": "tools_verified", "trace_id": "aa25e8a155834076a5bc9aeb8b2e8b73", "transport": "http", "tools": {"get_pod_status": "6a390080cc1b", "get_recent_alerts": "8e9ceceb650d"}, "lock": "labs/ch05/mcp-server/tools.lock.json"}
  {"ts": "2026-11-03T19:36:46.773+00:00", "event": "tool_call", "trace_id": "aa25e8a155834076a5bc9aeb8b2e8b73", "tool": "get_pod_status", "args": {"service": "claims-api"}, "transport": "http", "ok": true}
  {"ts": "2026-11-03T19:36:46.959+00:00", "event": "answer", "trace_id": "aa25e8a155834076a5bc9aeb8b2e8b73", "refused": false, "answer": "claims-api has 2 of 3 pods ready. Not ready: claims-api-7d9f8b6c4-t8w2c (CrashLoopBackOff, 7 restarts)."}

tool server log: 1 record
  {"ts": "2026-11-03T19:36:46.702+00:00", "event": "tool_call", "trace_id": "aa25e8a155834076a5bc9aeb8b2e8b73", "trace_source": "request", "tool": "get_pod_status", "args": {"service": "claims-api"}, "identity": "larkspur-ops-reader", "transport": "streamable-http", "ok": true}

gateway cost lines: 2 records: 2 served, 0.000876 USD, 177 tokens in, 23 out
  {"ts": "2026-11-03T19:36:46.698+00:00", "event": "call", "trace_id": "aa25e8a155834076a5bc9aeb8b2e8b73", "workflow": "w2-ops-assistant", "data_class": "internal", "requested_alias": "larkspur-chat", "served_alias": "larkspur-chat", "fallback": false, "fallbacks_disabled": false, "deployment": "primary", "region": "ca-central-1", "served_model": "fake-primary", "prompt_tokens": 74, "completion_tokens": 10, "cost_usd": 0.000372, "latency_ms": 752}
  {"ts": "2026-11-03T19:36:46.960+00:00", "event": "call", "trace_id": "aa25e8a155834076a5bc9aeb8b2e8b73", "workflow": "w2-ops-assistant", "data_class": "internal", "requested_alias": "larkspur-chat", "served_alias": "larkspur-chat", "fallback": false, "fallbacks_disabled": false, "deployment": "primary", "region": "ca-central-1", "served_model": "fake-primary", "prompt_tokens": 103, "completion_tokens": 13, "cost_usd": 0.000504, "latency_ms": 0}

spans: 11 kept by share-of-the-rest, at a share of 1
  invoke_agent harness  [harness]  +0 ms, 1532 ms  (kept at a share of 1)
    MCP send server/discover  [harness]  +84 ms, 4 ms
      server/discover  [mcp-server]  +84 ms, 0 ms
    MCP send tools/list  [harness]  +88 ms, 1 ms
      tools/list  [mcp-server]  +89 ms, 0 ms
    chat larkspur-chat  [gateway]  +509 ms, 752 ms
    execute_tool get_pod_status  [harness]  +1271 ms, 74 ms
      MCP send tools/call get_pod_status  [harness]  +1273 ms, 1 ms
        tools/call get_pod_status  [mcp-server]  +1274 ms, 0 ms
          execute_tool get_pod_status  [mcp-server]  +1274 ms, 0 ms
    chat larkspur-chat  [gateway]  +1527 ms, 0 ms
```

On the sampled phase's stores, a run the sampler dropped still shows its log lines and cost lines, and its
spans section says none were kept. Each store is a class with a `records(trace_id)` method, so the model invocation
log could be one more; step 7 read its records by the trace id in `requestMetadata` and added no store. CloudTrail is
written now, against nine sample events in the shapes
AWS documents for an AssumeRole with session tags and for a later call made with the role's credentials
(`collector/samples/cloudtrail-events.json`; none was recorded from an account). The amended O-D2 gives an
event three ways to its run. The tool server names the role session with the engineer's object ID, a dot,
and the trace id's first 16 hex characters, and every event made with the session's credentials shows that
name inside `userIdentity.arn`. The AssumeRole event alone records the session tag `trace_id`, which holds
the whole trace id. And a later event may carry, in `userIdentity.accessKeyId`, the key that AssumeRole
returned; join.py uses it only when CloudTrail filled it in. The samples hold three runs. Two take the
amended session name, and all their later calls join, one through an empty `accessKeyId`. The third takes
chapter 6's session name, the object ID alone, and its call with an empty key joins nothing, the case the
amendment closes. `--event FILE` goes the other way, from one event to its run: the session name gives 16
characters, and the AssumeRole's tag or the local logs give the whole trace id. Sixteen hex characters are
64 bits, so two runs share them only by chance, and the tag settles it while the AssumeRole is in the
window.

### The trace for fig-16-01

Step 3 wrote a stand-in for fig-16-01 here: a W2 question from chapter 5's skeleton, "Is claims-api healthy?",
answered with two model calls and one tool call by the rule model, the run join.py prints above. Step 3b
replaced it with W2's own run of the same question on gpt-oss-20b through the Collector
(`results/2026-11-03/workflows/fig-16-01-trace.json`, below), and the stand-in's file is gone. The run stays in
the every-run phase's stores.

## The workflows through the Collector (step 3b)

Step 3b runs four workflows on the local models, each through its own gateway and the pinned Collector: W2's
golden set, W3's 24 incidents and W5's fixture night on gpt-oss-20b (Ollama 0.22.1), and W4's 8 changes on
gpt-oss-20b and on Gemma 4 12B (the portable Ollama 0.40.13, its thinking off), one model on the GPU at a time.
`collector/run_workflows.py` runs each workflow's own code: its harness, its servers, its gateway with chapter
5's callback, and its scoring. `collector/analyze_workflows.py` turns the raw records into
`results/2026-11-03/workflows/`, and every table below is its `summary.md`'s. No process called a cloud, and the
Collector held no credential.

### The Collector, with CloudWatch and Langfuse off

The runs use `config.yaml` with the two cloud exporters off; step 7 turns them on. `otelcol.local_config` removes
the CloudWatch and Langfuse exporters, the two authenticators only they use, Langfuse's pipeline and its cost
copy, and nothing else, so the content drop, the tail sampler with its six policies, the batch and the span file
run as step 3 ran them, and the Collector's environment holds the span file's path and the share and no
credential. The run's overlay adds the receiver's port, the Collector's own metrics, step 3's tap before any
processor, and a sink: an exporter after the sampler, beside the span file, to a fake on 127.0.0.1 that records
when each kept span left. W2, W3 and W4 ran with the share of the rest at 100 percent, so the span file holds
every span the processes sent; W5's two runs keep `config.yaml`'s 10 percent, since the sampler is what they
measure.

Every process of a run gets `OTEL_EXPORTER_OTLP_ENDPOINT`. The harnesses run inside the workflows' eval scripts,
and none of those installs a tracer provider, so the runner installs chapter 5's in its own process for the
harness, as chapter 5's `client.py` and W4's `scribe.py` do in their `main()`. W4's lab script starts its gateway,
and W5's its gateway and its readers, with the endpoint removed ("the lab never talks to a collector",
`harness/launch.py`); the runner starts them the same way with the endpoint kept, and changes nothing else
about a run.

### The runs

|Run |Ollama |Cases |Passed |Model calls |Input tokens |Output tokens |Model time (s) |Run (s) |Share of the rest |decision_wait |Root trigger |
|---|---|---|---|---|---|---|---|---|---|---|---|
|W2, gpt-oss-20b |Ollama 0.22.1 on 11434, serving gpt-oss-20b |25 |21 |49 |47,588 |6,438 |46.6 |57.8 |100% |30 s |off |
|W3, gpt-oss-20b |Ollama 0.22.1 on 11434, serving gpt-oss-20b |24 |14 |142 |232,833 |16,130 |128.1 |163.1 |100% |30 s |off |
|W4, gpt-oss-20b |Ollama 0.22.1 on 11434, serving gpt-oss-20b |8 |8 |8 |1,541 |1,570 |15.9 |24.2 |100% |30 s |off |
|W4, gemma4-12b |Ollama 0.40.13 on 11435, serving gemma4-12b with its thinking off |8 |8 |8 |1,118 |207 |1.9 |10.1 |100% |30 s |off |
|W5, decision_wait 30 s |Ollama 0.22.1 on 11434, serving gpt-oss-20b |1 |1 |14 |8,844 |8,134 |51.3 |54.9 |10% |30 s |off |
|W5, root trigger |Ollama 0.22.1 on 11434, serving gpt-oss-20b |1 |1 |14 |8,844 |8,134 |51.2 |54.6 |10% |300 s |10s |
|all | | | |235 |300,768 |40,613 |295.0 |364.7 | | | |

The six runs took 295 seconds of model time, 235 calls with 300,768 input and 40,613 output tokens. Five smoke
runs of one case each and three runs made again (below) took 159 seconds more, 169 calls with 256,519 input and
19,056 output tokens, so the step used the GPU for about seven and a half minutes. W2 passed 21 of its 25 cases,
W3 14 of 24 under the scorer of that day (12 under the checks fixed in #122, as W3's README records), W4 8 of 8
on both models, and the night its golden checks. These runs exist for their traces and their cost lines; each
workflow's recorded evaluation stays where its README describes it.

### Where the runs are kept

Each workflow's results and its gateway's cost lines are in its `eval/traced/2026-11-03/`, as its runner writes
them: W2's `answers-gpt-oss-20b.json` with `logs-gpt-oss-20b/` (the gateway's lines, the harness's log, the
three servers' logs), W3's `runs-gpt-oss-20b.json` with each incident's trace id and `logs-gpt-oss-20b/`, and W4's
packs, results, summary, metrics and `logs-<model>/` for both models, the gateway's lines beside the agents'
logs. They sit beside `eval/results/` because chapter 15's registry takes every run in `eval/results/` as one of
the 26 runs its replay, its judge and its tests were built on, and these four would have become its 27th to
30th. The ledger reads them from `eval/traced/` (`costlines.traced_runs`), and a test holds chapter 15's
registry to its 26.

### Which processes sent spans

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

Every process that runs the workflows' code sent spans: the harnesses, the MCP servers, the A2A agents, and the
gateways through chapter 5's callback. Ollama sent none. It isn't instrumented, so a model call's span is the
gateway's, from the request's arrival to the response, and the time inside the model is one interval. W3's
approval service runs inside the harness's process and opens no span, nor do W5's GitHub fake and ledger.

### What a run's trace id holds

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

- W2: one tree a question. The harness's `invoke_agent w2-harness` span is the root. The MCP client's spans and
  the servers' spans sit under it through the `traceparent` the MCP SDK puts in `_meta`, and the gateway's
  `chat` spans through the `traceparent` chapter 5's `GatewayModel` puts in the request's metadata. The one case
  with no span is w2-13, the question W2 refuses as out of scope before it opens its span; its log line still
  carries its trace id.
- W3: the incident's trace id holds the gateway's `chat` spans alone, each a root of its own. W3's harness opens
  no run span, and it calls its bridges with no span context, so with the runner's tracer provider each read
  opens a trace of its own with a random id: the harness's `execute_tool` span, the MCP client's span, and the server's spans under them. 23 of
  the 24 incidents had reads elsewhere, 121 traces with 482 spans that name the incident only in their
  `larkspur.trace_id` attribute. The MCP sessions' set-up, 240 traces with 480 spans, names no incident at all.
- W4: one trace id a change, with two roots. The scribe's `invoke_agent change-management` span holds the
  analyst's and the risk scorer's spans through the `traceparent` in the A2A request; the risk scorer's
  rationale call sends the gateway a bare trace id, so the gateway's `chat` span is a second root.
- W5: one tree a night, after the change below.

### At config.yaml's 10 percent

|Run |Traces |Kept at 10% |By policy |Spans kept |Cases with spans |Kept whole |Kept in part |Kept not at all |
|---|---|---|---|---|---|---|---|---|
|W2, gpt-oss-20b |24 |6 |failed 4, share-of-the-rest 2 |111 of 473 |24 |6 |0 |18 |
|W3, gpt-oss-20b |385 |39 |failed 1, share-of-the-rest 35, slow 3 |128 of 1104 |24 |0 |11 |13 |
|W4, gpt-oss-20b |8 |1 |share-of-the-rest 1 |4 of 32 |8 |1 |0 |7 |
|W4, gemma4-12b |8 |1 |share-of-the-rest 1 |4 of 32 |8 |1 |0 |7 |

The share decides trace by trace. W2's and W4's runs have one trace id each, so 10 percent keeps a run whole or
not at all. W3's incidents are spread over many traces, its model calls, each read and each session's set-up,
and each is sampled on its own: of the 24 incidents none would be kept whole, 11 in part and 13 not at all. A
policy that keeps one of an incident's traces, such as `failed` on a read that errs, keeps that trace alone.

### W5's night as one trace

W5's night already opened an `invoke_agent w5-night` span around its work (`harness/night.py`), but the night
wasn't one trace. Its process installed no tracer provider, and the prose seam sent the gateway the night's
trace id with no `traceparent`, so by chapter 5's rule each `chat` span was a root of its own (step 3's
finding). Step 3b changes two things in W5's harness, both in its tracing. `prose.write` takes a `traceparent` and
puts it in the request's metadata beside the trace id, and the night passes its span's. The night's commands
install chapter 5's tracer provider (`install_tracing`), which exports to `OTEL_EXPORTER_OTLP_ENDPOINT` when it
is set and otherwise to `traces.jsonl` in `--out`. The span opens after the `night_start` line and closes
before `night_done`, with the night's trace id, and every read and model call of the night sits under it. W5's
new test runs the command against its readers and a fake gateway on 127.0.0.1 and follows every span of the
night, the readers' included, to the one root.

### W5's night under the two settings

|Setting |Night (s) |Spans sent |Kept |Policy recorded |Share recorded |First span in to first out |Root in, after the first span |Root in to root out |Spans in before the first left |Their decision |The whole trace's decision |Held per span (min / median / max) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
|decision_wait 30 s |54.9 |359 |359 |slow |1 |30.5 |58.0 |0.1 |352 |kept by slow |kept by slow |0 / 27.6 / 30.5 |
|decision_wait 300 s, root trigger 10s |54.7 |359 |359 |slow |1 |68.4 |57.9 |10.5 |359 (root among them) |kept by slow |kept by slow |10.4 / 65.6 / 68.4 |

With `config.yaml`'s `decision_wait` of 30 seconds, the sampler decided the night 30.5 seconds after its first
span arrived, on the 352 spans that had come by then, and kept it as `slow`. The root and six other spans
arrived after the decision and followed it, and the Collector's own count of late spans says 7. The night ran
54.9 seconds, so its last model calls and its root couldn't change the decision. Every night takes longer than
the 10 seconds `slow` asks for, so `slow` keeps every night; any other policy sees only a night's first 30
seconds.

With the root trigger, `decision_wait_after_root_received` at 10 seconds and `decision_wait` raised to 300
seconds, the decision came 10.5 seconds after the root arrived, 68.4 seconds after the first span, on all 359
spans, and none was late. The trigger can only bring a decision forward: with `decision_wait` at 30 seconds it
would have decided the night on its first spans, before the root came, and a test sends a root past that cap
to show it. The trigger costs time: each span was held 65.6 seconds at the median against 27.6, a trace that
never sends a root waits the whole 300 seconds, and the Collector keeps every trace in memory until it
decides.

### fig-16-01

`results/2026-11-03/workflows/fig-16-01-trace.json` replaces step 3's stand-in with W2's real run: the first
case in the golden set's order with two model calls and one read that passed, chapter 3's median (ch03:58). It
is w2-01, "Is claims-api healthy?", the stand-in's question, on gpt-oss-20b, in 2.58 seconds. The file holds the
span tree with offsets and durations, the stores the trace id joins with their record counts, and what
`join.py` prints for fig-16-01's run:

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

The harness's log holds the three servers' tool checks, the read and the answer; the kubernetes server's log
the read; the gateway's two cost lines the tokens; the span file 19 spans under one root. CloudWatch, Langfuse,
the model invocation log and CloudTrail all took a trace id in step 7 (the cloud session, below). At `config.yaml`'s 10
percent this
trace wouldn't have been kept: none of its spans matches a keep-all policy, and the share's hash leaves it out.

### What each workflow's tracing covers, and what it doesn't

Chapter 2 makes the trace id the center of the observability design (ch02:172): only the harness log can
connect the provider's model log, the harness log and the cloud audit log, "and only if the trace identifier is
written into every tool call it makes". Step 3b checks that against the four workflows as they are.

- The logs and the cost lines join every case by its trace id, in every workflow: the harness's lines, the tool
  servers' lines from `_meta`, and the gateway's cost lines carry it, and the ledger joins step 3b's cost lines
  to their cases by it. W2's results file and W3's record keep no trace id, so the runner kept them beside the
  records, W2's in the harness's log and W3's in `trace-ids-gpt-oss-20b.json`.
- The spans join a case only where the harness's process installs a tracer provider and every hop carries a
  `traceparent`. None of the four eval scripts installs one. With one installed, W2's and W5's harnesses give one
  tree a case, W4's gives two roots because its rationale seam sends a bare trace id, and W3's gives a forest:
  its harness opens no run span and hands its reads no span context.
- No span covers Ollama's time inside a call (the gateway's span holds it as one interval), W3's approval
  service and the wait for a person, W5's GitHub fake, or a question W2 refuses before its span opens. No content
  reached a span: no process set a content attribute, and `config.yaml` drops them anyway.
- For the sampler a forest is the worst case: W3's traces are sampled one by one, so a kept incident trace may
  carry none of its reads.

So chapter 2's rule holds for the logs and the cost lines, and for the spans only in W2 and W5. Two small changes
in W5's shape would close the gap: a run span in W3's harness with its context handed to the bridges, and a
`traceparent` from W4's rationale seam. This step changes neither harness; they are notes for W3's and W4's
plans (#10 and #11).

### W3 and W4 as one trace each

Both changes were made on 3 November, after step 3b, in W3's and W4's own code (#10, #11). W3's
`eval/lab.py` opens one `invoke_agent w3-incident` span an incident, with the incident's trace id, before its
five sessions, hands its context to every read's and every write's bridge, and hands its `traceparent` to
the model, which puts it beside the trace id in every request. W4's risk scorer hands its own span's
`traceparent` to the rationale seam. Each workflow's suite has a test that follows every span of a case to
one root, and neither change touches a record, a log line, or a cost line.

One case of each then ran again through this Collector on gpt-oss-20b, as step 3b ran them, with
`run_workflows.py --only`: w3-01 and w4-01, both passing. `collector/one_trace.py` keeps the two runs in
`results/2026-11-03/one-trace/`, beside step 3b's, and its `summary.md` sets each case against its own row
above. w3-01 sent 56 spans from seven processes, the harness, the five servers, and the gateway, and every
one sits under its trace id and under one root, the harness's `invoke_agent w3-incident`, with no span
elsewhere that names it and no trace that names no incident. In step 3b the same incident's trace id held 4
spans, each a gateway root, with 4 more traces of 15 spans elsewhere, beside the run's 240 traces of the
sessions' set-up. w4-01 sent 4 spans under one root, the scribe's, with the gateway's `chat` span under the
risk scorer's, where step 3b had two roots. So at `config.yaml`'s 10 percent each case is now one decision,
kept whole or not at all, as W2's and W5's are. The tables above stay as step 3b measured them.

### Found on the way

- On Windows `terminate()` ends a process without its exit handlers, so the spans still waiting in the
  OpenTelemetry SDK's 5-second batch are lost. The first smoke run stopped W2's gateway 3 seconds after its last
  call and lost both its spans and the kubernetes server's last two. W3's and W4's lab scripts stop their
  processes right after their last case, so a run traced as they stand loses its last seconds of spans. The
  runner waits 7 seconds after the last case is timed and scored, and a harness that traces to a collector has
  to flush its provider before its process stops.
- The first W3 run lost an incident to a closed connection: w3-22's fourth read found the metrics server's
  pooled connection closed (an `httpx` `ReadError`), and W3's harness, which doesn't retry a read, recorded the
  incident as an error. That run had also timed the runner's wait inside its last incident, as had the first W4
  run on each model, so all three were made again with the wait outside the timed cases, and the second runs
  are the ones kept.

## Budgets and switches (step 4)

Step 4 builds O-D7 on this workstation, with chapter 5's fake backends and no cloud call: the monthly budget per
workflow, the alarm at 80 percent to the owner and FinOps, the kill switch at the gateway, and the rung-down
switch. The identity half of the kill switch is written and tested offline here, and step 7 timed it on real
credentials. Chapter 2 promises a
budget per run and per month, an alarm at 80 percent of the monthly figure "to the owner and to Ingrid's team",
and a kill switch the on-call lead pulls as an emergency change (ch02:144, ch02:146, ch02:163, ch02:294).
Chapter 5 says the monthly budget "needs a counter that survives a restart, and that means LiteLLM's database"
(ch05:162), and chapter 1 that climbing down "has to be as easy as flipping a configuration value" (ch01:221).
Every table below is in `results/2026-11-03/budget/summary.md`, which `budget/drills.py` writes from
`drills.json` and `smoke.json`.

### The smoke test

Fact sheet 8.1 found an open defect in LiteLLM 1.106.6: on native Windows its watcher checks that Prisma's query
engine is alive with `os.kill(pid, 0)`, and two open pull requests say the call kills the engine. Key budgets,
soft-budget alerts and the key block all read and write LiteLLM's database through Prisma, so the step opened
with `budget/smoke.py`.

PostgreSQL comes from EnterpriseDB's zip of the 16.15 server binaries,
`postgresql-16.15-5-windows-x64-binaries.zip` (373,254,386 bytes), which EDB's download page lists under
"Binaries from installer"; LiteLLM's own Compose file runs PostgreSQL 16. `budget/postgres.py` checks the zip
against a pinned SHA-256, the digest EDB publishes in a file beside the zip on the same host, and reads that file
again at every fetch. The digest catches a damaged or changed download, though not a compromised host, and it
was the only check available: no signature covers the server's files. Windows reports 72 of the 73 programs and
libraries in `bin/` as unsigned; only `stackbuilder.exe` carries EnterpriseDB's Authenticode signature. Only
`bin`, `lib` and `share` are unpacked, into `budget/pg/`, which git ignores, and every start checks
`postgres.exe`, `initdb.exe` and `pg_ctl.exe` against their copies in the zip. Each run makes a fresh cluster
that listens on 127.0.0.1 with a password made for the run.

The scratch environment is chapter 5's requirements plus `prisma`, which resolved to prisma 0.15.0 with nodeenv
1.12.0. Prisma ran on the Node 22.19.0 already on PATH and fetched its CLI 5.17.0 from npm, and its engines, on
first use. Three things failed before the first full run, and the scripts now handle each. npm runs `cmd.exe`
about 110 characters below Prisma's home folder, and with that home under this session's long scratch path
Windows refused the working directory (WinError 267, then `ENOENT` from npm), so `--prisma-home` takes a short
folder. The Prisma CLI starts its `prisma-client-py` generator by name, so the environment's `Scripts` folder
goes on PATH, as activating the environment does. And `pg_ctl start` never returned while its output went to a
pipe, because the server it leaves running inherits the pipe; it writes to a log file now.

|Step|t (s)|Status|What it said|Engines alive|
|---|---|---|---|---|
|prisma generate|8.25|0||0|
|postgres up|14.05|||0|
|proxy up|35.81|||1|
|readiness|36.44|healthy||1|
|call 1, master key|37.73|200|[primary] Is claims-api healthy?|1|
|call 2, master key|38.36|200|[primary] Is policy-admin healthy?|1|
|key generate|39.05|200||1|
|call 3, the virtual key|39.75|200|[primary] Is claims-api healthy?|1|
|key block|40.39|200||1|
|call 4, the blocked key|41.03|401|Authentication Error, Key is blocked. Update via `/key/unblock` if you're an adm|1|
|key unblock|41.62|200||1|
|call 5, the key unblocked|42.27|200|[primary] Is claims-api healthy?|1|
|key row in the database|42.73|||1|
|after settling|63.36|||1|

The query engine survived. The proxy's log says `Watching engine PID ... via os.kill polling`, the watcher
polled once a second for the whole run, and the engine was alive when the script stopped the proxy 64 seconds
in. The probe at the end of `smoke.py` makes the watcher's call, `os.kill(child, 0)`, against a sleeping child
started the way the proxy starts its engine, from a process with a console of its own and from one with no
console at all, under each Python on this machine:

|Python|Prober|Processes on its console|os.kill(child, 0)|Child afterwards|
|---|---|---|---|---|
|3.12.9|console|2|returned|alive|
|3.12.9|no-console|0|raised OSError (winerror 6)|alive|
|3.10.11|console|2|returned|alive|
|3.10.11|no-console|0|raised SystemError (<built-in function kill> returned a result with an exception set)|ended, exit code 0|
|3.13.11|console|2|returned|alive|
|3.13.11|no-console|0|raised OSError (winerror 6)|alive|
|3.14.2|console|2|returned|alive|
|3.14.2|no-console|0|raised OSError (winerror 6)|alive|

On Windows, Python hands signal 0 to `GenerateConsoleCtrlEvent` as a Ctrl+C event. With a console the call
returns and the child carries on. With none the console call fails, and there Python 3.10.11 ended the child,
exit code 0, as `TerminateProcess(pid, 0)` would, and raised `SystemError`: the defect the pull requests
describe. Python 3.12.9, the labs' pin, raises `OSError` (winerror 6) instead and leaves the child alone, as do
3.13.11 and 3.14.2, and LiteLLM's watcher catches the error and stops polling. The defect needs both an older
interpreter and a proxy started with no console, as a Windows service or a scheduled task would start it. In a
terminal, or started by these scripts with a console of its own and its window hidden, LiteLLM's database works
on native Windows at the labs' pins. The full proxy wasn't run without a console: Prisma's console children
would each have opened a window on the desktop. One warning stays in the proxy's log, `LiteLLM Prisma Client
Exception connect(): 'Prisma' object has no attribute '_Prisma__engine'`, from its first attempt to connect; the
retry connected. The first runs also showed that stopping the `litellm` command leaves Prisma's query engines
running with no parent, because `litellm.exe` is a launcher, so the scripts stop the proxy's whole tree
(`taskkill /T`).

LiteLLM's database carries the budgets, the alert and the key block, then, as O-D7 planned, and the gateway
needs no budget callback of the lab's own. A Linux machine, step 7's VM for one, could run the same drills; step 7 didn't.

### A key per workflow, and its month

`budget/keys.py` makes one virtual key per workflow from its manifest, with `/key/generate` from LiteLLM's MIT
core. The workflow's name is the key's alias and goes into its metadata with the owner, the sponsor and the
maximum data class, since key tags need the license. The manifest's aliases are the key's models,
`per_month_usd` its `max_budget`, 80 percent of that its `soft_budget`, and `1mo` its `budget_duration`. This
step's config sets `timezone: America/Toronto`, so the month resets at midnight on the 1st in Toronto:

|Workflow|max_budget|soft_budget|budget_duration|Reset at (UTC)|Reset in Toronto|Midnight on the 1st in Toronto|
|---|---|---|---|---|---|---|
|w2-ops-assistant|200.0|160.0|1mo|2026-12-01T05:00:00+00:00|2026-12-01T00:00:00-05:00|yes|
|w3-incident|500.0|400.0|1mo|2026-12-01T05:00:00+00:00|2026-12-01T00:00:00-05:00|yes|

LiteLLM keeps the soft budget in a budget row it links to the key, which `/key/info` doesn't return; the drills
read it from the database. A test sets `keys.next_reset` against LiteLLM's own `get_next_standardized_reset_time`
at six moments, among them the evening of 30 November in Toronto, when UTC is already in December, and a month
on each side of a change of clocks. At LiteLLM's default of UTC, the reset would come at 19:00 on the last day of
the month in Toronto's winter.

### The key bound to its workflow

Chapter 5 says each workflow at Larkspur gets its own key, whose metadata names the workflow and its maximum
data class, and "the callback refuses tags that disagree with the key" (ch05:164); its lab had no database to do
it with. `budget/key_binding.py` is that check, a callback of this step's own registered ahead of chapter 5's,
which still writes every cost line and span, unchanged. `budget/ch05_callback.py` imports chapter 5's callback
from its own folder so that this step's config can name it.

|Case|Status|Kind|Message|
|---|---|---|---|
|W2's key, its own tags|200|answered||
|W2's key, W3's workflow tag|400|refused|request refused: the key is 'w2-ops-assistant''s, and the request says it is 'w3-incident'|
|W2's key, data class above its maximum|400|refused|request refused: data class 'confidential' is above the key's maximum ('internal')|
|the master key, which names no workflow|400|refused|request refused: the key names no workflow; model calls go through a workflow's own key|
|W3's key, its own tags|200|answered||

The master key makes no model call now, so every call is charged to some workflow's budget, and a workflow whose
key is blocked can't borrow another workflow's tag.

### The kill switch at the gateway

The gateway half of the switch is LiteLLM's `/key/block`. `budget/oncall.py kill <workflow>` finds the
workflow's key by its alias and blocks it by its hashed token, so the on-call lead never handles the key itself,
and writes the change record. LiteLLM evicts the key from its cache when it blocks it (fact sheet 8.1), and the
proxy keeps running. In the drill a W2 loop made one call every 0.25 seconds while the lead's command blocked and
unblocked the key five times:

|Cycle|/key/block (s)|First refusal in the loop (s)|In-flight calls that succeeded|Call right after the block|/key/unblock (s)|First success after the unblock (s)|Call right after the unblock|
|---|---|---|---|---|---|---|---|
|1|0.034|0.142|0|401|0.027|0.101|200|
|2|0.024|0.064|0|401|0.023|0.042|200|
|3|0.027|0.249|1|401|0.024|0.22|200|
|4|0.024|0.189|0|401|0.023|0.163|200|
|5|0.026|0.142|0|401|0.023|0.105|200|

The call made as soon as `/key/block` returned was refused in all five cycles with LiteLLM's 401, "Key is
blocked", and the call made as soon as `/key/unblock` returned was answered, so the switch takes effect from the
next request, both ways. The loop's first refusal came 0.142 seconds after the lead's command at the median and
0.249 at most, and its first answer after the unblock 0.105 and 0.22, numbers set mostly by the loop's own
interval. In cycle 3 one call already inside the gateway when the key was blocked finished normally. At the
gateway the book's "under a minute" holds with room to spare; the identity half, timed on real credentials in step 7,
took about eight seconds each way.

Each refused call left a `failed` line in chapter 5's cost log, 45 for the blocked key and 6 for the spent
budget below, and none of the 51 names a trace id or a workflow: LiteLLM refuses the call while it authenticates
the key, before any callback has read the request's metadata. A refusal at the gateway can't be joined to its run
from that log, a gap for the chapter's tracing (ch02:172).

### The reservation

Before it admits a call, LiteLLM 1.106.6 reserves the call's estimated cost on the key's spend counter: the input
tokens it counts, and the request's `max_tokens` or, when the request sets none, 16,384 output tokens. Once the
call is priced, after its answer has gone back, the reservation gives way to the call's cost. The admission
check and the budget alerts read the counter with its reservations, and a reservation that doesn't fit in what
is left is cut down to fit, which brings the counter exactly to the budget. Chapter 5's harness sets no
`max_tokens`, so each call reserved about 0.246 US dollars at the stand-in prices, and the two drills below start
their month one reservation and about three runs short of the threshold. At Nova Lite's price in Canada the same
reservation would come to about 0.4 US cents.

### The 80 percent alert

`budget/receiver.py` stands in for the owner's and FinOps's channels. LiteLLM POSTs its webhook event to it
(`alerting: ["webhook"]` and `WEBHOOK_URL`; email alerts need the license), and the receiver writes one line per
alert to its outbox, naming the owner from the manifest of the workflow the key belongs to, and
`finops@larkspur.example`. The drill set W2's month to 159.75064 with `/key/update`, as if the month's earlier
calls had been made, and ran the harness:

|Run|Answered|Cost (USD)|Month after (USD)|
|---|---|---|---|
|1|yes|0.000876|159.751516|
|2|yes|0.000876|159.752392|
|3|yes|0.000876|159.753268|
|4|yes|0.000876|159.754144|
|5|yes|0.000876|159.75502|

The alert came during run 5, with the month's priced calls at 159.754144. The run's first call had reserved its
0.246 dollars, and when its second call came the counter stood at 160.000351, past the soft budget: event
`soft_budget_crossed`, sent to sam.okafor@larkspur.example and finops@larkspur.example. So the alarm comes once
the month plus one call's reservation reaches 80 percent, and with chapter 5's harness that is about a quarter
of a dollar before the priced calls get there. Every alert the receiver got during the drills:

|Received (UTC)|Event|What it is|Spend|max_budget|soft_budget|Projected spend|Forwarded to|
|---|---|---|---|---|---|---|---|
|23:45:39.755|threshold_crossed|the month's pace projected past the soft budget|159.751012|160.0||1722.8720211343243|sam.okafor@larkspur.example, finops@larkspur.example|
|23:45:41.851|soft_budget_crossed|the soft budget reached|160.00035100000002|200.0|160.0||sam.okafor@larkspur.example, finops@larkspur.example|
|23:45:58.200|budget_crossed|the month's pace projected past the soft budget|199.751012|160.0||2154.0959676841035|sam.okafor@larkspur.example, finops@larkspur.example|
|23:47:05.864|budget_crossed|the budget reached|200.0|200.0|160.0||sam.okafor@larkspur.example, finops@larkspur.example|

After a priced call LiteLLM also projects the month's spend from its pace so far, and three days into November
the seeded month projected to 1,723 dollars and then 2,154. The projection alert passes the soft budget as its
`max_budget`, so LiteLLM's event logic labels it `threshold_crossed` or `budget_crossed` against 160, and the
receiver names it from its `projected_spend`. LiteLLM holds back a repeat of an alert for 24 hours, keyed on the
event and the key's token, and the projection and the key's own budget alerts use the same token. The relabeled
projections therefore took the places of the real 95 and 100 percent alerts: the 95 percent alert never came,
and the 100 percent alert came only after the restart below had emptied the proxy's in-memory cache. A receiver
that pages on the event name alone would page on the projection and miss the real ones for a day; the 80 percent
alarm, `soft_budget_crossed`, is the one this step relies on.

### The stop

The drill then set the month to 199.75064, a reservation and three runs short of 200:

|Run|Answered|Stop|Status|Calls|Month after (USD)|
|---|---|---|---|---|---|
|1|yes|||2|199.751516|
|2|yes|||2|199.752392|
|3|yes|||2|199.753268|
|4|yes|||2|199.754144|
|5|no|monthly_budget|422|1|199.754516|
|6|no|monthly_budget|422|1|199.754888|
|7|no|monthly_budget|422|1|199.75526|
|8|no|monthly_budget|422|1|199.755632|

Runs 1 to 4 were answered. Run 5's first call went through with its reservation cut to the 0.2459 dollars left,
which brought the counter to 200, and its second call got LiteLLM's 422, "Budget has been exceeded! ... Current
cost: 200.0, Max budget: 200.0". `budget/stops.py` counts a 422 that names a budget as `monthly_budget`, never
retries it, and ends the run there; chapter 5's per-run budget keeps its 429, and the kill switch its 401. Runs 6
to 8 went the same way, one call through and the next refused, so the month crept up by one call's cost each
time and stood at 199.755632, 0.244 dollars short of its budget, when the drill stopped. A harness that set
`max_tokens` would see the alarm and the stop come later by most of that margin.

### A restart, and the monthly reset

The spend lives in the database, and a restart doesn't touch it. LiteLLM writes spend there in batches about
every ten seconds, so the drills wait for the batch writer to drain before they set a month. The stop drill
leaves the month a reservation short, where a refusal depends on whether LiteLLM has priced the run's first call
yet, so the restart drill sets the month to the full 200.0. The run before the restart got the 422 at its first
call. The proxy came back in 20.38 seconds, reported the key's spend as 200.0, and the next run got the 422 at
its first call too.

For the reset, the drill moved the key's `budget_reset_at` into the past in the database, standing in for the
1st of the month, and ran LiteLLM's reset job every 5 to 10 seconds instead of about every ten minutes
(`PROXY_BUDGET_RESCHEDULER_MIN_TIME` and `_MAX_TIME`). The job set the spend to 0.0 within 13.47 seconds and the
next reset to 2026-12-01T05:00:00+00:00, midnight on the 1st in Toronto, and the next run was answered.

### The rung-down switch

`budget/rungs.py` reads one file per workflow, the override the on-call lead writes, at the start of each run and
before the first model call. An override can only lower the manifest's rung; one at or above it changes nothing.
A file the harness can't fully read stops the run before any call: YAML that doesn't parse, a file that isn't a
mapping, another workflow's name, a rung that isn't an integer from 0 to 5 (a quoted "1" or `true` included), or
a key it doesn't know. Below the manifest's rung, every tool the manifest marks `writes: true` leaves the
allowlist and the tools the model is offered. `budget/rung_harness.py` runs chapter 1's loop, unchanged, with a
scripted model and fake tools that count their calls, on chapter 5's W3 manifest:

|Case|Started|Rung|Write tools dropped|Model calls|Tool calls|Answer or why|
|---|---|---|---|---|---|---|
|no override; the model asks to restart|yes|3||2|{"restart_deployment": 1}|Restarted claims-api.|
|lowered to rung 1; the model asks to restart|yes|1|restart_deployment|1|{}|Refused: restart_deployment is not an allowed call.|
|lowered to rung 1; the model asks to read|yes|1|restart_deployment|2|{"get_pod_status": 1}|claims-api has 2 of 3 pods ready.|
|an override of rung 4, above the manifest's 3|yes|3||2|{"restart_deployment": 1}|Restarted claims-api.|
|a malformed override (rung: one)|no|||0|{}|w3-incident.yaml: rung 'one' is not an integer from 0 to 5|
|an override that isn't YAML|no|||0|{}|w3-incident.yaml: not YAML (ScannerError)|
|override removed; the model asks to restart|yes|3||2|{"restart_deployment": 1}|Restarted claims-api.|

At rung 1 the model's request for `restart_deployment` met chapter 1's decision box and the fake restart never
ran, while reads still did. The manifest marks writes and nothing finer, so the harness can't tell W4's ticket
from W3's restart, and a workflow lowered by any number of rungs loses every write. A finer rule would need the
manifest to say which writes act on a system and which only propose, a question for the chapter.

### The switch the on-call lead pulls, and the change record it leaves

```
python budget/oncall.py kill w2-ops-assistant --by oncall.lead@larkspur.example --change EC-1 --reason "..."
python budget/oncall.py reopen w2-ops-assistant --by oncall.lead@larkspur.example --change EC-1 --reason "..."
python budget/oncall.py rung w3-incident 1 --by oncall.lead@larkspur.example --change EC-2 --reason "..."
python budget/oncall.py restore-rung w3-incident --by oncall.lead@larkspur.example --change EC-2 --reason "..."
python budget/identity.py pull --manifest ../ch05/manifest/w3-incident.yaml    # with AWS credentials, step 7
```

Chapter 2 makes pulling the kill switch or moving a workflow down a rung "an emergency change authorized by the
on-call lead, documented within twenty-four hours, and reviewed at the next board meeting" (ch02:163). Each lever
appends one line to `changes.jsonl` in the state folder (`BUDGET_STATE_DIR`): the change's number, the lever, the
workflow, the state before and after, who authorized it and on what authority, when, the time by which it must
be documented, the review it goes to, the reason, and for the kill switch what LiteLLM answered and how long the
call took. The line opens the change's record; the write-up within the day and the board's review complete it.
The drills left twelve:

|Change|Lever|Workflow|From|To|By|Document by|Review|
|---|---|---|---|---|---|---|---|
|EC-DRILL-01|kill switch, gateway half|w2-ops-assistant|open|blocked|oncall.lead@larkspur.example|2026-11-04T23:45:02.749+00:00|the next board meeting|
|EC-DRILL-01|kill switch released|w2-ops-assistant|blocked|open|oncall.lead@larkspur.example|2026-11-04T23:45:04.794+00:00|the next board meeting|
|EC-DRILL-02|kill switch, gateway half|w2-ops-assistant|open|blocked|oncall.lead@larkspur.example|2026-11-04T23:45:06.826+00:00|the next board meeting|
|EC-DRILL-02|kill switch released|w2-ops-assistant|blocked|open|oncall.lead@larkspur.example|2026-11-04T23:45:08.859+00:00|the next board meeting|
|EC-DRILL-03|kill switch, gateway half|w2-ops-assistant|open|blocked|oncall.lead@larkspur.example|2026-11-04T23:45:10.911+00:00|the next board meeting|
|EC-DRILL-03|kill switch released|w2-ops-assistant|blocked|open|oncall.lead@larkspur.example|2026-11-04T23:45:12.945+00:00|the next board meeting|
|EC-DRILL-04|kill switch, gateway half|w2-ops-assistant|open|blocked|oncall.lead@larkspur.example|2026-11-04T23:45:14.983+00:00|the next board meeting|
|EC-DRILL-04|kill switch released|w2-ops-assistant|blocked|open|oncall.lead@larkspur.example|2026-11-04T23:45:17.016+00:00|the next board meeting|
|EC-DRILL-05|kill switch, gateway half|w2-ops-assistant|open|blocked|oncall.lead@larkspur.example|2026-11-04T23:45:19.049+00:00|the next board meeting|
|EC-DRILL-05|kill switch released|w2-ops-assistant|blocked|open|oncall.lead@larkspur.example|2026-11-04T23:45:21.089+00:00|the next board meeting|
|EC-DRILL-RUNG|rung down|w3-incident|manifest (3)|1|oncall.lead@larkspur.example|2026-11-04T23:47:21.996+00:00|the next board meeting|
|EC-DRILL-RUNG|rung restored|w3-incident|unreadable|manifest (3)|oncall.lead@larkspur.example|2026-11-04T23:47:22.013+00:00|the next board meeting|

The last line says `unreadable` because the drill had left a malformed override in place to test it, and the
restore removed that file.

The identity half is `budget/identity.py`, for step 7. `pull` puts one inline policy, `larkspur-kill-switch`, on
the workflow's harness role and on each of its tool roles, by chapter 6's names (`<workflow>-harness`, and
`<workflow>-<tool>` from `modules/manifest_roles`). The policy has two statements. `KillSwitchDenyAll` denies
every action on every resource, and since IAM evaluates a role's policies on every request, it refuses the
sessions already issued and any issued later. `KillSwitchRevokeIssued` is AWS's revoke of older sessions written
by hand, a deny on every action when `aws:TokenIssueTime` is before the pull plus 30 seconds (fact sheet 8.3). It
adds nothing while the deny-all stands; `release` takes the deny-all away and keeps this statement with its
cut-off moved to the release, so no credential issued before the release, during the incident included, works
again. `release --purge` removes the policy once the longest of those sessions has expired, an hour for chapter
6's harness role. Before it writes, the script reads each role and skips one whose `workflow` tag names another
workflow. A deny on issue time alone would let any session issued after the cut-off through, which is why the
deny-all comes first. The tests drive `pull`, `release` and `--purge` through botocore's Stubber, which checks
every request against IAM's API model and sends nothing; step 7 timed them on real credentials.

### What step 4 left for later

- Answered by step 7: `identity.py pull` and `release` on the cloud session's roles took about eight seconds to the
  first AccessDenied on credentials already issued, and about eight until a session issued after the release worked (the
  cloud session, below).
- Still open: the same drills on a Linux machine, if the chapter wants the database path shown on Linux as well, and a
  `max_tokens` on the harness's model calls, which would bring the alarm and the stop to within one call of their
  thresholds; chapter 5's `GatewayModel` sets none, and this step doesn't change it.

## Capacity and continuity (step 5)

Step 5 builds O-D8, O-D9 and O-D10 on this workstation, against fakes, with no model and no cloud call: a fake
provider with a tokens-per-minute quota, W2 and W3 contending for it through step 4's gateway under three kinds of
limit, retries, the gateway's own latency, the outage drill, PostgreSQL stopped under the gateway, the
repeated-write check, the calculator for committed capacity, and the continuity table. Chapter 3 says a fallback
stays in the manifest's Regions and the span records where it went (ch03:58), and chapter 8 leaves provisioned
capacity "a cost question for Ingrid Holm" (ch08:86). Every table below is in
`results/2026-11-03/capacity/summary.md`, which `capacity/run_drills.py` writes from `drills.json`,
`limiter-cache.json` and `calculator.json`; every request behind the contention tables is in
`contention-requests.jsonl` and `limiter-cache-requests.jsonl`, every call of the outage drill in
`outage-events.jsonl`, and every call of the database drill in `database-events.jsonl`. The drills ran on the
evening of 3 November in Toronto, which was 4 November in UTC, the date their files carry.

### The fake provider

`capacity/fake_provider.py` stands in for the managed model behind `larkspur-chat`. It keeps a quota of tokens a
minute over a sliding 60-second window and treats a request the way section 4 of the fact sheet describes Bedrock's
and Azure's quotas. It reserves the prompt's tokens, counted at four characters a token as LiteLLM counts them, plus
the request's `max_tokens`, or 4,096 when the request sets none. Once the answer is written it replaces the
reservation with the tokens used, output times a burndown of 1. A reservation that doesn't fit gets 429 with
`Retry-After` in whole seconds, `retry-after-ms`, and Azure's `x-ratelimit-limit-tokens` and
`x-ratelimit-remaining-tokens`; the wait it gives is the time until enough of the window has expired for the request
to fit. In the drills it answers after 50 ms plus 1 ms for each output token. `POST /control` makes it answer 503 at
once, or hold a request for 30 seconds and then answer 504; a connection error is the process stopped, so that its
port refuses. A request with tools gets chapter 5's rule model, as chapter 5's fake backend answers it, so the loops
of chapters 1 and 12 run through the gateway against it. The window's shape sets the waits below: a provider that
enforces its minute over shorter intervals, as Azure says it typically does over one or ten seconds, would ask for
shorter ones.

### Contention under three limits

The contention drill runs on step 4's gateway, its config and keys unchanged, with the fake provider as the
primary behind `larkspur-chat` and a quota of 100,000 tokens a minute. W3 sends an incident's call every six seconds
and W2 a question every three, each the ledger's tokens per call on the managed alias (W3's 1,602 in and 99 out,
W2's 964 and 152), with a `max_tokens` of 256 that chapter 5's harness doesn't set. From 15 to 75 seconds W2
bursts: eight workers send questions that each pull a long log into the prompt, 6,000 tokens in, a `max_tokens` of
2,000 and 1,000 back, each sending the next as soon as the last ends. Every call honors Retry-After (retries,
below). Who gets a slot when the provider's window frees one is a race, so each limit ran three times, the rounds
interleaved, each on a fresh proxy and a fresh quota. The per-key limit ran twice over: W2's key at 75,000 tokens a
minute and W3's at 25,000, dividing the quota exactly, and then W2's share halved, so that a burst at the end of one
of the limiter's minutes and another at the start of the next would still fit beside W3. W3's requests made during
the burst:

|Limit|Round|Requests|Served|On the first attempt|Attempts a request|Median wait (s)|Longest wait (s)|What refused W3's attempts|
|---|---|---|---|---|---|---|---|---|
|requests per minute alone|1|10|10|2|3.7|18.7|48.2|the provider's quota 27|
|requests per minute alone|2|10|7|2|4.4|9.38|45.5|the provider's quota 37|
|requests per minute alone|3|10|10|3|3.8|20.3|51.3|the provider's quota 28|
|tokens per minute per key|1|10|10|10|1|0.163|0.18||
|tokens per minute per key|2|10|10|10|1|0.161|0.174||
|tokens per minute per key|3|10|10|10|1|0.166|0.178||
|tokens per minute per key, with headroom|1|10|10|10|1|0.168|0.18||
|tokens per minute per key, with headroom|2|10|10|10|1|0.16|0.163||
|tokens per minute per key, with headroom|3|10|10|10|1|0.16|0.177||
|deployment limits|1|10|8|2|4.2|18|45.5|the deployment's parallel requests 6, the provider's quota 28|
|deployment limits|2|10|3|1|4.8|0.432|3.61|the deployment's parallel requests 2, the provider's quota 43|
|deployment limits|3|10|4|2|4.6|0.357|45.9|the deployment's parallel requests 2, the provider's quota 40|

Under chapter 5's request rate alone, W2's burst took the provider's quota with few requests: 12 to 20 in its
minute, each reserving 8,000 tokens, well inside W2's 120 requests a minute. The provider refused W3 27 to 37 times
in each round's burst. Only 2 or 3 of W3's 10 requests went through on the first attempt, the median request waited
9.38 to 20.3 s and the longest 45.5 to 51.3 s, and in the second round 3 of the 10 were never served. Limits on the
deployment did no better: 3 to 8 of W3's 10 requests were served, and the provider still refused W3 28 to 43 times.
The deployment's `tpm` and `rpm` refused nothing in any round. Set at the provider's own quota, the `tpm` counts a
call's tokens once the call is answered, while the provider reserves a call's prompt and `max_tokens` when it
arrives, so the provider refused first every time. The cap of four calls at once did refuse, W3's calls as readily
as W2's, since a deployment's limits are shared by every workflow that calls it.

|Limit|Round|W2's burst requests|Served|W2's questions served|W3 served, whole run|Provider refusals, W2|Provider refusals, W3|What refused W2's burst|
|---|---|---|---|---|---|---|---|---|
|requests per minute alone|1|12|10|9 of 19|25 of 25|91|27|the provider's quota 18|
|requests per minute alone|2|20|19|11 of 20|22 of 25|92|37|the provider's quota 17|
|requests per minute alone|3|20|18|9 of 20|25 of 25|91|28|the provider's quota 18|
|tokens per minute per key|1|149|17|7 of 21|25 of 25|0|0|chapter 5's requests per minute 191, the key's tokens per minute 105|
|tokens per minute per key|2|136|10|6 of 19|25 of 25|1|6|chapter 5's requests per minute 169, the key's tokens per minute 105|
|tokens per minute per key|3|142|9|5 of 19|25 of 25|0|0|chapter 5's requests per minute 201, the key's tokens per minute 105|
|tokens per minute per key, with headroom|1|139|8|5 of 19|25 of 25|0|0|chapter 5's requests per minute 184, the key's tokens per minute 106|
|tokens per minute per key, with headroom|2|154|14|4 of 20|25 of 25|12|9|chapter 5's requests per minute 209, the key's tokens per minute 111|
|tokens per minute per key, with headroom|3|141|9|4 of 19|25 of 25|0|3|chapter 5's requests per minute 192, the key's tokens per minute 106|
|deployment limits|1|18|16|11 of 20|23 of 25|100|36|chapter 5's requests per minute 12, the deployment's parallel requests 4, the provider's quota 14|
|deployment limits|2|17|14|12 of 20|18 of 25|83|43|chapter 5's requests per minute 3, the deployment's parallel requests 8, the provider's quota 19|
|deployment limits|3|17|15|9 of 19|19 of 25|81|40|chapter 5's requests per minute 10, the deployment's parallel requests 2, the provider's quota 15|

With a `tpm_limit` on each key, every one of W3's requests in the burst was served on its first attempt, within 0.18
s, in all six rounds, and for most of the burst W2 was held back by its own spent request rate. In the burst's first
second the key let through W2's share of the first requests, nine at 75,000 tokens a minute and three or four at
37,500, and refused the next 105 to 112, each with `retry-after: 60`, a wait the burst's retry policy, with a
minute's patience, gave up on at once. Every refusal also counted against chapter 5's 120 requests a minute, so W2's
rate was spent by 17 s, and chapter 5's limit refused nearly all W2 sent until those requests left its window at 75
s, its questions as well as its burst: W2 got 4 to 7 of its 19 to 21 questions answered during the burst, against 9
to 11 under the request rate alone.

After the burst the provider refused W3 again, in one round of the exact division and two of the headroom rounds,
6, 9 and 3 times between 96 and 121 s. As chapter 5's window let W2 through at 75 s, the burst's last requests,
retrying, went through W2's key together: the burst was served 49,000 to 70,000 tokens between 60 and 120 s in the
headroom rounds, against W2's share of 37,500 a minute, and with W2's questions and W3's own calls they held the
provider's window at its quota for the next minute. The key refused none of them, because by then it kept no count.
Each per-key limit ran once more with `capacity/census_hooks.py`, a callback that writes, at every call, what the
proxy holds in the cache its rate limiter counts in, on step 4's gateway (`litellm.census.yaml`) and on the same
gateway without step 4's budget alerts (`litellm.census-no-alerts.yaml`):

|Gateway|Limit|Most entries|Full at (s)|What it held then|W2's window evicted at (s)|The key's refusals of W2, the last at (s)|W2's burst tokens served from 60 to 120 s|W3 in the burst, served and on the first attempt|Provider refusals, W3|
|---|---|---|---|---|---|---|---|---|---|
|step 4's|tokens per minute per key|200 of 200|30.5|request_status 192, {api_key}:requests 2, {api_key}:tokens 2|30.8|105, 16.8|70,000|10 of 10, 10|12|
|step 4's|tokens per minute per key, with headroom|200 of 200|31.1|request_status 192, {api_key}:requests 2, {api_key}:tokens 2|31.6|111, 15.8|56,000|10 of 10, 10|0|
|step 4's without alerts|tokens per minute per key|8 of 200||{api_key}:requests 2, {api_key}:tokens 2, {api_key}:window 2||109, 117|56,000|10 of 10, 10|0|
|step 4's without alerts|tokens per minute per key, with headroom|8 of 200||{api_key}:requests 2, {api_key}:tokens 2, {api_key}:window 2||123, 117|21,000|10 of 10, 10|0|

Without Redis, LiteLLM keeps each key's window and counters in the proxy's internal usage cache, in memory, which
holds 200 entries and, when it is full, drops the entries nearest their expiry
(`litellm/caching/in_memory_cache.py`). Step 4's budget alerts, `alerting: ["webhook"]`, also make the proxy keep
there a status for every request, refused ones included, for the alerting threshold plus 100 seconds, 400 by default
(`ProxyLogging.update_request_status`, there for Slack's hanging-request alerts). On step 4's gateway the burst's
refusals filled the cache 30.5 and 31.1 s into the round, request statuses in 192 of its 200 entries, and from then
on each new status pushed out the entries nearest their expiry, the keys' sixty-second windows and counters first:
W2's window went at 30.8 and 31.6 s, and every reservation after it found an empty counter, so the key refused
nothing more. Without the alerts the cache never held more than eight entries, the two keys' windows and counters,
and the windows lived out their minutes: W2's key went on refusing into its second minute, the last time at 117 s,
and in the headroom round the burst got 21,000 tokens between 60 and 120 s, inside its share. The provider refused
W3 nothing in either round without the alerts, and 12 times after the burst in the exact division with them. So on
step 4's gateway a key's tokens-per-minute limit holds only while the cache keeps its window, half a minute into
this burst. Taking `alerting` off the proxy kept the window for the whole round; Redis behind the limiter might too,
and no drill tried it. Without the alerts each limit ran once.

### Retries

`capacity/retry.py` holds two policies. The one named `honour` follows the clouds' advice in section 4 of the fact
sheet: it retries a 429, a 503 or a 529 and nothing else; it waits what the answer asks, `retry-after-ms` first,
then `Retry-After`, then the same two under LiteLLM's prefix `llm_provider-`, plus up to a second of jitter; with no
wait given it backs off as the AWS SDKs do, from one second to a cap of twenty with full jitter; and it stops after
six attempts or a minute after the first. The naive one retries any failure at once, up to twenty attempts. A minute
of W2's requests, one every 0.75 seconds with 1,500 tokens reserved each, met a fresh quota of 60,000 tokens a
minute, which admits the first forty and throttles the rest of the minute:

|Through|Policy|Requests|Served|Calls|Calls a success|Calls in the minute|Calls over requests, in the minute|Refused by|
|---|---|---|---|---|---|---|---|---|
|the provider directly|none|80|46|80|1.74|80|1|the provider's quota 34|
|the provider directly|honour|80|56|238|4.25|80|1|the provider's quota 182|
|the provider directly|naive|80|46|726|15.8|726|9.07|the provider's quota 680|
|step 4's gateway|honour|80|75|222|2.96|80|1|chapter 5's requests per minute 72, the provider's quota 75|
|step 4's gateway|naive|80|46|726|15.8|726|9.07|chapter 5's requests per minute 606, the provider's quota 74|

Sent to the provider directly, the naive client made 726 calls, 9.07 times the minute's requests, and served 46 of
80, as many as sending each request once did: every extra call landed while the window was full. Honoring the wait
kept the minute's calls to its requests and served 56, since the waits ran into the next minute, when the window had
room again. It still made 4.25 calls a success. Every refused request was told the same wait, the time until the
window's oldest charge expired, and they all came back within a second of it, where one or two fit and the rest
were told to wait again, until six attempts or the minute's patience ran out.

Through step 4's gateway the honoring client found the provider's wait under `llm_provider-retry-after` and served
75 of 80 at 2.96 calls a success. Chapter 5's limit of 120 requests a minute refused 72 of its retries, with no wait
in the answer, so those requests backed off on the SDKs' schedule and came back spread out. The naive client made
the same 726 calls, and the same limit refused 606 of them at the gateway: 120 reached the provider in the throttled
minute, one and a half times the minute's requests. Only the manifest's request rate stood between a naive harness
and the provider, and the naive harness spent all of it on retries.

LiteLLM's router retrying on its own, with `num_retries: 2` and the first deployment throttled
(`capacity/litellm.retry.yaml`):

|Case|Attempts|Gaps between attempts (s)|Served by|Status|
|---|---|---|---|---|
|one deployment in the group, Retry-After 5 s|t1 429, t1 429, t1 200|5.11, 5.49|t1-single|200|
|one deployment in the group, Retry-After 90 s|t1 429, t1 429, t1 200|0.815, 1.48|t1-single|200|
|two deployments in the group, the first throttled, Retry-After 5 s|t1 429, t2 200|0.013|t2-pair|200|

Alone in its group, the deployment's Retry-After of 5 s was honored, with up to 0.75 s of jitter: the router waited
5.11 and 5.49 s. A Retry-After of 90 s, past the router's limit of 60, was ignored, and it backed off 0.815 and 1.48
s. With a second deployment healthy in the group, it retried on that one at once, 0.013 s after the 429, whatever
the first had asked. A gateway with several deployments behind an alias spreads a throttled provider's load at once,
and a gateway with one, like chapter 5's, waits as the provider asks, up to a minute. LiteLLM's own limits answer
with their own waits: a key's tokens per minute and a deployment's limits ask for 60 s whatever their window holds,
and a cooled-down group for its whole `cooldown_time`, however much of it is left.

### The gateway's own latency

Each setup sends W2's call one at a time, sixty after three to warm the caches, unless it says otherwise, and each
call is matched to the provider's own record of it by its id. The client's time less the provider's is what the
gateway adds, beside the client's and the provider's own overhead, which the first row measures with no gateway at
all. Both clocks are the performance counter: Python 3.12's `time.time()` on Windows is `GetSystemTimeAsFileTime`,
which moved in steps of about a millisecond on this workstation. Each gateway setup starts on a fresh proxy, and in
the last two the key's `tpm_limit` is ten million tokens a minute, so the limiter reserves and settles every call and
refuses none:

|Setup|Calls|At once|Client, median (ms)|Provider, median (ms)|Client less provider, median (ms)|Client less provider, 95th percentile (ms)|LiteLLM's own figure, median (ms)|
|---|---|---|---|---|---|---|---|
|the provider alone, no gateway|60|1|206|205|0.973|1.2||
|chapter 5's gateway, no database|60|1|207|197|9.82|11.6|2.56|
|chapter 5's gateway, the provider answering in 50 ms|60|1|62.1|52.5|9.55|11.1|3.35|
|step 4's gateway, W2's virtual key|60|1|207|193|13.3|18.5|6.81|
|step 4's gateway, W2's key with a tpm_limit|60|1|206|195|11.5|13.6|0|
|step 4's gateway, W2's key with a tpm_limit, 8 at once|96|8|236|196|38.9|49|25.9|

With no gateway, the client's and the provider's own handling come to 0.973 ms a call. Chapter 5's gateway adds
about 9 ms to that, 9.82 ms at the median against a provider taking 197 ms, and the same 9.55 ms when the provider
answers in 50 ms: the gateway's time doesn't grow with the model's. Step 4's gateway, with the key's checks and the
spend tracking of its database, took 13.3 ms, and 11.5 ms with a `tpm_limit` on the key, which reserves and settles
every call, so the limiter's own work was too small for this drill to see. Eight calls at once took 38.9 ms at the
median and 49 ms at the 95th percentile, since one proxy process does the work of all eight. LiteLLM's own
`x-litellm-overhead-duration-ms` reported less than the client saw in every setup, and 0 for more than half the
calls with a `tpm_limit`, so the header doesn't measure the gateway's cost. Beside a model call of a few hundred
milliseconds, the gateway's own time is a few percent.

### The outage drill

`capacity/litellm.outage.yaml` is chapter 5's three aliases and its callback, unchanged, with the fallback one hop
from the primary in ca-central-1 to the deployment in us-east-2, `num_retries: 0`, and the router's cooldown written
out: `allowed_fails: 2`, since LiteLLM 1.106.6 treats an explicit 3 as unset, and `cooldown_time: 30`. Each failure
mode starts on a fresh proxy: ten healthy seconds, a minute of failure, fifty seconds after the primary heals. W2
calls once a second and W3 once every two throughout, each sending its next call when the last is answered. Two runs
are in flight when the failure starts, each between its first and second model call: W2's question through chapter
1's loop and chapter 5's `GatewayModel`, and W3's triage through W3's own `run_steps` and `W3GatewayModel`. A third,
W3's, starts twenty seconds in. The gateway's own lines time the cooldown, since a provider that refuses
connections can't log what reached it. Times are seconds from the moment the failure took effect:

|Mode|First cycle|Cooldown first answered (s)|Second cycle|Healed at (s)|Primary serving again after the heal (s)|
|---|---|---|---|---|---|
|5xx|3 failures, 0.223 to 0.542|1.48|3 failures, 30.8 to 31.8|60|2.15|
|timeout|4 failures, 5.23 to 6.76|6.78|4 failures, 41.1 to 46.9|60|16.6|
|connection|4 failures, 2.29 to 3.88|3.89|4 failures, 35.3 to 38.1|60|7.76|

In every mode the router did what fact sheet 8.1 reads in its code once `allowed_fails` is set: it cooled the
primary down for thirty seconds at the failure that took its count past two, then let live calls find it again and
cooled it down after the same count. The table's times are the gateway's failure lines, written when a call failed.
5xx errors cost nothing but the calls, and the third came 0.542 s in. A timeout held each call the deployment's five
seconds, so the router heard of the first failures five seconds in and cooled the primary down 5.8 s in; every call
sent to it before then waited five seconds before the fallback answered. A refused connection took about two seconds
on this workstation, where Windows tries a refused loopback connection again before it reports one, and the cooldown
came 2.91 s in. In those two modes a fourth call, sent before the third failed, failed after it. A primary that came
back served again only when the cooldown in force ran out: 2.15, 16.6 and 7.76 s after it healed.

|Mode|W2's calls|W2's answers|Served by|W2's latency, median / longest (s)|W3's calls|W3's answers|W3's refusals|
|---|---|---|---|---|---|---|---|
|5xx|59|200 59|fallback 59|0.0822 / 0.104|30|429 29, 503 1|status 503 1, the router's cooldown 29|
|timeout|47|200 47|fallback 47|0.0816 / 5.1|25|408 3, 429 22|status 408 3, the router's cooldown 22|
|connection|56|200 56|fallback 56|0.0856 / 2.13|29|429 26, 500 3|status 500 3, the router's cooldown 26|

W2 got an answer to every call, from the fallback in us-east-2 while the primary failed: one of its manifest's two
Regions. W3 got no answer while the primary failed. Those of its calls that reached the failing primary, one in the
5xx mode and three in each of the others, got its error, 503, 408 or 500, and every other call LiteLLM's 429, "No
deployments available for selected model, Try again in 30 seconds", with `retry-after: 30`: once the router has
cooled down a group's only deployment, a request whose fallback is off never reaches it. Chapter 5's rule that W3's
Confidential calls get the primary's 503 holds for the first calls of an outage; for the rest of it W3 gets a 429.

|Mode|W2's run|W3's run|W3's run during the cooldown|
|---|---|---|---|
|5xx|answered; calls served by primary in ca-central-1, then fallback in us-east-2|unavailable (model unavailable) after 2 model calls|raised HTTPStatusError 429 after 1 model call|
|timeout|answered; calls served by primary in ca-central-1, then fallback in us-east-2|raised HTTPStatusError 408 after 2 model calls|raised HTTPStatusError 429 after 1 model call|
|connection|answered; calls served by primary in ca-central-1, then fallback in us-east-2|unavailable (model unavailable) after 2 model calls|raised HTTPStatusError 429 after 1 model call|

W2's run answered in every mode, its second call failing on the primary and served by the fallback in us-east-2,
after 0.388, 5.16 and 2.22 s. `W3GatewayModel` takes a 5xx for an outage, so for the 5xx error and the refused
connection it returned "model unavailable" and W3's `run_steps` ended the triage with W3's sentence, before any
write. It takes a 4xx for the gateway refusing the call, a fault to surface, so the timeout's 408 and the cooldown's
429 raised out of the triage, which leaves the run in its store at triaging for a restarted harness to pick up from
the trigger. The run started inside the cooldown raised on its first call in every mode. Neither path writes, and
the 429's case is a finding for W3's follow-ups (#10): for most of an outage the incident workflow raises where it
was meant to say the model is unavailable.

|Mode|W2's calls by Region|W3's calls by Region|W3's failed lines with fallback disabled|W2's cooldown failures logged as the fallback|
|---|---|---|---|---|
|5xx|ca-central-1 50, us-east-2 62|ca-central-1 26|33 of 33|58|
|timeout|ca-central-1 36, us-east-2 64|ca-central-1 19|35 of 35|60|
|connection|ca-central-1 45, us-east-2 64|ca-central-1 24|35 of 35|60|

Every one of W3's failed lines records that its fallback was disabled, and none of its calls was served outside
ca-central-1. Chapter 5's cost log has one wrong field: while the primary is cooled down, each of W2's calls leaves
a `failed` line for the router's 429 that names the fallback deployment and us-east-2, beside the `call` line of the
fallback that answered it, 58 to 60 such lines a mode. A count of failures by deployment from that log puts the
primary's outage on the fallback.

### The database stopped

Step 4's gateway with W2's key: one call a second, each sent whatever happened to the last, and PostgreSQL stopped
ten seconds in and started again ninety seconds later. Times are seconds from the stop, and from the start for the
calls after it:

|Stopped for (s)|Calls sent while down|Answered from the key cache|The cache answered until (s)|Refused|A refusal held its caller, median / longest (s)|Answered after waiting for it|First answered call after the restart, sent at (s)|After the restart|Spend counted over the answered calls' cost|
|---|---|---|---|---|---|---|---|---|---|
|90.1|91|51|50.1|503 31|14.6 / 18.8|9|0.862|200 59|0.543|

The proxy kept answering for 50.1 s after PostgreSQL stopped, 51 calls, from the key it had cached. From the next
call on it refused every one with 503, "Service Unavailable, the authentication database is temporarily unreachable.
Please retry shortly.", each after 14.6 s at the median and 18.8 s at the longest. Nine calls sent while it was down
waited and were answered once it was back. The first call sent 0.862 s after PostgreSQL started was answered, and
every call after it. The key's spend counter gained 0.543 of what the answered calls cost, less than the share
answered outside the outage: the spend of the calls answered while the database was down never reached it, nor part
of what LiteLLM's batch writer held when it stopped. Step 4's budgets are enforced against that counter, so each
outage of the database leaves some spend outside the budgets.

### The repeated write

A run lost in a failover fails and is started again, and the second run must not repeat a write the first one made.
`capacity/repeat_write.py` drives W3's own approval service behind its HTTP layer on 127.0.0.1, W3's `Writer` over a
fresh cluster state, and W3's `Harness` over a fresh store, with a scripted model; the membership table and the
approver's token come from W3's test fixtures, and nothing in W3 changes. Run A triages `claims-api`, proposes the
restart, gets a person's yes and writes, and its pod is lost before the harness records the result. Then:

|Case|Presented|Write ran|Generation|Stopped by|Reason|
|---|---|---|---|---|---|
|run A writes under its approval, and its pod is lost before it records the result|run A's approval|yes|1 to 2||the process died after the write|
|run A resumed by a new harness process, its store intact|run A's approval, reserved in run A's store|no|2 to 2|W3's store|the write is marked started; the run ended done after verifying|
|run B presents run A's approval|run A's approval, under run B's trace id|no|2 to 2|the approval service|the approval is for another run|
|run A's approval presented again, by a harness that lost run A's store|run A's approval, under run A's trace id|no|2 to 2|the approval service|already applied|
|run B presents its own approval before anyone has decided|run B's approval, pending|no|2 to 2|the approval service|the approval is pending|
|a person approves run B's own request|run B's approval, approved|yes|2 to 3||a second restart, decided by a person; the run ended done|

Three things stop the second write, all of them W3's. The run's store reserves a write before it runs, so the same
run resumed by a new process finds the reservation, verifies and ends done (W3-D4). The approval service binds a yes
to one call in one run and applies it once: run B presenting run A's approval gets "the approval is for another
run", and a harness that lost run A's store presenting it again under run A's trace id gets "already applied". And a
new run files its own request, which writes nothing until a person approves it. The second restart did happen, after
a person approved run B's request. The approval's number does the idempotency key's job, as chapter 12 says, and it
belongs to one run.

### The provisioned calculator

`capacity/calculator.py` answers O-D9 in the manner of chapter 9's crossover. Committed capacity is bought in units
and paid for every hour of its term; a workflow sizes it for its busy hour and fills it, on average, for its duty
cycle. The commitment costs less than paying per token exactly when the share of its capacity the workflow fills
over the term, u, passes the break-even u*: the commitment's price for an hour over the on-demand price of a full
hour of the same capacity. The prices come from the dated table, where step 2 put every committed price of section
8.8; section 8.8 holds none the table lacks, so this step adds none. `units.yaml` adds what isn't a price, in the
fact sheet's words: the Reserved tier, sold per 1,000 tokens a minute, input and output apart, at least 100,000 and
10,000; Azure's normalized tokens a minute, 1,200 a PTU for gpt-5.5 with output counted six times, regional
deployments from 50 PTUs in steps of 50; a GSU, 675 tokens a second for Gemini 3.6 Flash with output counted five
times; and Nova Lite's model units, whose size the fact sheet doesn't give. `busy_hour.yaml` states the busy hours,
since the book gives none: W2's 200 questions, twice "the hundred questions an hour" of ch12:18, and W3's ten
incidents, a day's in one hour. Tokens per run come from the ledger, less W3's Restricted calls, which go to the
self-hosted alias and never to a commitment. The duty cycle is the month's runs over the runs the month would hold if
every hour were the busy hour:

|Workflow|Busy hour (runs)|Runs a month|Input tokens a minute|Output tokens a minute|Duty cycle|
|---|---|---|---|---|---|
|w2-ops-assistant|200|43,030|6,692|1,054|0.295|
|w3-incident|10|300|1,480|91.3|0.0411|

|Workflow|Product|Term|Units the busy hour needs|Units bought|Busy hour fills|Utilization u|Discount needed (1 - u)|Break-even u*|Busy hours to break even|Month over per_month_usd|
|---|---|---|---|---|---|---|---|---|---|---|
|w2-ops-assistant|bedrock-reserved-sonnet-4.5-cac1|1 month|9|110|10.5%|3.11%|96.9%|||108|
|w2-ops-assistant|bedrock-reserved-sonnet-4.5-cac1|3 months|9|110|10.5%|3.11%|96.9%|||97.6|
|w2-ops-assistant|bedrock-pt-nova-lite-use1|no commitment||1|||||1,541|221|
|w2-ops-assistant|bedrock-pt-nova-lite-use1|1 month||1|||||1,401|201|
|w2-ops-assistant|bedrock-pt-nova-lite-use1|6 months||1|||||770|110|
|w2-ops-assistant|azure-ptu-gpt-5.5-regional-canadaeast|hourly|11|50|21.7%|6.39%|93.6%|||431|
|w2-ops-assistant|azure-ptu-gpt-5.5-regional-canadaeast|1-month reservation|11|50|21.7%|6.39%|93.6%|||84.5|
|w2-ops-assistant|azure-ptu-gpt-5.5-regional-canadaeast|1-year reservation|11|50|21.7%|6.39%|93.6%|||71.8|
|w2-ops-assistant|google-gsu-gemini-3.6-flash|1 week, non-global|1|1|29.5%|8.71%|91.3%|||28.7|
|w2-ops-assistant|google-gsu-gemini-3.6-flash|1 month, non-global|1|1|29.5%|8.71%|91.3%|||14.8|
|w2-ops-assistant|google-gsu-gemini-3.6-flash|3 months, non-global|1|1|29.5%|8.71%|91.3%|||13.2|
|w2-ops-assistant|google-gsu-gemini-3.6-flash|1 year, non-global|1|1|29.5%|8.71%|91.3%|||11|
|w2-ops-assistant|google-gsu-gemini-3.6-flash|1 week, global|1|1|29.5%|8.71%|91.3%|||26.1|
|w2-ops-assistant|google-gsu-gemini-3.6-flash|1 month, global|1|1|29.5%|8.71%|91.3%|||13.5|
|w2-ops-assistant|google-gsu-gemini-3.6-flash|3 months, global|1|1|29.5%|8.71%|91.3%|||12|
|w2-ops-assistant|google-gsu-gemini-3.6-flash|1 year, global|1|1|29.5%|8.71%|91.3%|||10|
|w3-incident|bedrock-reserved-sonnet-4.5-cac1|1 month|3|110|1.48%|0.0608%|99.9%|||43.4|
|w3-incident|bedrock-reserved-sonnet-4.5-cac1|3 months|3|110|1.48%|0.0608%|99.9%|||39|
|w3-incident|bedrock-pt-nova-lite-use1|no commitment||1|||||9,109|88.3|
|w3-incident|bedrock-pt-nova-lite-use1|1 month||1|||||8,281|80.3|
|w3-incident|bedrock-pt-nova-lite-use1|6 months||1|||||4,554|44.2|
|w3-incident|azure-ptu-gpt-5.5-regional-canadaeast|hourly|2|50|3.38%|0.139%|99.9%|||172|
|w3-incident|azure-ptu-gpt-5.5-regional-canadaeast|1-month reservation|2|50|3.38%|0.139%|99.9%|||33.8|
|w3-incident|azure-ptu-gpt-5.5-regional-canadaeast|1-year reservation|2|50|3.38%|0.139%|99.9%|||28.7|
|w3-incident|google-gsu-gemini-3.6-flash|1 week, non-global|1|1|4.78%|0.196%|99.8%|||11.5|
|w3-incident|google-gsu-gemini-3.6-flash|1 month, non-global|1|1|4.78%|0.196%|99.8%|||5.94|
|w3-incident|google-gsu-gemini-3.6-flash|3 months, non-global|1|1|4.78%|0.196%|99.8%|||5.28|
|w3-incident|google-gsu-gemini-3.6-flash|1 year, non-global|1|1|4.78%|0.196%|99.8%|||4.4|
|w3-incident|google-gsu-gemini-3.6-flash|1 week, global|1|1|4.78%|0.196%|99.8%|||10.4|
|w3-incident|google-gsu-gemini-3.6-flash|1 month, global|1|1|4.78%|0.196%|99.8%|||5.4|
|w3-incident|google-gsu-gemini-3.6-flash|3 months, global|1|1|4.78%|0.196%|99.8%|||4.8|
|w3-incident|google-gsu-gemini-3.6-flash|1 year, global|1|1|4.78%|0.196%|99.8%|||4|

u* needs the on-demand rate of the same model in the same place. The table holds one only for Nova Lite, in
us-east-2, which stands in for us-east-1, and section 8.8 quotes none for Claude Sonnet 4.5 through the Canadian
profile, gpt-5.5 Regional or Gemini 3.6 Flash, and no tokens per model unit for Nova Lite:

|Product|Lacks|
|---|---|
|bedrock-reserved-sonnet-4.5-cac1|the on-demand rate (section 8.8 quotes no on-demand rate for Claude Sonnet 4.5 through the Canadian profile, and the offer file it cites for the Reserved tier holds only the Reserved rows)|
|bedrock-pt-nova-lite-use1|the tokens a minute one unit carries, which the fact sheet doesn't give|
|azure-ptu-gpt-5.5-regional-canadaeast|the on-demand rate (section 8.8 quotes no on-demand rate for gpt-5.5, and the table's Azure rate is gpt-4o's, whose tokens per PTU the fact sheet doesn't give)|
|google-gsu-gemini-3.6-flash|the on-demand rate (section 8.8 quotes no Gemini token rate, and the table's Gemini entry is null for the same reason)|

So the break-even is missing for all four, and `--on-demand-input` and `--on-demand-output` take the rate when there
is one. The calculator answers with what needs no rate. For the commitment to cost no more than paying per token,
its full-use price has to be below u times the on-demand rate, a discount of 1 - u. W2's month would fill 3.11
percent of the smallest Reserved purchase, 6.39 percent of Azure's 50 PTUs and 8.71 percent of one GSU, so each would
have to sell its capacity at least 91 percent below the on-demand rate; W3's would fill 0.0608, 0.139 and 0.196
percent, a discount above 99.8 percent. A Nova Lite model unit for six months costs as much an hour as 770 of W2's
busy hours of tokens and 4,554 of W3's, whatever its size. The smallest commitments cost 10 to 431 times W2's monthly
budget. Committed capacity would pay off only at many times W2's volume. The chapter weighs that against Larkspur's
bursty traffic and against the grid: Nova Lite's units are in us-east-1, which neither manifest allows and the
Canadian profile can't reach, and the GSU's global endpoint offers no data residency.

|Workflow|Input tokens|Output tokens|Replica-seconds|Share of one replica-hour|Share of the two-replica floor|
|---|---|---|---|---|---|
|w2-ops-assistant|0|0|0|0%|0%|
|w3-incident|8,226|1,243|8.34|0.232%|0.116%|

W3's busy hour sends 8,226 input and 1,243 output tokens to the self-hosted path, 8.34 seconds of one replica at
chapter 9's single-stream speeds, 0.232 percent of the hour of one of the two replicas chapter 9 keeps for
availability.

### Continuity

`capacity/continuity.yaml` gives each component the plan names its failure mode, the recovery objective the lab
proposes, the evidence and the gap. The book sets no recovery objective, and none of the three clouds publishes one
for a model endpoint or an agent service (fact sheet section 5), so each objective is a proposal for the chapter,
sized by what the drills measured; a test finds every number the evidence cites in its drill's JSON:

|Component|Failure mode|Recovery objective|Evidence|Gap|
|---|---|---|---|---|
|the gateway|A model behind it fails, with 5xx errors, timeouts or refused connections; or the proxy itself stops, and every call in flight with it.|A failing model off the path within three failures, seconds, or the timeout and a little more when it hangs; back on it within one cooldown of healing, thirty seconds; the proxy back within a minute of a restart. RPO none: it holds nothing a call needs beyond its database.|Outage drill, with allowed_fails 2 and cooldown_time 30: the router cooled the primary down at its third failure, 0.542 s into a 5xx outage, 5.8 s into timeouts, each of which held its call five seconds, and 2.91 s into refused connections, each of which took about two; in those two modes a fourth call, already in flight, failed after it. The primary served again 2.15, 16.6 and 7.76 s after it healed, as the cooldown in force ran out. W2's every call was answered, by the fallback in us-east-2 while the primary failed; W3 got the primary's error and then the cooldown's 429. Step 4's proxy came back from a restart in 20.4 s with its database.|One Region: the second gateway Region of month five isn't deployed (O-D17). A proxy killed with calls in flight, and a fleet of proxies behind a load balancer, weren't drilled.|
|its database|PostgreSQL unreachable. The keys, the monthly budgets, the key block and the spend counter all live in it.|Back inside the time the proxy answers from its key cache, under a minute, so that a failover refuses no caller. RPO for spend none, which needs what the proxy drops put back from chapter 5's cost lines.|Database drill, PostgreSQL stopped for 90.1 s under step 4's gateway, W2 calling once a second: the proxy answered 51 calls from its key cache until 50.1 s, then refused 31 with 503, "the authentication database is temporarily unreachable", each refusal holding its caller 14.6 s at the median. The first call sent 0.862 s after PostgreSQL started again was answered. The key's spend counter gained 0.543 of the answered calls' cost, less than the share answered outside the outage.|A managed database's failover wasn't drilled, nor a proxy started while its database is down. Nothing in the lab puts the lost spend back from the cost lines yet, so after an outage each budget is enforced against less than was spent.|
|Redis|Redis down: LiteLLM keeps the keys' windows, the spend reservations and the cooldown counts in each worker's memory instead.|None of its own, since nothing in it needs restoring; the shared counts come back with it. Until then each of n workers allows its own share, n times every limit, and a worker's key limits hold only while its in-memory cache keeps their windows.|Fact sheet 8.1 quotes LiteLLM's docs on what a worker without Redis does with spend. LiteLLM 1.106.6's cooldown counter falls back to "this worker's in-memory count" on a Redis error (router_utils/cooldown_handlers.py). This step ran one proxy process and no Redis, so every count in its drills was one worker's, and the keys' windows sat in that worker's cache of 200 entries. On step 4's gateway, whose budget alerts keep a status there for every request, the limiter-cache drill found the cache full 30.5 s into a burst and W2's window evicted at 30.8 s; without the alerts the cache held 8 entries all round and the window lived out its minute.|No Redis runs on this workstation, and no drill stopped one, or showed whether Redis keeps a key's window through a burst of refusals.|
|Langfuse|Langfuse down or its stores lost: the trace store the observability team reads. The Collector's export to it fails while the span file and CloudWatch, in pipelines of their own, carry on.|Hours, restored from a backup of its four stores. Traces are sampled already, and neither the audit record nor the cost lines pass through it (O-D3), so nothing a budget or an audit needs is lost with it.|Fact sheet 8.5 quotes Langfuse's own guide on its Compose setup, which step 7 runs on one VM. Step 3's Collector exports to the span file, CloudWatch and Langfuse in separate pipelines.|Langfuse didn't run in this step, and what the Collector's exporter keeps while Langfuse is away wasn't measured.|
|the audit log|The approval service's store, Larkspur's one audit trail of approvals, unreachable or lost; or the cloud's own audit log out of reach.|RPO zero for a decided approval, which W3's service commits before it answers (SQLite, synchronous FULL). RTO: no write runs until the service is back, since every write asks it first; reads go on.|The repeated-write check: a write ran only under an approval the service covered, a second run presenting the first run's approval got "the approval is for another run", and the service's log recorded every refusal. CloudTrail's event history, by fact sheet 8.2, keeps the last 90 days of management events in a Region; anything kept longer needs a trail.|The store's loss wasn't drilled, and the lab keeps it in one SQLite file; the immutable store chapter 2 asks for (ch02:170) is the cloud's, and step 7 reads CloudTrail.|
|the self-hosted path|One of chapter 9's two replicas down, or both. Restricted calls have no fallback, since Restricted data never leaves the path.|RTO: a replica rescheduled and its model loaded, minutes, with the other carrying the load meanwhile. RPO none: a replica keeps no state.|W3's busiest hour takes 8.34 s of one replica at chapter 9's measured single-stream speeds, 0.232% of its hour, so one replica carries it. With the path down, W3's harness gets a 5xx and ends the triage "model unavailable" before any write, as the outage drill showed through the managed alias.|The replicas' own failover belongs to chapter 9's lab and wasn't drilled here; chapter 9's speeds are the workstation's RTX 5080 standing in for an L40S.|
|W5's ledger in its fork|The fork's branch lost, or the fork App's commit refused: W5's ledger is one JSON file there, every change a commit.|RPO: the last commit, which git keeps in every clone. RTO: the branch pushed again from a clone; a night is short and idempotent, so a night lost is run again.|W5's ledger says so of itself (workflows/w5-drift/writer/ledger.py): "Deployed, it is a file on a branch of W5's own fork, written by the fork App, so every change to it is a commit", and W5 keeps no store of runs, since a night is idempotent (W5-D2).|Not drilled; restoring a lost fork is untested.|
|the trace pipeline|The Collector down: each process's exporter retries and then drops its spans, and tail sampling loses the traces it was holding in memory to decide.|RTO: a restart. RPO: the traces in the Collector's memory, about 30.7 s of them at the default wait. The cost lines and the audit record never pass through it (O-D3), so cost per run and the approvals survive its loss.|Step 3 measured tail sampling holding each trace 30.7 s at the median before it left. Fact sheet 8.4 quotes the tail sampler's README: every span of a trace must reach one Collector instance, so a second Collector behind a plain load balancer would split traces.|A Collector restart, and what each exporter drops meanwhile, weren't drilled.|

### What the drills can't show

- The provider's window. The fake's quota slides over sixty seconds; Bedrock doesn't say how its per-minute quota
  counts, and Azure says it typically enforces over one or ten seconds. The waits it asks for, and who wins a slot
  the window frees, follow from that shape, so the contention and retry numbers are this fake's.
- A fleet. One proxy process ran each drill, with no Redis, so LiteLLM's key windows, its deployment counters, its
  cooldowns and chapter 5's request rate were that process's alone. LiteLLM counts per worker without Redis (fact
  sheet 8.1), which loosens every limit here by the number of workers, and without Redis the key windows live in
  the 200-entry cache above. This workstation runs no Redis, and no drill ran one, so whether Redis keeps a key's
  window through a burst of refusals is untested.
- The network. Every connection was on loopback. A refused port is what the outage drill could make; a provider that
  stops answering mid-stream, or a partition that leaves connections hanging until the connect timeout, would hold
  each call longer than the two seconds a refusal took here.
- A provider failing in part. The fake failed every call or none; a provider that fails some calls, or answers
  slowly inside the timeout, wasn't drilled.
- What's outside the workstation. No second gateway Region (month five), no managed database's failover, no
  Langfuse, and no Collector restart were drilled; the continuity table gives each its gap.
- The break-even. The calculator lacks the on-demand rates of three products and the size of Nova Lite's model unit,
  so it gives utilization, the discount a commitment would need, and the busy hours it would have to carry, and the
  break-even waits for those inputs.

## The store, the retries and W3's fallback (step 5b)

Step 5's drills called for four fixes, which the author settled on 4 November 2026 (issue #14): the limiter's windows
on a shared store, a 429's Retry-After waited out by every workflow's model client, W3 ending a run it can't wait for
as model unavailable, and a fallback for W3 inside Canada. Step 5b makes them and runs the drills again on this
workstation, against step 5's fakes, quota, loads and rounds, with no model and no cloud call. Every table below is in
`results/2026-11-04/capacity/summary-5b.md`, which `capacity/run_5b.py` writes from `store-probe.json`, `store.json`
and `outage.json`, with step 5's committed numbers beside the new ones where the drills compare. Every request behind
the contention tables is in `store-contention-requests.jsonl` and `store-cache-requests.jsonl`, every request of the
rounds with the store stopped in `store-stopped-requests.jsonl`, and every call of the outage drill in
`outage-events.jsonl`. The drills ran in the early hours of 4 November in Toronto, an hour and five minutes from start
to end.

### The store

LiteLLM keeps a key's window and counters in Redis when it has one, and this workstation runs neither WSL2 nor Docker.
Microsoft's Garnet speaks Redis's protocol and ships Windows builds, and its license is MIT ("Copyright (c) Microsoft
Corporation", the LICENSE file at the tag). `capacity/garnet.py` pins release v2.2.5's `win-x64-based-readytorun.zip`,
26,186,101 bytes, a build for the .NET 10 runtime, which this workstation has (10.0.14). The project publishes no
checksum file beside the release and no build attestation (`gh attestation verify` finds none), so the pin is the
SHA-256 digest GitHub records for the asset and returns from its release API, read again at every fetch;
`garnet-fetch.json` records the check. As with step 4's PostgreSQL, the digest catches a damaged or changed download,
though not a compromised host. Windows reports `GarnetServer.exe` as signed by Microsoft Corporation and timestamped,
and `lua54.dll` and `diskann_garnet.dll` as unsigned. Only the server's own files are unpacked, into
`capacity/garnet/`, which git ignores, and every start checks `GarnetServer.exe` and `lua54.dll` against their copies
in the zip. A store listens on 127.0.0.1 on a port chosen free, with a password made for the run, keeps everything in
memory, and is stopped by its process id.

Step 4's gateway reaches the store as LiteLLM's documentation describes for Redis. Its page "What Needs Redis" asks
for two halves, saying "Configure both": the `router_settings` block, which "covers router state (cooldowns, usage and
latency based routing)", and a block that "covers response caching and everything coordinated proxy-wide". Its page
"Redis and Valkey" gives `general_settings.coordination_redis` for the second half without the response cache, the
Redis for "spend tracking, cross-pod rate limits, pod locks", so no answer is ever served from the store.
`capacity/litellm.store.yaml` is step 4's config with the two blocks and the alert's callback and nothing else, and
`litellm.store-deployment.yaml`, `litellm.store-census.yaml` and `litellm.store-census-no-alerts.yaml` do the same to
step 5's configs. On the store, the keys' windows and counters (`{api_key:<key>}:window` and `:tokens`) and the spend
counters are keys with a TTL each, and the proxy's in-memory cache holds none of them.

### What LiteLLM's limiter needs from the store

LiteLLM 1.106.6's limiter (`proxy/hooks/parallel_request_limiter_v3.py`) counts with eight Lua scripts, so the store
must run Lua and run each script whole: a check-and-increment reads a counter and adds to it, and no other client may
touch the counter in between. Garnet runs Lua when it is enabled, and runs a script whole only in its Lua transaction
mode, which its configuration page describes as "lock keys - run script - unlock keys"; its compatibility page says
that "Garnet being multi-threaded, `MSET` is not atomic". The probe (`run_5b.py --only probe`) ran every step of the
eight scripts once with known inputs, then sent 1,000 check-and-increments at once over 100 connections against a
limit of 250, three times with the transaction mode and three times without:

|Lua transaction mode|Script steps answered as Redis answers|Admitted, each trial|Counter after, each trial|Errors|
|---|---|---|---|---|
|on|18 of 18|250, 250, 250|250, 250, 250|0|
|off|18 of 18|251, 250, 251|250, 250, 250|0|

Every step answered as Redis answers, in both modes. With the transaction mode Garnet admitted exactly 250 each time;
without it, 251 in two of three trials, while the counter read 250, so one admission was never counted. LiteLLM's two
pages on Redis name no feature its limiter needs from the store, and a store that runs Lua without running each script
whole lets a key's limit slip under contention. The lab runs Garnet with the transaction mode on, and no other
candidate was needed.

### Contention on the store

Step 5's contention drill again, its four limits three rounds each, on step 4's gateway with the store, the store
emptied before every round as step 5 started each on a fresh proxy. The summary has every round; beside step 5's,
round by round:

|Limit|Drill|W3 served in the burst|On the first attempt|Longest wait (s)|Provider refusals of W3 after the burst|The key's refusals of W2, 60 to 120 s|W2's burst tokens served, 60 to 120 s|
|---|---|---|---|---|---|---|---|
|requests per minute alone|step 5, no store|27 of 30|7|51.3|0 to 3|0|42,000 to 49,000|
|requests per minute alone|step 5b, the store|28 of 30|6|52.8|3 to 4|0|42,000 to 49,000|
|tokens per minute per key|step 5, no store|30 of 30|30|0.18|0 to 6|0|56,000 to 63,000|
|tokens per minute per key|step 5b, the store|30 of 30|30|0.535|0|5 to 7|56,000|
|tokens per minute per key, with headroom|step 5, no store|30 of 30|30|0.18|0 to 9|0|56,000 to 70,000|
|tokens per minute per key, with headroom|step 5b, the store|30 of 30|30|0.178|0|12 to 19|21,000 to 28,000|
|deployment limits|step 5, no store|15 of 30|5|45.9|0 to 11|0|49,000 to 56,000|
|deployment limits|step 5b, the store|22 of 30|3|54.2|2 to 19|0|56,000|

With the windows in the store, the per-key limits held for the whole round. In every round of both per-key limits W3's
ten requests in the burst were served on the first attempt, as in step 5, and the provider refused W3 nothing after
the burst, where step 5's rounds had up to 6 and 9 such refusals. W2's key went on refusing in its second minute, 5 to
7 times in the exact division and 12 to 19 with the headroom, where step 5's refused nothing in its second minute.
With the headroom, the burst got 21,000 to 28,000 tokens between 60 and 120 s, inside W2's share of 37,500, against
56,000 to 70,000 in step 5. The request rate alone and the deployment's limits behaved as in step 5, since neither
counts in a key's window: the provider kept refusing W3 during and after the burst, and the deployment's limits served
22 of W3's 30 requests in the burst, 3 on the first attempt.

### The limiter's cache on the store

The limiter-cache drill again, each per-key limit once with the census, which now reads the store every half second as
well as the proxy's memory at every call; step 5's rows, with no store, are first:

|Gateway|Limit|Most entries in memory|Memory full at (s)|W2's window gone from memory at (s)|W2's windows evicted from the store|The key's refusals of W2, the last at (s)|W2's burst tokens served from 60 to 120 s|W3 in the burst, served and on the first attempt|Provider refusals, W3|
|---|---|---|---|---|---|---|---|---|---|
|step 4's|tokens per minute per key|200 of 200|30.5|30.8|no store|105, 16.8|70,000|10 of 10, 10|12|
|step 4's|tokens per minute per key, with headroom|200 of 200|31.1|31.6|no store|111, 15.8|56,000|10 of 10, 10|0|
|step 4's without alerts|tokens per minute per key|8 of 200|||no store|109, 117|56,000|10 of 10, 10|0|
|step 4's without alerts|tokens per minute per key, with headroom|8 of 200|||no store|123, 117|21,000|10 of 10, 10|0|
|step 4's with the store|tokens per minute per key|200 of 200|31.4||0 of 3 windows|112, 117|56,000|10 of 10, 10|0|
|step 4's with the store|tokens per minute per key, with headroom|200 of 200|32.9||0 of 3 windows|130, 120|28,000|10 of 10, 10|0|
|step 4's with the store, without alerts|tokens per minute per key|1 of 200|||0 of 3 windows|115, 117|63,000|10 of 10, 10|0|
|step 4's with the store, without alerts|tokens per minute per key, with headroom|1 of 200|||0 of 3 windows|130, 117|28,000|10 of 10, 10|0|

Step 4's alerts still filled the proxy's in-memory cache with request statuses, 31.4 and 32.9 s into the burst, as
they did in step 5, and it no longer mattered: with a store the limiter counts there, and the memory held no window or
counter of either key when it was fullest. In the store no window of W2's went before its time, three lived out their
minutes in each round, W2's key refused until 117 and 120 s, and the provider refused W3 nothing. The windows survive
step 4's alerts. One of the first round's 292 readings of the store timed out at the census's own limit of 0.4 s, and
the alert's pings all answered.

The store costs a few milliseconds a call, step 5's latency drill beside:

|Setup|Calls|At once|Client, median (ms)|Provider, median (ms)|Client less provider, median (ms)|Client less provider, 95th percentile (ms)|LiteLLM's own figure, median (ms)|
|---|---|---|---|---|---|---|---|
|step 4's gateway, W2's key with a tpm_limit|60|1|206|195|11.5|13.6|0|
|step 4's gateway with the store, W2's key with a tpm_limit|60|1|207|192|14.5|16.7|9.03|

### The store stopped, and the alert

`capacity/store_hooks.py` is a callback in the gateway that opens a connection to the store every two seconds from the
proxy's first call on, sends AUTH and PING, and waits a second for the answer. After two misses in a row it POSTs
`limiter_store_unreachable` to step 4's webhook, once, and at the first answer after that `limiter_store_reachable`,
naming the store and how long it was gone and never its password. LiteLLM's own webhook carries budget alerts only
(fact sheet 8.1), and chapter 5 pages the platform's on-call "when the gateway itself fails" (ch05:498), so
`budget/receiver.py` forwards the two events to `platform.oncall@larkspur.example` and to no workflow's owner.

The drill ran one round of the exact division with the census, stopped the store 30 s into W2's burst and started it
again, empty, a minute later, once as LiteLLM leaves its limiter by default and once with
`general_settings.fail_closed_rate_limit_enforcement: true` (`litellm.store-census-fail-closed.yaml`), with which
LiteLLM refuses a call it can't check against the store:

|Limiter|Sent|W2's answers|What refused W2|W2's burst tokens served|W3's incidents served, and on the first attempt|W3's answers|W2's attempt, median / longest (s)|
|---|---|---|---|---|---|---|---|
|LiteLLM's default|before|200 15, 429 250|chapter 5's requests per minute 145, the key's tokens per minute 105|63,000|8 of 8, 8|200 8|0.0198 / 1.18|
|LiteLLM's default|while down|200 24, 429 158|chapter 5's requests per minute 153, the provider's quota 5|70,000|9 of 10, 8|200 8, 429 5|0.0192 / 3.12|
|LiteLLM's default|after|200 15, 429 25|the provider's quota 25|0|7 of 7, 4|200 8, 429 12|0.0729 / 0.438|
|failing closed|before|200 15, 429 246|chapter 5's requests per minute 141, the key's tokens per minute 105|63,000|8 of 8, 8|200 8|0.0208 / 1.14|
|failing closed|while down|429 162, 503 83|chapter 5's requests per minute 162, status 503 83|0|2 of 10, 0|503 57|0.021 / 2.06|
|failing closed|after|200 17, 503 5|status 503 5|0|7 of 7, 6|200 9, 503 1|0.209 / 0.338|

|Limiter|First 503 after the stop|503 answers|Last 503 after the start|First failed ping|Unreachable alert received|First good ping after the start|Answering-again alert received|Forwarded to|
|---|---|---|---|---|---|---|---|---|
|LiteLLM's default||0||1.28|4.47|1.02|1.21|platform.oncall@larkspur.example|
|failing closed|2.86|146|2.68|1.3|4.47|0.981|1.18|platform.oncall@larkspur.example|

|Limiter|Log lines|A batch of store operations failed|The circuit breaker opened|A store call skipped while the breaker was open, with its traceback|The key cache's subscriber lost the store|A Lua script failed, the local mirror used|A call refused, failing closed|Memory readings while down|Most entries in memory|Readings that held W2's window|
|---|---|---|---|---|---|---|---|---|---|---|
|LiteLLM's default|13,937|5|2|650|4|0|0|237|200|0|
|failing closed|20,503|5|1|920|4|0|0|436|200|0|

By default LiteLLM carried on from the proxy's memory, and its counts there didn't hold: no reading while the store
was down held W2's window, W2's key refused nothing until the store came back, and the provider, which had refused W3
nothing before the stop, refused it 5 times while the store was down and 12 after, as the burst's tokens served
without the key's limit, 70,000 in that minute, filled the provider's window. Failing closed, the gateway answered 503
to every call that passed chapter 5's request rate, from 2.86 s after the stop until 2.68 s after the restart, W3's 57
attempts while the store was down among them, with "Rate limit enforcement unavailable: request counters could not be
verified against Redis". Chapter 5 says Larkspur's budgets and rate limits fail closed, and of a managed gateway whose
limits fail open by default, that the default "has to be a decision rather than a discovery" (ch05:498). LiteLLM's
limiter fails open when its store goes; the decision on LiteLLM is this setting, and its cost is every call through a
limited key for as long as the store is gone. LiteLLM's Redis client stopped calling the store after five failures in
a row, its circuit breaker waiting a minute before it tries again, and the proxy logged a traceback for every spend
write it skipped, 650 and 920 of them in the two rounds. The alert reached the receiver 4.47 s after the stop and
about 1.2 s after the restart.

### Retry-After in every client

Step 5 found that a provider's 429 reaches a harness through the gateway with its wait under LiteLLM's prefix
(`llm_provider-retry-after`), that LiteLLM's own limits answer with `retry-after` (60 s for a key's tokens a minute,
and a cooled-down group's whole `cooldown_time`), and that naive retries multiply the load. Step 5b checked each
workflow's model client. None retried blindly, and none waited out a Retry-After: W1's and W2's, chapter 5's
`GatewayModel` underneath, raised the 429 at once; W3's raised it as a 4xx it took for a refusal; W4's rationale seam
and W5's prose seam fell back to their stub sentence at once. Each now waits out a 429 that says how long to wait, and
sends the same request again:

- W1 (`harness/answer.py`) and W2 (`harness/answer.py`): a `WaitingClient`, httpx's client with the wait added, is the
  model's client whenever none is passed in. It reads `retry-after-ms`, `retry-after` and their `llm_provider-` forms,
  waits what the answer asks plus up to a second of jitter, and stops at six attempts or a minute after the first,
  Bedrock's "six total attempts" and the longest wait LiteLLM's router honors. The `__call__` chapter 11 prints for
  W2 is unchanged. Tests: `tests/test_waits.py`, 7 in W1 and 6 in W2.
- W4 (`a2a/rationale_model.py`) and W5 (`harness/prose.py`): `post_waiting`, the same wait and the same caps, before
  the stub stands in. Tests: `tests/test_waits.py`, 6 in W4 and 5 in W5.
- W3 (`harness/loop.py`): below.

A 429 that names no wait, as chapter 5's per-run budget and request rate don't, is never sent again, and nothing but a
429 (and, for W3, a 408) is retried. Chapter 13 prints W4's seam (lst-13-04), and two of its lines change: the
`import httpx` after `try:` goes, since `post_waiting` imports it, and `resp = httpx.post(` becomes
`resp = post_waiting(`. That listing needed an erratum, and chapter 13 now prints the seam with `post_waiting`.

### W3 under a 429 or a 408

Step 5's outage drill had W3's triage raise on the cooldown's 429 and on the timeout's 408, which left the run in its
store at triaging for a restarted harness to pick up. `W3GatewayModel` (`harness/loop.py`) now treats both as a wait
or an end. When the answer says how long to wait (W2's `retry_after_s`, the same four headers), the same request goes
again after that wait and up to a second of jitter, if the wait ends inside the incident's time budget and within six
attempts. The budget, `TIME_BUDGET_S`, is two minutes from the triage's first model call, the lab's figure, about
three times the longest triage of W3's kept run (42.2 s), since the book sets none. Otherwise the call returns "model
unavailable", and W3's loop and harness, unchanged, end the run as refused, with W3's fixed sentence ("W3 couldn't
reach the model just now; work the incident without it, or try again") in its store: the incident goes to the
engineer, as W3-D10 has it for the self-hosted route. A 5xx and a refused connection end the run as before, and any
other 4xx (the grid, a budget, the kill switch) still raises. The model keeps every wait (`waits`) and why it gave up
(`unavailable`), and labels a call once however many times it is sent. `tests/test_waits.py` has 11 tests: the wait
that fits and the one that doesn't, the budget counted from the first call, a 408 with and without a wait, six
attempts, the other statuses, and a run through W3's harness refused in its store with no approval asked and nothing
written. W3's suite has 126 tests: 125 pass, and the offline Terraform plan skips without Terraform and a provider
cache, as before.

The outage drill ran again on step 5's config, `litellm.outage.yaml`, with W3's new client in its two runs:

|Mode|W2's run|W3's run in flight|W3's run started 20 s in|
|---|---|---|---|
|5xx|answered|unavailable after 2 model calls and 0.885 s: the gateway answered 503|answer after 2 model calls and 61.3 s, having waited 30.3 and 30.5 s for 429, 429|
|timeout|answered|unavailable after 2 model calls and 6.03 s: 408 with no wait to wait out|answer after 2 model calls and 61.5 s, having waited 30.4 and 30.4 s for 429, 429|
|connection|answered|unavailable after 2 model calls and 2.74 s: the gateway answered 500|answer after 2 model calls and 61 s, having waited 30 and 30.2 s for 429, 429|

The run in flight ended as model unavailable in every mode, on the timeout's 408 too, which step 5's W3 raised. The
run started 20 s into the outage waited out the cooldown's two 429s, 30 s each and inside its two minutes, and the
primary, healed by then, answered it, where step 5's W3 raised. W3's own calls through the drill got what they got in
step 5, the primary's error and then the cooldown's 429, all of them in ca-central-1.

### W3's fallback in Canada

Chapter 5's callback checks every hop of an alias's fallback chain against chapter 2's grid and the workflow's
Regions, and a hop that fails turns the request's fallback off altogether (`gateway_rules.decide`). W3's Confidential
calls ask for `larkspur-chat`, whose one hop is the same family in us-east-2, outside W3's one Region, so chapter 5's
rule turns their fallback off, and a change to the config alone can't give W3 a hop of its own while W2 keeps its hop
to us-east-2. The grid in chapter 5's lab lets a Confidential call reach a self-hosted model in the jurisdiction
(`may_receive`, and its test `test_grid_by_row`), and the self-hosted alias serves from ca-central-1. So chapter 16's
outage config, `capacity/litellm.outage-canada.yaml`, is step 5's with a section LiteLLM doesn't read,
`larkspur_fallbacks_in_jurisdiction`, naming `larkspur-chat-restricted` as `larkspur-chat`'s fallback for a request
whose own chain stops, and `capacity/fallback_hooks.py` after chapter 5's callback. When chapter 5 has turned a
request's fallback off and the request may reach the named alias by chapter 5's own check (`_blocked`: the grid for
every deployment behind it, and every Region it serves from inside the manifest's), the callback gives the request
that one hop through LiteLLM's per-request `fallbacks`, marks the metadata so the cost line no longer says the
fallback was disabled, and writes a `fallback_in_jurisdiction` line after chapter 5's `fallback_disabled` line. A
request chapter 5 left alone keeps chapter 5's chain, so W2 still fails over to us-east-2, and a Restricted call,
whose alias has no chain, has no fallback. Chapter 5's config, code and demo are unchanged.

The outage drill on that config:

|Mode|W2's calls|W2's answers|Served by|W3's calls|W3's answers|Served by|W3's refusals|
|---|---|---|---|---|---|---|---|
|5xx|59|200 59|fallback 59|30|200 30|self-hosted 30||
|timeout|47|200 47|fallback 47|25|200 25|self-hosted 25||
|connection|56|200 56|fallback 56|29|200 29|self-hosted 29||

|Mode|W2's calls by Region|W3's calls by Region|W3's calls by deployment|W3's requests the primary saw|W3's requests us-east-2 saw|W3's requests the self-hosted saw|W2's requests the self-hosted saw|
|---|---|---|---|---|---|---|---|
|5xx|ca-central-1 50, us-east-2 62|ca-central-1 60|primary 26, self-hosted 34|31|0|31|0|
|timeout|ca-central-1 36, us-east-2 64|ca-central-1 55|primary 19, self-hosted 36|26|0|33|0|
|connection|ca-central-1 45, us-east-2 64|ca-central-1 60|primary 24, self-hosted 36|22|0|33|0|

|Mode|W2's run|W3's run in flight|W3's run started 20 s in|
|---|---|---|---|
|5xx|answered|answer after 2 model calls and 1.41 s|answer after 2 model calls and 0.568 s|
|timeout|answered|answer after 2 model calls and 5.75 s|answer after 2 model calls and 0.554 s|
|connection|answered|answer after 2 model calls and 2.72 s|answer after 2 model calls and 0.521 s|

W3 was served through every failure mode: each of its calls made while the primary failed was answered by the
self-hosted alias, the fake in us-east-2 saw none of W3's requests, and both W3 runs answered. W2's calls failed over
to us-east-2 as in step 5, and none of them reached the self-hosted alias. In the timeout mode the calls sent to the
primary before its cooldown waited out its five seconds before the fallback answered. During an outage the self-hosted
replicas carry W3's Confidential calls as well as its Restricted ones; at chapter 9's measured speeds W3's busy hour
of Confidential calls would take 46.2 replica-seconds, and with the Restricted calls 54.5, 1.51% of one replica's
hour.

### Continuity

Two rows of step 5's continuity table change with step 5b, and `capacity/continuity.yaml` keeps both versions
(`after_step5b` for these), each number in them checked against the drills' files:

|Component|Failure mode|Recovery objective|Evidence|Gap|
|---|---|---|---|---|
|the gateway|A model behind it fails, with 5xx errors, timeouts or refused connections; or the proxy itself stops, and every call in flight with it.|A failing model off the path within three failures, seconds, or the timeout and a little more when it hangs; back on it within one cooldown of healing, thirty seconds; the proxy back within a minute of a restart; and a workflow whose data may not leave Canada served meanwhile by the self-hosted alias. RPO none: it holds nothing a call needs beyond its database.|Outage drill again, step 5's three modes. With litellm.outage-canada.yaml, W3's calls failed over to the self-hosted alias in ca-central-1 and all 30, 25 and 29 made while the primary failed were answered; the fake in us-east-2 saw none of W3's requests, and W2's calls failed over to us-east-2 as in step 5. On step 5's config, W3's model client of step 5b ended its triage in flight as model unavailable on the primary's 503, the timeout's 408 and the refused connection's 500, and a triage started in the cooldown waited out two 429s of 30 s and was answered by the healed primary 61.3 s after it began.|One Region: the second gateway Region of month five isn't deployed (O-D17). A proxy killed with calls in flight, and a fleet of proxies behind a load balancer, weren't drilled. During an outage the self-hosted replicas carry W3's Confidential calls as well as its Restricted ones; at chapter 9's speeds W3's busy hour would take 1.51% of one replica's hour, and the replicas under that load weren't drilled.|
|Redis|The store unreachable. LiteLLM keeps the keys' windows and counters, the spend counters and the router's state there, and counts in it with Lua scripts that must run whole.|Back within the minute LiteLLM waits before it tries the store again, with the keys' limits failing closed meanwhile (fail_closed_rate_limit_enforcement) and the platform's on-call alerted within seconds. RPO: the current minute's windows, which a restarted store has lost; nothing a budget needs, since the spend is in the database.|Garnet 2.2.5 ran every step of LiteLLM 1.106.6's eight limiter scripts as Redis does; with its Lua transaction mode it admitted 250 of 1,000 check-and-increments against a limit of 250 in each of three trials, and without it 251 in two. With the windows in the store, step 4's alerts still filled the proxy's in-memory cache 31.4 s into a burst, yet W2's key went on refusing until 117 s, no window left the store early, and the provider refused W3 nothing. With the store stopped 30 s into the burst, LiteLLM's default carried on from memory, which held no window of W2's: the key refused nothing until the store came back, and the provider refused W3 5 times while it was down and 12 after. Failing closed, every keyed call got 503 from 2.86 s after the stop until 2.68 s after the restart. In both rounds the alert reached step 4's receiver 4.47 s after the stop, and the second one 1.21 and 1.18 s after the restart. LiteLLM's circuit breaker opened after five failures, and the proxy wrote 13,937 log lines in the default's round, 650 of them tracebacks for spend writes it skipped.|One proxy on one store: a fleet sharing it, the store's own replication and failover, a store that answers slowly rather than not at all, and TLS to it weren't drilled. Garnet ran in memory, so a restarted store came back empty.|

### What step 5b doesn't drill

- A fleet. One proxy ran each drill, so the store held one worker's windows; several proxies sharing it, which is what
  a shared store is for, weren't run.
- The store's own continuity. Garnet ran in memory, with no append-only file, no replica and no TLS, on loopback with
  a password; a restarted store came back empty, and replication and failover weren't drilled.
- A slow store. The drill stopped the store, so connections failed outright; a store that answers slowly meets
  LiteLLM's timeout accounting, which opens the breaker only after five timeouts spread over five seconds, and wasn't
  drilled.
- The other workflows' waits through a live gateway. W1's, W2's, W4's and W5's waits are tested against httpx's mock
  transport; only W3's ran against the gateway, in the outage drill.
- The self-hosted path under an outage's load. The fakes answer at once, and the replicas' queueing with W3's whole
  load on them wasn't drilled. A Confidential prompt longer than the self-hosted model's window would get a 400 from
  the fallback, which W3 still raises; W3 trims logs only in Restricted prompts.
- The prefix cache's salt. Chapter 5 adds the per-workflow `cache_salt` only when the alias asked for is self-hosted,
  so a Confidential call that falls back to the self-hosted alias carries none, and on chapter 9's vLLM it would share
  the prefix cache with any other unsalted call. None is sent today, and the chapter can say whether the fallback
  needs one.
- A pager. The receiver writes the store's alert to its outbox for the platform's on-call; nothing pages.

## SLOs, the simulated month, the alerts and the playbook (step 6)

Step 6 builds O-D12 and O-D13 on this workstation, with no model, no gateway process, and no network beyond
127.0.0.1: three SLIs for each workflow, computed from what the kept runs hold; a target and an error budget for
each; a simulated month built from the kept runs, with five events injected into it; the workbook's burn-rate alerts,
W5's failed nights, and an hourly probe over that month; the error-budget policy applied to it; the dashboard's panels
and the data for fig-16-03; and the misbehaving-agent playbook. The SLIs on the kept runs are measured. Everything
after them is simulated, and every file that holds it says so in its first field or on every line. Every table below
is in `results/2026-11-09/slo/summary.md`, which `slo/run_slo.py` writes from the files beside it. The book's lines
are cited as of 9 November 2026.

### The SLIs

`slo/slos.yaml` defines them, workflow by workflow, with what makes a run valid, the file, field, or span attribute
each event comes from, and what the kept runs can't supply; `slo/slis.py` computes them. A run, kept or simulated,
becomes one event: how it ended, how long it took, and, where a person decided on what it proposed, what they decided.

- Success counts the runs that end in an answer, a refusal the harness made by rule, or a proposal, over the valid
  runs. A step-budget stop, chapter 5's per-run budget refusal, the model unavailable, and an error are bad. A run
  that the workflow's own monthly budget or request rate refused isn't valid: that is the control holding, and
  ch05:498 sends it to the owner's dashboard, where it shows on the budget and 429 panels, and to no pager.
- Latency counts the runs that were good for success and finished inside the workflow's threshold, so a failure isn't
  counted twice: 30 seconds for W1, 10 for W2's chat, 120 for W3 (its own time budget, `TIME_BUDGET_S`), 60 for W4,
  and the whole night for W5, six hours from its 02:00 ET start.
- Outcome counts what a person decided: W3's writes approved, run, and not rolled back; W4's risk class kept by the
  board; W5's pull requests merged. A proposal nobody decided isn't valid yet.

What each workflow's signals say, and don't:

- W1 words a search budget that ran out as its refusal by design (W1-D22, `answer.finish`), as chapter 10 tells it
  (ch10:330), so for W1 that is a refusal by rule.
- W2's harness words a step-budget stop as its refusal too and marks it `larkspur.refused`, as it does a refusal by
  rule; its log line can't tell them apart. The run's calls can: the harness's exact refusal after `MAX_READS` reads
  and one model call more (`slis.w2_budget_stop`). In production the same count is in the cost lines and the span
  tree of the trace id.
- W3's state and triage name the stop: the step-budget sentence, or the model-unavailable sentence step 5b gave it.
- W4's run is good when its pack reaches the change record. The board's decision on the class is the outcome event,
  and nothing in the lab emits it: the ServiceNow fake keeps the state "Assess".
- W5's night is good when it reaches `night_done`, and its ledger holds each pull request's state.
- W1 and W2 have no outcome SLI. No person decides on an answer, and the one human signal, a person reporting an
  answer wrong, is collected by nothing in the lab or the book.

The controls (residency, the never-list, the budgets) get no error budget. A run that breached one carries its
breach, `slis.incidents` lists it as an incident, and no SLI, burn rate, or budget account reads the field;
`tests/test_slo_slis.py` breaches a control on a fifth of a stream and finds every ratio, burn rate, and budget account
the same as without it. Quality from chapter 15's sets gates a release (E-D11) and has no SLO.

### Measured on the kept runs

|Workflow|Runs by end|Success|Target|Latency threshold|Latency|Target|Outcome|Target|
|---|---|---|---|---|---|---|---|---|
|W1|answer 64, refusal 11|75 / 75 (100%)|99.5%|30 s|74 / 75 (98.67%)|95%|none|none|
|W2|answer 106, refusal 23, budget stop 5, error 1|129 / 135 (95.56%)|99.5%|10 s|128 / 129 (99.22%)|95%|none|none|
|W3|answer 33, refusal 2, proposal 5, budget stop 8|40 / 48 (83.33%)|95%|120 s|40 / 40 (100%)|95%|2 / 2 (100%)|90%|
|W4|proposal 48|48 / 48 (100%)|99%|60 s|48 / 48 (100%)|95%|no events|90%|
|W5|proposal 33|33 / 33 (100%)|90%|21,600 s|33 / 33 (100%)|90%|11 / 11 (100%)|80%|

|Workflow|Kept run|Runs|Runs by end|Success|Latency|Outcome|
|---|---|---|---|---|---|---|
|W2|gpt-oss-20b 2026-11-02|25|answer 21, refusal 4|25 / 25 (100%)|25 / 25 (100%)|none|
|W2|gpt-oss-20b 2026-11-02 run1|20|answer 11, refusal 4, budget stop 5|15 / 20 (75%)|14 / 15 (93.33%)|none|
|W2|gpt-oss-20b 2026-11-02 run2|20|answer 16, refusal 3, error 1|19 / 20 (95%)|19 / 19 (100%)|none|
|W2|gpt-oss-20b 2026-11-02 run3|20|answer 17, refusal 3|20 / 20 (100%)|20 / 20 (100%)|none|
|W2|gpt-oss-20b traced/2026-11-03|25|answer 21, refusal 4|25 / 25 (100%)|25 / 25 (100%)|none|
|W3|gpt-oss-20b 2026-11-02|24|answer 17, refusal 1, proposal 2, budget stop 4|20 / 24 (83.33%)|20 / 20 (100%)|no events|
|W3|gpt-oss-20b traced/2026-11-03|24|answer 16, refusal 1, proposal 3, budget stop 4|20 / 24 (83.33%)|20 / 20 (100%)|2 / 2 (100%)|

The second table keeps W2's and W3's kept runs, and the summary has all 28. Every kept run counts, on every model,
the early ones included:

- W2's five step-budget stops are all in its first kept run (`2026-11-02 run1`), whose harness refused nine of its 20
  questions with the same sentence; the later runs stopped none. Its one error is run2's w2-14, the weeklong window
  that "still ended as an outage" (ch11:327): one question in the 90 of W2's four later runs on gpt-oss-20b.
- W3 ends 8 of 48 incidents at its read budget, four in each kept run, which puts its success at 83 percent.
- The outcomes measure no person. W3's two approvals are the eval's scripted approver (`eval/lab.py` approves every
  proposal an eligible approver exists for), W5's one merged pull request in each of its 11 kept runs is the eval's,
  which merges the archive volume's pull request before golden night 2 (`eval/nights.yaml`, `before.merge`), and W4
  kept no board decision.
- W1's one slow question took Nova Lite 55.6 seconds, the 56 seconds chapter 10 reports; W2's is in run1, 19.1
  seconds.

### The SLOs

The targets are the lab's proposals for Larkspur; the book sets none. Each comes from the clouds' SLAs in section 6 of
the fact sheet (Bedrock's "99.9% monthly uptime", where an error is "any Request that returns a 500 error code"), the
kept runs, and the rung, and the budget in events is 1 minus the target times the valid events the SLI expects in the
simulated month at its volume:

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

- W1 and W2, success 99.5 percent: two or three model calls and a search or read a question put the SLA's ceiling at
  about 99.7 to 99.8 percent from the model alone, and 99.5 leaves the tools their share.
- W3, success 95 percent: six to eight calls and reads an incident put the ceiling near 99.3. At the kept runs' 83
  percent a total outage burns at 1 / (1 - 0.83), about 6, so the hour's page at 14.4 could never fire, the workbook's
  caution for low targets ("a 100% outage consumes only 1.4% of the budget in that hour, this alert could never fire",
  fact sheet 8.9). 95 is the lowest round target at which a total outage pages (it burns at 20). W3 doesn't meet it
  today, and its budget says so in the month below.
- W4, success 99 percent: one model call a change, which the stub sentence covers when the model fails, and about 200
  changes a month (ch13:9), so the budget is two failed changes.
- W5, every SLI in nights: one run a night is a thirtieth of the month and the budget has to be whole failed nights
  (fact sheet 8.9). 90 percent of about 34 runs a month, nights and alarm runs, is a budget of 3.4: three failed
  runs fit inside it and the fourth spends it. 80 percent of decided pull requests merged, since some drift is
  intended and a person rightly declines to adopt it.
- Latency, 95 percent for W1 to W4 at the thresholds above, each past the kept runs' tail on the local models; W5's
  six hours is far off the kept runs' times, 15 to 714 seconds for the 22 scheduled nights and 3 to 147 for the 11
  alarm runs.
- Outcome, 90 percent for W3 and W4: a declined restart or a reclassified change is a person correcting the workflow,
  and more than one in ten would make the person's check a review of its mistakes.

### The simulated month

`slo/month.yaml` says what the month is built from and `slo/simulate.py` builds it, seeded (20261109) and the same on
every run: 30 days from 00:00 ET on Tuesday 5 January 2027, after the year-end freeze and with no change of clocks,
and three days of lead-in so the 3-day window is full on the first day. Each workflow's runs arrive at the ledger's
monthly volume (`results/2026-11-03/ledger.json`), as a Poisson process with no daily or weekly cycle, since the book
gives none; W5 runs once a night at 02:00 ET and four alarm runs a month. Each run is one of its workflow's kept runs
on gpt-oss-20b, the ledger's reference model, drawn with replacement from the pools the file names, keeping its end,
its time, and its calls by alias; W2's pool leaves out its first kept run, which the regression draws from. The
golden sets' mix of cases stands for production's, traps and refusals included. A person's decisions are assumptions,
stated in the file, because no kept run holds one: W3's proposals decided within half an hour, nine in ten, accepted
at 95 percent with 2 percent of those rolled back; W4's at the board's Thursday session at 14:00 ET (ch13:18),
accepted at 97 percent; W5's one new pull request a night, the kept steady-state night's, decided within three days
six times in ten and merged at 90 percent. An event counts at the time it becomes known, in the month's tables, the
budgets and the alert windows alike: a run when it ends, an outcome when a person decides. So the lead-in's runs,
which end before the month, count in no budget; a decision made inside the month on one of their proposals counts,
as any rolling window would see it; and a decision made after the month's end counts in the next month.

Five events are injected, each changing the runs it touches, which then carry its name. The month models no response
to an alert: each event runs its course, so the slower signals show too.

- `provider-outage`, 45 minutes of the managed model behind `larkspur-chat` in step 5's timeout mode. Under step 5b's
  gateway W1, W2, and W3 fall back to the self-hosted alias in Canada, and every managed call waits the deployment's
  5-second timeout first (`capacity/litellm.outage-canada.yaml`), an upper bound at the month's rate of about two
  managed calls a minute. W4's and W5's manifests list `larkspur-chat` alone, so their calls get the cooldown's 429
  with its retry-after of 30 seconds, which step 5b's seams wait out once before they write the stub; the month adds
  the timeout and that one wait to each of their calls. With this seed no W4 or W5 run starts inside the 45 minutes,
  so nothing in the results moves with that shape, and a test drives it on a W4 run of its own.
- `throttled-hour`, the provider's quota at half the demand for an hour, with the shares of step 5's retry drill through
  step 4's gateway with Retry-After honored: of 80 requests, 34 refused at their first attempt, 29 of those served
  after waiting, 5 never. A waited call waits between 1 second and the clients' cap of 60, since the drill kept no wait
  per request.
- `model-regression`, `larkspur-chat` remapped on day 15, after chapter 15's live job passed it, and worse in
  production: W2 draws from its first kept run and W5 from its three nights before the review, and a person accepts
  W3's proposals at 0.6, the share of W3's five kept proposals that passed their golden check, standing for a worse
  proposal declined. W1 has no earlier kept run on the model, and W4's class is decided by rules before the model is
  asked, so neither changes.
- `self-hosted-down`, a weekend without either of chapter 9's replicas. Restricted calls have no fallback: W1's runs
  that send one raise and W3's end as model unavailable. The probe stays green.
- `w4-records-refused`, a day in which the change record's API refuses W4's writes. Every pack fails to be written; the
  model path, and with it W4's probe, is healthy.

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

|W5's scheduled nights|Nights|Output tokens a night, mean|Range|Seconds a night, mean|
|---|---|---|---|---|
|before|16|12,929|8,377 to 18,505|239|
|after|14|19,394|11,556 to 25,462|547|

The baseline is what the kept runs measured, and two workflows spend their budgets on it. W2's one read failure in 90
questions is twice what 99.5 percent allows, 261 bad runs in the month against a budget of 212. W3's step-budget stops,
40 of 281 incidents, are almost three times its budget of 14.8. The regression shows in W2's step-budget stops, 5,161
of the runs after the remap, and in W5's nights, which spent half as many output tokens again and more than twice the
time, with no SLI moved: only the cost lines show that one. W3 had no incident in the outage's 45 minutes or the
throttled hour, and its latency held throughout.

### The alerts, and where burn rates fail (simulated)

`slo/alerts.yaml` holds the rules and `slo/burn.py` evaluates them every five minutes over the simulated month. The
burn-rate rules are the workbook's table (Table 5-8): page at 14.4 over one hour and at 6 over six hours, ticket at 1
over three days, the burn rate being "how fast, relative to the SLO, the service consumes the error budget". The table
pairs each long window with a short one, 5 minutes, 30 minutes and 6 hours, which fact sheet section 9.4 gives with
the workbook's guideline, "a good guideline is to make the short window 1/12 the duration of the long window". A rule
fires only while both windows burn past its rate, so an alert ends about a short window after its burn does and not a
long window later. A window with no valid event has no burn rate, so the short window of a stream with few events is
often empty, and its alert stays off until a bad event falls inside it. An alert that fires again within its long
window of its last end is the same alert, and one that fires after that is a new one. The outcome SLI opens
tickets and never pages: its events are a person's decisions, made by someone who has already seen what the workflow
proposed. W5 goes by nights: a ticket for each failed or late night, one more when the fourth failed run spends the
budget of 3.4, and never a page. The platform's on-call is paged when the provider's 429s reach two or more
workflows within five minutes (ch05:498); the two other platform rules `alerts.yaml` writes down, the gateway down
and a workflow's own limit, have no evaluator over this month, which injects neither, and the file says so. An alert
is put down to the injected event behind more than half the bad events in its window when it starts, and to the
baseline otherwise.

Three designs ran over the same simulated month. Own traffic gives every workflow its own runs alone. With the
probe, the lab's proposal, W1, W3, and W4 add the hourly probe's runs to their own in the success SLI, the workbook's
"artificial traffic"; they are the low-volume workflows, at about 8, 0.4, and 0.3 runs an hour against the
workbook's example of "10 requests per hour". Grouped puts W1, W3, and W4 together as one service on the success SLI,
the workbook's other option ("Combine smaller services into a larger service for monitoring purposes"), at the lowest
of their targets, 95 percent, so that W3's own stops don't page the group.

|Injected event|own-traffic|with-probe (proposed)|grouped|platform|
|---|---|---|---|---|
|provider-outage|none|page: W4 success fast-burn-1h, Mon 11 Jan 10:35|none|none|
|throttled-hour|page: W2 success fast-burn-1h, Wed 13 Jan 14:10|page: W2 success fast-burn-1h, Wed 13 Jan 14:10|page: W2 success fast-burn-1h, Wed 13 Jan 14:10|page: PLATFORM provider 429s provider-429-across-workflows, Wed 13 Jan 14:20|
|model-regression|page: W2 success fast-burn-1h, Wed 20 Jan 10:30|page: W2 success fast-burn-1h, Wed 20 Jan 10:30|page: W2 success fast-burn-1h, Wed 20 Jan 10:30|none|
|self-hosted-down|page: W1 success fast-burn-1h, Sat 30 Jan 00:45|page: W1 success fast-burn-1h, Sat 30 Jan 00:45|page: group:w1+w3+w4 success fast-burn-1h, Sat 30 Jan 04:50|none|
|w4-records-refused|page: W4 success fast-burn-1h, Thu 28 Jan 14:35|page: W4 success fast-burn-1h, Thu 28 Jan 14:35|none|none|

|Injected event|Workflow|SLI|Highest burn over 1 hour (page at 14.4)|Over 6 hours (page at 6)|Over 3 days (ticket at 1)|
|---|---|---|---|---|---|
|provider-outage|W2|latency|13.6|2.76|0.229|
|provider-outage|W4|success|100|12.5|1.06|
|throttled-hour|W1|success|28.6|4.65|0.316|
|throttled-hour|W2|success|31.2|9.94|2.78|
|model-regression|W2|success|93.9|61.9|53.4|
|model-regression|W3|outcome|10|10|10|
|self-hosted-down|W1|success|125|57.1|16.4|
|self-hosted-down|W3|success|13.3|5.46|1.98|
|w4-records-refused|W4|success|50|25|3.61|

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

The highest-burn table keeps the rows the notes below discuss; the summary has every workflow and SLI each event
touched. Each figure in it is a long window's highest burn, and a page needs the short window past the rate as well.

- In the provider outage the fallback answered every call. W2's latency, with most of its questions 10 seconds slower
  for 45 minutes, burned at 13.6 over the hour, under 14.4, and the 6-hour and 3-day windows averaged it away. The only
  page came from W4's probe, whose call has no fallback hop; W4's own changes rode the outage out on the stub sentence,
  so the page was for a failure W4's users never saw. The fallback panel (the gateway's fallback lines) is where the
  outage shows.
- The throttled hour paged W2 within 10 minutes and the platform within 20, and W1's 1-hour burn reached 28.6 on one
  failed question in seven. W3 had no incident in the hour.
- The regression paged W2 30 minutes after the remap: a quarter of its questions stopped at the read budget. Paged,
  the on-call lead would remap the alias back, which would end it for every workflow on the alias. Without W2's volume
  it would have shown only in W3's outcome, which burned at 10 on its first declined proposal and opened a ticket put
  down to the regression, and in W5's cost lines, which no alert reads.
- The weekend without the self-hosted path is section 8.9's first caution. It failed five of W3's incidents. With its
  own traffic alone, W3 paged three times; with the probe's green runs in its windows, W3's burn peaked at 13.3 over an
  hour and 5.46 over six, just under both pages, and nothing put down to the event fired for W3: "if an issue affects
  real users but doesn't affect artificial traffic, the successful artificial requests hide the real user signal". W1's
  own traffic paged 45 minutes in, since W1 sends Restricted calls too, and 21 times over the two days.
- The day of refused records is the second caution. W4 failed completely, and its own alerts paged at its first
  failed change, with or without the probe (at 99 percent, one failed change beside the hour's probe is a burn of 50).
  In the group, W4's three failures among about 214 runs of the day were "not a significant event": nothing put down to
  the event fired. The group did page for the weekend, four hours after W1's own page.
- Most of the own-traffic design's pages came from the baseline, 52 of 84. W3 paged 47 times on its own traffic for its
  own step-budget stops, since a single failed incident in an hour is 100 percent of the hour; with the probe it paged
  twice, and the same dilution hid its failures over the weekend. W2's read failures paged 5 times in clusters and
  kept its 3-day ticket open.
- The short windows left the first alert of every event where it was and changed how many alerts there are. A page that
  only good runs leaving the long window had raised, with no bad run in the short one, is gone: W3's own traffic lost 9
  of its 1-hour pages and 3 of its 6-hour pages that way, and W2 the page of Fri 8 Jan 11:55. An alert ends sooner,
  W2's page for the throttled hour closing at 14:45 where the hour alone had held it until 15:30. And an alert that
  has ended can start again: W1 fails about one question an hour in the weekend, and a failure that came an hour or
  more after a page closed opened a new page, 21 in all where the long window alone paged 6.

One number in the workbook's low-traffic paragraph doesn't follow from the definition it gives: at 10 requests an hour
and 99.9 percent, one failure is a 10 percent error rate, which the burn-rate definition makes a burn of 100, where the
quoted sentence says "a 1,000x burn rate"; its "13.9% of the 30-day error budget" does match one failure in the 7.2
the month allows. `tests/test_slo_burn.py` reproduces both. The chapter's fact check should read the workbook's page.

### The hourly probe

`slo/probe.py` sends, each hour at minute 30, the first model call of one golden case per low-volume workflow (W1's
gq-14, W3's w3-02, W4's w4-01) through the gateway with the workflow's key, its workflow and data-class tags, and a
new trace id, in the shape the workflows' model seams send. The system prompt is imported from the workflow's harness
and the question comes from chapter 15's golden set; W4's is the class, reasons, and change of its kept pack, as its
rationale seam writes them. A 200 with a reply inside 30 seconds is good; a refusal, an error, an empty reply, a late
one, or no answer is bad. It tests the model path alone, which is what the cautions above turn on.
`tests/test_slo_probe.py` runs it against a fake model on 127.0.0.1: what it sends, each way it can fail, and its cost
line, which has the ledger's shape (`kept_run` "probe") and is priced by `ledger/price.py` like any other. Its request
carries no tool definitions, so it is smaller than the kept call; the simulated month's cost lines carry the kept
call's measured tokens, as `probe-costlines.jsonl` records, one line a probe. Over the simulated month:

|Workflow|Case|Tokens a probe (in / out)|Probes|Served|Probe tokens in the month|The workflow's own tokens|Probe over own|USD in the month|
|---|---|---|---|---|---|---|---|---|
|W1|gq-14/oncall.engineer|404 / 44|720|720|322,560|18,918,523|1.7%|0.02673|
|W3|w3-02|981 / 43|720|720|737,280|3,069,407|24.02%|0.05313|
|W4|w4-01|200 / 253|720|719|325,707|76,710|424.6%|0.05577|

At Nova Lite's price in Canada, on gpt-oss-20b's measured tokens (Nova Lite's own count would differ by step 2's
ratios), the three probes cost about 14 US cents a month. Against the workflows' own tokens they
are large: W4's probe sends 4.2 times W4's own month, since W4 makes about 200 calls a month and the probe 720, and
W3's sends a quarter of W3's. Through a live gateway each probe call would also leave the gateway's own cost line,
under the workflow's tag, since the key binding of step 4 refuses any other; the probe's log of trace ids is what
tells those lines from the workflow's. Step 2's month in `ledger/` doesn't count the probe's lines yet, and this step
leaves `ledger/` unchanged.

### The error-budget policy

`slo/policy.yaml` is the policy and `slo/budget_policy.py` applies it. Its sources are the SRE book's "If SLO
violations occur frequently enough to expend the error budget, releases are temporarily halted" and the workbook's
example policy: "This policy is not intended to serve as a punishment for missing SLOs" (fact sheet 6). The owner and
the sponsor agree to it with the platform team before the workflow ships, and it goes to the board with the manifest.

- When any SLI's budget is spent, changes to the workflow's prompts and models stop: its system prompt and templates,
  any remap of an alias for it, any new model in its manifest. A change that addresses what spent the budget goes ahead
  with the sponsor's written agreement, as does every security fix. Nobody decides the freeze at the time; it follows
  from the budget, the owner and sponsor are told, and the platform's change pipeline refuses the change. Its record is
  a line in the policy's log.
- When the outcome SLI's budget is spent, the workflow also moves down a rung, through step 4's rung switch. The on-call
  lead decides it, as ch02:163 makes every move down a rung an emergency change, and `budget/oncall.py` leaves its
  change line. In the month this runs as a dry run: `oncall.lower_rung` writes the override and the change line into a
  temporary folder and `rungs.plan` reads it back as the harness would.
- A breach of a control spends nothing: it is an incident for the playbook.

Applied to the simulated month:

|Workflow|SLI|Budget (events)|Bad events in the month|Budget used|Spent at|Bad events when spent|
|---|---|---|---|---|---|---|
|W1|success|29.6|54|182.5%|Sat 30 Jan 21:56|throttled-hour 1, self-hosted-down 29|
|W2|success|212|5,432|2560%|Sun 17 Jan 04:24|baseline 203, throttled-hour 10|
|W3|success|14.8|45|304.2%|Fri 22 Jan 21:38|baseline 15|
|W3|outcome|2.77|5|180.2%|Wed 20 Jan 11:18|baseline 2, model-regression 1|
|W4|success|1.97|3|152.1%|Thu 28 Jan 18:00|w4-records-refused 2|
|W4|outcome|19.7|9|45.63%|||
|W5|outcome|3.6|3|83.33%|||

|When (ET)|Workflow|Action|SLI|Decided by|Record|
|---|---|---|---|---|---|
|Sun 17 Jan 04:24|W2|freeze|success|the policy, agreed in advance||
|Wed 20 Jan 11:18|W3|freeze|outcome|the policy, agreed in advance||
|Wed 20 Jan 11:18|W3|rung down|outcome|the on-call lead (oncall.lead@larkspur.example)|EC-SIM-01: rung 3 to 2, dropped record_change, restart_deployment, scale_deployment; document by 2027-01-21T16:18:16.815+00:00|
|Fri 22 Jan 21:38|W3|budget spent|success|||
|Thu 28 Jan 18:00|W4|freeze|success|the policy, agreed in advance||
|Sat 30 Jan 21:56|W1|freeze|success|the policy, agreed in advance||

W2's baseline spent its budget on day 12, before the regression; W3's outcome budget, under three declined proposals a
month at its volume, was spent 78 minutes into the regression by its third declined proposal, and W3 went down to rung
2 with its three write tools dropped. W4's budget of two failed changes went on the day of refused records, and W1's on
the weekend without the self-hosted path. Every other budget held; the summary has them all.

### The dashboard and fig-16-03

O-D17 rules out Grafana and a vendor console, so the dashboard is `slo/dashboard.yaml`, a list of panels with what
each shows and where its data comes from:

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

The Foundry panel is the count chapter 18 puts on this dashboard (ch18:49). Its quota is in the Microsoft fact sheet
(LINKS.md, chapter 8: 2,000 concurrent hosted-agent sessions per subscription per region
in Canada Central, 1,000 in regions it doesn't list, and the errors `session_quota_exceeded` and
`regional_session_quota_exceeded`), and no sheet names a metric for the count, so the panel stays an open fact for
the chapter's fact check and the lab names no metric for it.

`results/2026-11-09/slo/fig-16-03.json`, marked simulated, is one workflow's dashboard over the simulated month, hour
by hour: each SLI's value and
budget left to date, its burn rates over the three windows under the proposed design, the runs, step-budget stops, 429s,
fallback calls, and the probe's result, with the alerts, the policy's actions, and the injected events' hours beside
them. The workflow is the one whose month shows the most, counting the injected events that changed its runs, the
kinds of alert it had, the kinds of policy action, and its SLIs:

|Workflow|Injected events that changed its runs|Kinds of alert|Kinds of policy action|SLIs|Sum|Chosen|
|---|---|---|---|---|---|---|
|W1|3|3|1|2|9||
|W2|3|4|1|2|10||
|W3|2|4|3|3|12|yes|
|W4|1|3|1|3|8||
|W5|1|0|0|3|4||

W3's month has all three SLIs, a success budget its own stops spend, the probe's smoothing and the failure it hid, the
outcome budget the regression tips over, and the rung down that follows.

### The playbook

`playbook/playbook.yaml` is the table the chapter can print, `playbook/runbook.md` the on-call lead's version with the
commands. Each of O-D13's eight symptoms has its signal, a first and a second lever, and the record each leaves; the
levers are the rate in the manifest, the alias remapped back, a rung down, and the kill switch, all pulled by the
on-call lead on Tomasz's rota as emergency changes (ch02:163). O-D12's fast burns page and everything else opens a
ticket. The rung down and the kill switch are `budget/oncall.py rung` and `kill`, drilled in step 4; the rate goes live
through the key's `rpm_limit` and `tpm_limit` with LiteLLM's `/key/update` and has no `oncall.py` command yet; the remap
back has no command in the lab at all.

The table ties each signal to something the lab emits and says where nothing does. The gaps:

- A denied egress: nothing. No flow log, firewall log, or NetworkPolicy log is read, and the chat clients' rendering
  rules aren't in the lab.
- A loop that exhausts its step budget: W3's sentence and W2's call count; no line names W2's stop, and W1's is its
  refusal by design.
- A run of refusals: a refusal is a good event, so nothing alerts on their share.
- A planted text restated: W5's prose seam at run time (`refused_words`); W1 to W4 only in chapter 15's offline
  red-team scoring.
- Confident wrong answers reported by people: the outcome SLI for W3 to W5; nothing for W1 and W2.
- A model that changed under its alias: `served_model` on the cost line, except for a provider's update in place under
  an identifier with no version, which leaves it as it was.

### What step 6 can't show

- A real month. The month is a simulation: kept runs drawn at the ledger's volumes, five events of stated shapes, and a
  person's decisions assumed. Its numbers say what these SLOs, alerts, and policy do with those runs, and nothing about
  Larkspur's traffic, which has a daily cycle the month leaves out.
- Rates from the kept runs. The kept runs are few: W2's read failure is one question in 90, which the month turns into
  about 1 percent of a month's questions, and W3's stops are 8 of 48. Their intervals are wide, and the targets don't
  rest on them.
- A person. No kept run holds a person's decision, so every outcome in the month comes from an assumption, and
  nothing in the lab would emit W4's.
- The workbook's 1,000x, which the fact check should settle.
- A pager. No paging service runs (O-D17); the alerts are what would page.
- A probe in production. The probe ran against a fake model, and step 7 sent none; its first live run would be against a
  gateway with a real model behind it.
- The Foundry sessions panel's source, an open fact.
- The response. The month lets every event run its course; a real on-call lead would have ended the regression at W2's
  page, and with it the later signals the month shows.

## The cloud session (step 7)

Step 7 is the one session in the lab account that O-D1 allows, for what only a cloud can show. It ran on 9 November
2026 between 09:37 and 10:11 UTC with profile `book-lab`, given to every tool through the environment alone
(`AWS_SHARED_CREDENTIALS_FILE`, `AWS_CONFIG_FILE` pointing at a file that doesn't exist, `AWS_PROFILE`,
`AWS_DEFAULT_REGION`), every resource in us-east-2 on synthetic data (book D-034, D-036), the budget first, and
everything destroyed and swept in the same session. The code is in `cloud/`: the Terraform, one script per check,
and `cloud_summary.py`, which writes `results/2026-11-09/cloud/summary.md` from the files beside it; every table
below is one of its. `cloud_session.redact` replaces account IDs, access key IDs (with a placeholder that stays
distinct per key, so `join.py` still matches on it), principal IDs, user names, addresses, public IP addresses, and
this machine's paths in every file kept, and the raw records stay in `cloud/_lab/`, which git ignores. Timings
count seconds with `time.perf_counter()` and stamp moments with this workstation's UTC clock.

### The budget first

`terraform apply -target=aws_budgets_budget.session` made three resources before anything else: an SNS topic in
us-east-2, the topic policy that lets AWS Budgets publish to it, and a monthly cost budget of 5 USD with
notifications at 80 and 100 percent of actual spend to the topic, no address anywhere (`cloud/terraform/budget.tf`;
every other resource `depends_on` it). `cloud/cloud_budget.py` read it back through the API at the start and at the
end, with the free plan's state beside it:

|Moment |At (UTC) |Budget |Limit |Actual spend |Notifications |Credits left |
|---|---|---|---|---|---|---|
|start |2026-11-09T09:37:59 |ch16-cloud-session |5.0 USD a month |0.0 USD |80% ACTUAL, OK, SNS sns-topic; 100% ACTUAL, OK, SNS sns-topic |139.38 USD (FREE, ACTIVE) |
|end |2026-11-09T10:07:04 |ch16-cloud-session |5.0 USD a month |0.0 USD |80% ACTUAL, OK, SNS sns-topic; 100% ACTUAL, OK, SNS sns-topic |159.38 USD (FREE, ACTIVE) |

The budget's actual spend read 0.0 both times. The plan's remaining credits
read 139.38 USD at the start and 159.38 at the end: AWS added 20 USD during the session, for a reason the API
doesn't give, and the sweep at the end shows the same figure.

### Transaction Search, in a step of its own

Transaction Search is account-wide, so `cloud/transaction_search.py on` made AWS's three calls (fact sheet 8.2)
before anything sent a span: the resource policy `TransactionSearchAccess` for the two log groups X-Ray writes,
the trace segment destination set to `CloudWatchLogs`, and the Default indexing rule, which read 0.0 percent after
the switch, as before it, and was set to the page's 1 percent. The destination answered `PENDING` and was still
`PENDING` 182 seconds later, after 37 readings; read again eight minutes after the switch it was `ACTIVE`, and both
log groups existed when first read, three minutes after the switch. `off` reversed the three at the end, so the API
does turn it off: the destination back to `XRay`, `PENDING` for the 182 seconds the script waited, still `PENDING`
when read at 10:08:05 and `ACTIVE` at 10:10:40, 7.6 minutes after the switch; the policy and the two groups
deleted; the rule back to 0.0.

|Step |What AWS answered |Seconds |
|---|---|---|
|on: resource policy |put as TransactionSearchAccess |0.3 |
|on: destination to CloudWatchLogs |CloudWatchLogs PENDING |1.3 |
|on: destination ACTIVE |still PENDING after 37 readings |182.6 |
|on: indexing rule after the switch |0.0 percent | |
|on: indexing rule set |1.0 percent, the page's default |182.7 |
|status at 09:46:42 UTC |CloudWatchLogs ACTIVE, indexing 1.0 percent, aws/spans present (0 bytes stored) | |
|status at 10:08:05 UTC |XRay PENDING, indexing 0.0 percent, aws/spans absent | |
|status at 10:10:40 UTC |XRay ACTIVE, indexing 0.0 percent, aws/spans absent | |
|off: destination to XRay |XRay PENDING |0.3 |
|off: destination XRay ACTIVE |not reached after 37 readings |181.7 |
|off: resource policy |deleted |182.0 |
|off: aws/spans |deleted |182.0 |
|off: /aws/application-signals/data |deleted |182.1 |
|off: indexing rule restored |0.0 percent, as before the session |182.2 |

|Setting |Before the session |After `on` |After `off` |
|---|---|---|---|
|Trace segment destination |XRay ACTIVE |CloudWatchLogs PENDING |XRay PENDING |
|Default indexing rule (percent) |0.0 |1.0 |0.0 |
|Resource policy TransactionSearchAccess |no |yes |no |
|Log group aws/spans |no |yes |no |
|Log group /aws/application-signals/data |no |yes |no |

|While on, AWS bills |Quote |Source, date |
|---|---|---|
|span ingestion |$0.35 per GB of Application Signals data ingested for the first 10TB - US East (Ohio) |fact sheet 8.8, AmazonCloudWatch offer file for us-east-2, 2026-11-03 |
|spans indexed as trace summaries |$0.00000075 per spans indexed for USE2-XRay-Spans-Indexed in US East (Ohio); By default you will also index 1% of ingested spans for free as trace summary |fact sheet 8.8 and 8.2, 2026-11-03 |

### The live run through the Collector

`cloud/export_run.py` is step 3's local run with the real exporters: `collector/config.yaml` as it is, the CloudWatch
exporter signed by `sigv4auth` with the session's profile (the extension reads `AWS_PROFILE` and the shared
credentials file as the SDK does), and the Langfuse exporter pointed through the tunnel at the VM (below). Chapter
5's skeleton answered its golden set of 20 questions and the five runs made to be kept, on the rule model and the
fake backends, with the share of the rest at 100 percent, so every trace was kept and both stores should hold every
span. The tap recorded what the processes sent, the sink what left the Collector and when, and the two checks
(`cloud/cloudwatch_spans.py`, `cloud/langfuse_check.py`) then polled the stores for the 25 trace ids.

|Runs |Passed |Traces |Spans sent |Left the Collector |In the span file |Traces with every span left |Share of the rest |decision_wait |Collector exit |Error or warning lines in its log |
|---|---|---|---|---|---|---|---|---|---|---|
|25 |25 |25 |257 |257 |257 |25 of 25 |100.0% |30 s |0 |0 |

Both stores were complete at the first reading, 0.7 seconds into CloudWatch's poll and 2.1 seconds into Langfuse's,
which began 1.9 and 1.5 seconds after the last span left the Collector, so the first readings bound the delay from
above: the last trace had left the Collector 2.6 seconds before CloudWatch's reading and 1.7 seconds before
Langfuse's, the first about 38 seconds before. CloudWatch's own
`ingestionTime` minus each span's start came to 31.4 to 34.8 seconds, 30 of which is the sampler's hold, so the
group took a span in within a few seconds of the Collector sending it.

|Traces expected |Group seen after (s) |Traces seen |Traces complete |Spans found / sent |Events not the run's |First reading (s after the poll began) |Traces complete at the first reading |Had left the Collector (s) before it, min / median / max |ingestionTime minus the span's start (s), min / median / max |
|---|---|---|---|---|---|---|---|---|---|
|25 |0.3 |25 |25 |257 / 257 |0 |0.7 |25 |2.6 / 27.6 / 38.6 |31.4 / 32.4 / 34.8 |

|Record keys |Field that holds the trace id |X-Ray trace summaries in the window |Of them, the run's |Indexing rule (percent) |Application Signals services |Logs Insights query |Rows |Bytes scanned |Records matched |
|---|---|---|---|---|---|---|---|---|---|
|attributes, durationNano, endTimeUnixNano, flags, kind, name, parentSpanId, resource, scope, spanId, startTimeUnixNano, status, traceId |traceId |0 |0 |1.0 |none |Complete |25 |309,817 |257 |

A record in `aws/spans` is one span as JSON (`results/2026-11-09/cloud/export-run/cloudwatch-sample-record.json`):
the trace id in `traceId`, the field the fact sheet couldn't name, the span's own attributes under `attributes`
with six AWS added (`aws.local.service` from `service.name`, `aws.local.operation`, `aws.span.kind`,
`aws.local.environment`, `PlatformType`, `telemetry.extended`), the resource attributes under `resource`, and the
scope with its attributes, so `tailsampling.policy` survives. No field holds the tracestate, so the share each
trace was kept at, which step 2 found a store needs to weight a sampled month, is lost on this path. At the
Default rule's 1 percent, X-Ray indexed none of the 25 traces as a trace summary (a quarter of a trace was the
expectation), so `GetTraceSummaries` had nothing of the run; Logs Insights over the group found every span,
`stats count(*) as spans by traceId` returning 25 rows from 257 records and 309,817 bytes scanned. Application
Signals listed no service for the window, with `aws.local.service` set on every record: the Collector's spans
reach Transaction Search and Logs Insights, as fact sheet 8.2 said the chapter could promise, and the service and
agent views stay unmeasured here.

|Langfuse |Traces expected |Seen |Complete |First reading (s after the poll began) |Traces complete at the first reading |Had left the Collector (s) before it, min / median / max |Traces with every span id |Gateway spans with a cost |Cost equal to gen_ai.usage.cost |Tokens equal |Tracestate anywhere |Span attributes kept as metadata |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
|4.74.0 |25 |25 |25 |2.1 |25 |1.7 / 26.7 / 37.7 |25 of 25 |45 |45 |45 |no |yes |

|Observation types |Count |
|---|---|
|AGENT |25 |
|GENERATION |48 |
|SPAN |121 |
|TOOL |63 |

Langfuse 4.74.0 holds every span of every trace under the span's own id, typed from the GenAI operation names: the
harness's `invoke_agent` as AGENT, the gateway's `chat` as GENERATION, the tool calls as TOOL, the rest as SPAN. On
all 45 generation observations with a cost, `costDetails.total` equals the span's `larkspur.cost_usd` and
`usageDetails` equals its token counts, so Langfuse read the `gen_ai.usage.cost` the Collector copies on this
pipeline alone (step 3), and it shows in the observation's metadata as `attributes.gen_ai.usage.cost` beside every
other span, resource, and scope attribute, 23 keys in all; the three generations without a cost are the calls that
failed. The tracestate appears nowhere. Reading it back needed the right fields: the v2 observations route returns its core
and basic field groups by default, with no usage, cost, model or metadata, and the fuller rows come with
`fields=core,basic,time,io,metadata,model,usage,metrics,trace_context`, which the instance's own OpenAPI document
lists; the v1 detail routes (`/api/public/observations/{id}`, `/api/public/traces/{id}`, `/api/public/metrics`)
answer 404 with "not available on deployments running in Langfuse v4 events_only mode".

|Instance type |Ready after launch (s) |Image pull (s) |`up` to healthy (s) |Langfuse health |Pinned tags |Docker |Compose |Cores |Memory (MB) |Tunnel |
|---|---|---|---|---|---|---|---|---|---|---|
|m7i-flex.large |119.0 |40 |25 |{"status": "OK", "version": "4.74.0"} |pinned |29.1.3, build 29.1.3-0ubuntu3~24.04.2 |2.40.3+ds1-0ubuntu1~24.04.1 |2 |7776 |open-tunnel to port 22, ssh -L 3000 |

|Image |Digest |
|---|---|
|redis:7 |sha256:2e3eb11462c4... |
|cgr.dev/chainguard/minio:latest |sha256:a1ac4589a5f8... |
|docker.langfuse.com/langfuse/langfuse-worker:4.74.0 |sha256:d9cf97c0ae7d... |
|clickhouse/clickhouse-server:26.3.62.3 |sha256:de3e47c64078... |
|docker.langfuse.com/langfuse/langfuse:4.74.0 |sha256:f409386b80aa... |
|postgres:17 |sha256:ff87138949ad... |

The VM is `cloud/terraform/vm.tf`: Ubuntu 24.04.5 from Canonical's published parameter, Docker 29.1.3 and the
Compose plugin 2.40.3 from Ubuntu's own packages, and Langfuse from the Compose file of its v4.74.0 tag, vendored in
`cloud/langfuse/` (its SHA-256 is in the tests) with an override that pins the two floating `:4` images to 4.74.0;
the pinned tags were served, and the digests of all six images are above. The first apply asked for the t3.xlarge
Langfuse's guide names and the free plan refused it: "The specified instance type is not eligible for Free Tier"
(`results/2026-11-09/cloud/terraform-apply-1-errors.txt`, which also holds EC2's refusal of three security group
rule descriptions for an apostrophe, chapter 6's finding again). The session applied again with m7i-flex.large, the
largest eligible type at 2 vCPU and 8 GiB, and the stack was healthy 119 seconds after launch with 2,976 MB in use.
No security group rule names the internet: the VM accepts traffic from the Instance Connect endpoint's group alone,
on 22 and 3000, and has a public address for its outbound pulls only. The endpoint's own tunnel refused Langfuse's
port, "The specified RemotePort is not valid. Specify either 22 or 3389", so `cloud/tunnel.py` opened the tunnel to
port 22 and SSH forwarded port 3000 through it, with a key pair made for the session and pushed for 60 seconds at a
time; the Collector exported through that. The VM was destroyed 15.4 minutes after launch, once the detailed
read-back above was recorded.

### Bedrock with the trace id in requestMetadata

O-D2 gives the gateway the job of passing `trace_id` and `workflow` in Bedrock's `requestMetadata`.
`cloud/request_metadata_hooks.py` is that change as a LiteLLM callback of this step's own, registered ahead of
chapter 5's, which stays unchanged: it reads the request's `metadata.trace_id` and its `workflow:` tag the way
chapter 5 reads them and writes the two pairs as the request's `requestMetadata`, in place of anything the caller
sent under that key, so the gateway owns the two names; LiteLLM 1.106.6 writes them into the Converse body
(`tests/test_cloud_scripts.py` drives its transformation offline). `cloud/bedrock_calls.py` made four Nova Lite
calls with a one-line synthetic prompt: the Canada call through the gateway with chapter 6's design
(`cloud/litellm.bedrock-ca.yaml`), two logged calls in us-east-2 through the gateway with the In-Region deployment
behind the alias (`cloud/litellm.bedrock-us.yaml`), one with text delivery off as Terraform leaves it and one with
it switched on by API, and the US profile from us-east-2 with the SDK and the same metadata (item 4).

|Call |Path |Answered |Tokens in / out |Gateway cost (USD) |Cost lines / spans |Invocation record |Record after the call (s) |requestMetadata in the record |Text fields |inferenceRegion in the record |
|---|---|---|---|---|---|---|---|---|---|---|
|Canada profile, chapter 5's W3 manifest, regions [ca-central-1] |gateway, litellm.bedrock-ca.yaml, W3 larkspur-chat (confidential), called in ca-central-1 |no: 400 request refused: 'larkspur-chat' serves from ca-west-1, outside the regions of 'w3-incident' |none / none |none |1 / 0 |not readable here (ca-central-1) | | | | |
|Canada profile, chapter 6's W3 manifest, regions [ca-central-1, ca-west-1] |gateway, litellm.bedrock-ca.yaml, W3 larkspur-chat (confidential), called in ca-central-1 |yes |99 / 2 |0.000007 |2 / 1 |not readable here (ca-central-1) | | | | |
|In-Region us-east-2, text delivery off |gateway, litellm.bedrock-us.yaml, W2 larkspur-chat (internal), Nova Lite In-Region us-east-2 |yes |99 / 2 |0.000006 |1 / 1 |found |12.2 |{"workflow": "w2-ops-assistant", "trace_id": "280e7796708b45d0b8b1eafa04a57511"} |none |absent |
|In-Region us-east-2, text delivery on |gateway, litellm.bedrock-us.yaml, W2 larkspur-chat (internal), Nova Lite In-Region us-east-2 |yes |99 / 2 |0.000006 |1 / 1 |found |11.4 |{"workflow": "w2-ops-assistant", "trace_id": "bfd8a29fb80447f5bf1ceb2899434154"} |inputBodyJson, outputBodyJson |absent |
|US profile from us-east-2 (SDK) |the SDK's Converse in us-east-2 on us.amazon.nova-lite-v1:0, with the same requestMetadata |yes |8 / 3 |none |SDK call |found |11.3 |{"workflow": "w2-ops-assistant", "trace_id": "21e37613001e4962af4e937a4d9d9daa"} |inputBodyJson, outputBodyJson |us-west-2 |

|ca-central-1, anything but a model call |Answer |
|---|---|
|get logging configuration |refused (AccessDeniedException) |
|describe log groups |refused (AccessDeniedException) |
|cloudtrail lookup |refused (AccessDeniedException) |

|Call |Event found |awsRegion |inferenceRegion (CloudTrail) |inferenceRegion (log) |Request ID equals the log's |Event name |
|---|---|---|---|---|---|---|
|us text off |yes |us-east-2 |absent |absent |yes |Converse |
|us text on |yes |us-east-2 |absent |absent |yes |Converse |
|us profile |yes |us-east-2 |us-west-2 |us-west-2 |yes |Converse |

The Canada call was refused first, by chapter 5's own rules: W3's manifest in `labs/ch05/manifest` names
ca-central-1 alone, the Canada profile serves from ca-central-1 and ca-west-1, and the gateway compares every
Region a profile serves from with the manifest's (O-D11), so the request ended with a `refused` cost line and no
model call. Under chapter 6's W3 manifest, grown by ca-west-1 for that reason, the call went through: 99 input and
2 output tokens, 787 ms, a cost line with Region ca-central-1 and deployment `nova-lite-ca`, a `chat` span, and a
`fallback_disabled` line, since Confidential data may not fall back to Ohio. What the Canada call left in the
account can't be read from here: the lab account may enable logging, list log groups, and look up CloudTrail in
us-east-2 alone (book D-034), and ca-central-1 refused all three, so Larkspur's own account would hold that record
and this one holds the gateway's cost line and span.

The two us-east-2 calls settled what the fact sheet left open. With text delivery off, a text call is logged: the
record holds the token counts, the content types, `requestMetadata` with the trace id and the workflow, and no
text. With it on, the same record gains `inputBodyJson` and `outputBodyJson`, the prompt and the answer. Each
record was there at the second poll, 11 to 12 seconds after the call; the first, a second after it, found nothing.
`inferenceRegion` is in a record only when a profile served the call: absent on the two In-Region calls, `us-west-2` on the US profile called from us-east-2,
the same value CloudTrail's `additionalEventData.inferenceRegion` gives for that event, and the invocation log's
`requestId` equals CloudTrail's `requestID` on all three. CloudTrail's `additionalEventData` also carries the
token counts, so the audit log alone prices a call. The US profile answered the call made from us-east-2: the
sign-up page's sentence on cross-Region features (fact sheet 8.6) did not refuse it, so O-D11's test found no
refusal. The first run of the script, before the Canada call moved under chapter 6's manifest, made the three
us-east-2 calls as well; their tokens count in the spend estimate.

### The tool role with the trace id

`cloud/terraform/iam.tf` makes `w3-incident-get-pod-status`, chapter 6's name for W3's read tool, with the amended
O-D2's trust policy: the `workflow` and `trace_id` session tags required, the trace id 32 characters long
(`StringLike` with 32 single-character wildcards, since IAM can't require hexadecimal), no other tag key, and the
role session name pinned to the engineer's object ID, a dot, and the trace id's first 16 characters. The role may
make one read, `ec2:DescribeInstances`. `cloud/tool_role.py run` assumed it for the trace id of the live run's first
golden case, through STS's us-east-2 endpoint so the event lands in that Region's history, made the read, and tried
the shapes the policy must refuse.

|Check |Result |
|---|---|
|AssumeRole with the trace id tag and the session name |allowed; session `3f2b9c1e-6a4d-4e8b-9c7f-1a2b3c4d5e6f.5de3012d83cd461e`; 0.317 s |
|One read under it (ec2:DescribeInstances) |answered; 0.344 s |
|AssumeRole with no trace_id tag |refused (AccessDenied) |
|AssumeRole with chapter 6's session name, the object ID alone |refused (AccessDenied) |
|AssumeRole with a tag key the policy doesn't list |refused (AccessDenied) |
|AssumeRole with a trace id of the wrong length |refused (AccessDenied) |

The first attempt failed on the trust policy's shape. With `sts:AssumeRole`, `sts:TagSession`, and
`sts:SetSourceIdentity` in one statement under the four conditions, STS answered "not authorized to perform:
sts:TagSession", while the policy simulator allowed all three actions for the caller, the organization's policies
included; both answers were read on the console, and neither was kept in the results. The session name condition
is met for `sts:AssumeRole`, whose request context carries `sts:RoleSessionName`, and not for the permissions-only
`sts:TagSession`, so the trust policy now has two statements: the session name is required on `AssumeRole` alone,
the tags on all three (`iam.tf` says so). Chapter 6's module puts `sts:SourceIdentity` beside `sts:TagSession` in
one statement, a shape this session didn't test; #12 should check it.

|Event |Seen after the call (min) |Event time |
|---|---|---|
|AssumeRole |4.4 |2026-11-09T10:02:10Z |
|DescribeInstances |4.4 |2026-11-09T10:02:10Z |

|Events of the two sessions |AssumeRole |DescribeInstances |With userIdentity.accessKeyId |Denied (errorCode) |AssumeRole with the trace_id tag |Polled (s) |
|---|---|---|---|---|---|---|
|23 |2 |21 |23 |9 |2 |0.6 |

|Store |Records |
|---|---|
|harness log |3 |
|tool server log |1 |
|gateway cost lines |2 |
|spans |11 |
|CloudTrail |13 |

CloudTrail's event history held both sessions' events when first read, 4.4 minutes after the calls: 2 AssumeRole
events, each with the `trace_id` tag in its request parameters, and 21 DescribeInstances events, 9 of them the
deny-all drill's refusals, all 23 with `userIdentity.accessKeyId` filled in, the field the fact sheet said might be
empty. `join.py` on the live run's stores and the kept events (`results/2026-11-09/cloud/cloudtrail-events.json`,
`join.txt`) printed the run from all five: 3 harness lines, 1 tool server line, 2 cost lines, the 11 spans as a
tree, and 13 CloudTrail records, the AssumeRole matched by its tag and the 12 reads by the session name inside
`userIdentity.arn`; given one DescribeInstances event, it found the one trace id behind it.

### The deny-all

The identity half of the kill switch is step 4's `budget/identity.py`, run here through its own functions on the
tool role with the session above already issued, a read every half second.

|Step |Seconds |Detail |
|---|---|---|
|`identity.py pull` answered by IAM |0.151 |1 role; policy larkspur-kill-switch put |
|calls that still passed after the pull |9 |one read every 0.5 s |
|first AccessDenied on credentials already issued |8.232 |code UnauthorizedOperation |
|`identity.py release` answered by IAM |0.159 |revoke statement alone, cut-off at the release |
|a session issued after the release |0.042 |issued |
|its first successful read |8.197 |7 refusals before it |
|the earlier session after the release | |still refused (UnauthorizedOperation) |
|`release --purge` |0.161 |deleted; the later session then reads |

IAM answered the pull in 0.151 seconds; nine reads on the issued credentials still passed, and the tenth, 8.232
seconds after the pull, was refused with "explicit deny in an identity-based policy". After the release, a session
issued two seconds later was refused seven times and read successfully 8.197 seconds after the release, while the
session issued before it stayed refused by the revoke statement, and after `--purge` the later session read on.
So the book's "under a minute" held with room on both sides, at about eight seconds each way, one account's
measurement on one day, as fact sheet 8.3 warned; the clock is this workstation's.

### Cost Explorer

Cost Explorer answered, so the author had opened it in the console (the checkpoint listed it as the author's
optional step), and the filter on the product attribute `model` set to Nova Lite worked at the first request,
which cost one US cent.

|Day (the bill's, UTC; the ledger's, Toronto) |Bill's usage types |Bill input tokens |Bill output tokens |Bill cost (USD) |Ledger calls |Ledger tokens in / out |Ledger cost (USD) |
|---|---|---|---|---|---|---|---|
|2026-10-29 |none |0 |0 |0 |48 |81,439 / 4,260 |0.006303 |
|2026-10-30 |CAN1-NovaLite-input-tokens, CAN1-NovaLite-output-tokens, USE2-NovaLite-input-tokens, USE2-NovaLite-output-tokens |88,246 |8,214 |0 |0 |0 / 0 |0 |

|Bill day (UTC) |Ledger day (Toronto) |Usage types |Bill tokens in / out |Ledger tokens in / out |Ledger calls |Bill over ledger, input |Bill over ledger, output |Bill cost (USD) |Bill at the table's price (USD) |Ledger cost (USD) |At list price, bill over ledger |
|---|---|---|---|---|---|---|---|---|---|---|---|
|2026-10-30 |2026-10-29 |CAN1-NovaLite-input-tokens, CAN1-NovaLite-output-tokens |88,240 / 8,211 |81,439 / 4,260 |48 |1.084 |1.927 |0 |0.007749 |0.006303 |1.229 |

W1's run of 29 October (its Toronto date; the run kept no clock) sits on 30 October in the bill, which Cost
Explorer keeps in UTC days, with the Canadian usage types, metered in thousands of tokens. Aligned, the bill holds
1.084 times the ledger's input tokens and 1.927 times its output tokens: 6,801 input and 3,951 output Nova Lite
tokens that the ledger's 48 calls do not hold, and no kept record says what made them. The bill's cost reads 0 on
every line, the free plan's credits absorbing it, so the comparison is at the dated table's price, where the bill's
tokens come to 1.229 times the ledger's cost. The two USE2 lines, 6 input and 3 output tokens, are chapter 6's
sandbox check of 30 October (`labs/ch06/results/2026-10-30/first-apply.json`).

### Teardown

The VM went first, 36 seconds from the command to `terminated`. After the budget's last read-back,
`terraform destroy` removed the other 22 resources in 20 seconds, the Instance Connect endpoint the slowest at 13.
`cloud/leftovers.py` then looked for every kind the session had made, and the author's read-only
sweep, kept outside this repository, for everything that bills:

|Terraform |At (UTC) |Seconds |Result |
|---|---|---|---|
|vm destroy |2026-11-09T10:01:17 |36 |terraform destroy -target=aws_instance.langfuse; instance states after: ['terminated'] |
|destroy |2026-11-09T10:11:00 |20 |Destroy complete! Resources: 22 destroyed |

|cloud/leftovers.py, after the destroy |Found |
|---|---|
|instances_not_terminated |[] |
|volumes |0 |
|elastic_ips_allocated |0 |
|vpcs |0 |
|instance_connect_endpoints |[] |
|iam_roles |{"w3-incident-get-pod-status": {"exists": false}, "ch16-cloud-invocation-logging": {"exists": false}} |
|log_groups |{"/aws/bedrock/model-invocations-ch16": "absent", "aws/spans": "absent", "/aws/application-signals/data": "absent"} |
|other_log_groups |[] |
|invocation_logging |false |
|xray_destination |{"Destination": "XRay", "Status": "PENDING"} |
|xray_indexing_percent |[["Default", 0.0]] |
|logs_resource_policies |[] |
|budgets |[] |
|sns_topics |[] |

|tools/cloudcheck/aws_sweep.py |Found |
|---|---|
|plan |FREE ACTIVE | credits left: {'amount': 159.38, 'unit': 'USD'} | expires: 2027-04-28 |
|EC2 instances not terminated |0 |
|NAT gateways available |0 |
|Elastic IPs |0 |
|VPCs besides the default |0 |
|VPC interface endpoints |0 |
|EBS volumes |0 |
|load balancers |0 |
|EKS clusters |[] |
|RDS instances |0 |
|ECS clusters |0 |
|AgentCore runtimes |[] |
|Bedrock provisioned throughputs |0 |
|SageMaker endpoints |0 |
|OpenSearch domains |0 |
|Secrets Manager secrets |0 |
|customer KMS keys by state |{'PendingDeletion': 4} |
|S3 buckets |0 |
|CloudWatch log groups, stored MB |0.0 |
|budgets |[] |

The four KMS keys pending deletion are chapter 6's, as the checkpoint has them. Transaction Search's destination
read `XRay PENDING` at the sweep and `XRay ACTIVE` at 10:10:40, under three minutes later, its final state, with the
indexing rule at 0.0 percent, no resource policy, and no span group, as before the session.

### The spend estimate

At list price, from the quantities the session recorded and the prices of fact sheet 8.8 as the dated table holds
them:

|Service |Quantity |Price |Source, date |Estimate (USD) |
|---|---|---|---|---|
|EC2, the Langfuse VM |0.256 instance hours of m7i-flex.large |$0.09576 per On Demand Linux m7i-flex.large Instance Hour |fact sheet 8.8 (ledger/prices.yaml), read 2026-11-03 |0.0245 |
|EBS, its gp3 disk |30 GiB for 0.256 hours |$0.08 per GB-month of General Purpose (gp3) provisioned storage - US East (Ohio) |fact sheet 8.8 (ledger/prices.yaml), read 2026-11-03 |0.000842 |
|Public IPv4 address |0.256 hours |$0.005 per In-use public IPv4 address per hour |fact sheet 8.8 (ledger/prices.yaml), read 2026-11-03 |0.00128 |
|CloudWatch, spans ingested |257 spans at about 1000 bytes each (the pricing page's own assumption) |$0.35 per GB of Application Signals data ingested for the first 10TB - US East (Ohio) |fact sheet 8.8 (ledger/prices.yaml), read 2026-11-03 |0.00009 |
|CloudWatch, spans indexed |0 of the run's traces indexed, inside the free 1 percent |$0.00000075 per spans indexed for USE2-XRay-Spans-Indexed in US East (Ohio) |fact sheet 8.8 (ledger/prices.yaml), read 2026-11-03 |0 |
|CloudWatch Logs Insights |309,817 bytes scanned |$0.005 per GB log data scanned by CloudWatch Logs Insights queries - US East (Ohio) |fact sheet 8.8 (ledger/prices.yaml), read 2026-11-03 |0.000002 |
|Bedrock, Nova Lite in us-east-2 |412 input and 14 output tokens, the first run's 3 calls included |$0.00006 per 1K tokens for Nova Lite-input-tokens in us-east-2 (Ohio) |fact sheet 8.8 (ledger/prices.yaml), read 2026-11-03 |0.000028 |
|Bedrock, Nova Lite through the Canada profile |99 input and 2 output tokens |$0.000064 per 1K tokens for CAN1-NovaLite-input-tokens in Canada (Central) |fact sheet 8.8 (ledger/prices.yaml), read 2026-11-03 |0.000007 |
|Cost Explorer API |1 request(s) |$0.01 per API Request |fact sheet 8.8 (ledger/prices.yaml), read 2026-11-03 |0.0100 |
|EC2 Instance Connect endpoint |one endpoint |no charge (fact sheet 8.6: "There is no additional cost for using EC2 Instance Connect Endpoints.") | |not priced |
|AWS Budgets, SNS, IAM, STS, CloudTrail event history, the VPC, the invocation log's records |one budget, one topic, two roles, the lookups, three records |no entry in the dated table | |not priced |
|Total of the priced lines | | | |0.0368 |

About 4 US cents at list price, two thirds of it the VM's quarter hour and most of the rest Cost Explorer's one
request; the free plan's credits carried all of it, and the budget's actual spend never left 0.0.

### What the chapter takes from here

- The trace id reaches every store it was meant to reach. The invocation log records `requestMetadata` with the
  trace id and the workflow whether text delivery is on or off, CloudTrail shows the session name in every later
  event's `userIdentity.arn` and the tag on the AssumeRole, and `join.py` prints one run from five stores and
  finds the run behind one audit event.
- Two trust policy shapes, one tried and one measured: the amended O-D2's conditions need two statements, since
  `sts:RoleSessionName` isn't in `sts:TagSession`'s request context; chapter 6's one-statement shape is untested
  and should be.
- The deny-all takes about eight seconds to bite and about eight to lift, on credentials already issued, in this
  account on this day.
- A profile's serving Region is in the invocation log (`inferenceRegion`) and in CloudTrail, and only for a
  profile; the US profile served a us-east-2 call from us-west-2, and this account's plan didn't refuse it.
- Transaction Search keeps every span of a trace in `aws/spans` with the sampling policy and without the
  tracestate, indexes 1 percent as trace summaries (none of 25 traces here), and lists no service for a Collector's
  spans; the switch on and off settles in minutes, and the API turns it off.
- Langfuse 4.74.0 takes the Collector's spans whole, maps the GenAI operation names to its observation types, and
  prices a generation from `gen_ai.usage.cost` to the gateway's own figure; its v4 API hides usage and cost unless
  asked for by field group, and the v1 detail routes are gone in events-only mode.
- The free plan refuses instance types outside its eligible list, and 8 GiB ran Langfuse's six containers for a
  lab's traffic; the Instance Connect endpoint tunnels to ports 22 and 3389 alone.
- Cost Explorer bills by UTC day and holds every call, the ledger holds kept runs by local date, so a reconciliation
  shifts the day and finds the bill above the ledger, by 6,801 input and 3,951 output tokens here, for a reason the
  records don't give; with credits, the bill's cost line is zero, and the comparison runs at the table's price.
- Chapter 5's W3 manifest names one Canadian Region and the Canada profile serves from two, so chapter 5's rules
  refuse chapter 6's design until the manifest is chapter 6's: a sentence for chapter 16 where it tells O-D11.

## The model register and the upgrade path (step 8)

Step 8 builds O-D14 on this workstation: one register for the three clouds and the local models, the 90-day rule as
an alert, and the upgrade path run once for real, with Gemma 4 12B as the candidate for W2's alias and gpt-oss-20b,
the model behind it today, as the control. Everything ran on 9 November 2026 between 11:41 and 11:54 UTC against the
portable Ollama 0.40.13 on 11435, the one server on the one GPU; no cloud was called and no credential was used. The
code is in `lifecycle/`, the files in `results/2026-11-09/lifecycle/`, and every table below is in its `summary.md`,
which `lifecycle/upgrade.py --only summarize` writes from the files beside it. W2 is the workflow because its golden
set is the cheapest to run end to end (25 questions, two model calls and one read at the median, about two seconds
each), its data is Internal, and both local models already have kept runs on it, so chapter 15's baseline had
something to hold the candidate to.

### The register

`lifecycle/register.yaml` merges the registers of chapters 6, 7, and 8 (`labs/ch06/models.yaml`,
`labs/ch07/models.yaml`, `labs/ch08/models.yaml`) with the local models the gateways serve. A model has one
lifecycle: its stage in its provider's scheme, the date it retires where the provider has published one and the
earliest possible date where it hasn't, its replacement, and the pin a gateway holds it by. It has one or more
deployments, each with the identifier the gateway uses, the aliases it serves, its Region, and the configurations or
the Terraform file that name it. Every fact carries its source and the date it was read: the chapters' registers of
28 and 29 October, the fact sheets, and Ollama's `/api/tags` of 9 November. Claude Haiku 5.5 is in it as Larkspur's
candidate for `larkspur-chat`, from the header of chapter 6's gateway configuration and fact sheet 11.10, with the
note that the lab's account can't call it. The stages are the providers' own (AWS's Active, Legacy, and EOL; Google's
preview, GA, and retired; Foundry's Preview, GA, Legacy, Deprecated, and Retired) and, for a self-hosted model, the
lab's three, since chapter 9 pins weights and names no lifecycle: candidate, serving, and retired.

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

The Behind column lists the aliases of every configuration the register names, the Gemma copies of chapter 9's and
W1's and W2's gateways (evaluation files) and step 8's staging and canary files included, so Gemma 4 12B appears
behind both chat aliases while Larkspur runs on gpt-oss-20b.

|Cloud|Models|
|---|---|
|aws|6|
|google|2|
|azure|2|
|local|3|
|all|13|

The pins differ by host, and the register says so. A Bedrock ID carries its version (`amazon.nova-lite-v1:0`,
`anthropic.claude-3-haiku-20240307-v1:0`), a Foundry model its name and version (`gpt-4o 2024-11-20`), and Google
versions by the model ID itself. The two Claude 5.5 entries are the exception: `anthropic.claude-sonnet-5-5` and
`ca.anthropic.claude-haiku-5-5` carry no version and no date, so a change to the model under either is invisible to
this register, and only a rerun of the golden sets, chapter 15's live job, would show it. The chapter states that
limit.

A local model's pin is the digest Ollama reports for its tag, on the server that reports it. `register.py --digests`
read the portable 0.40.13 on 9 November, and the three pins matched:

|Tag|Pinned digest|Reported by Ollama 0.40.13|Matches|Size|
|---|---|---|---|---|
|gpt-oss:20b|f38aa0c53da5|f38aa0c53da5|yes|13.79 GB|
|gemma4:12b|6114515d63c1|6114515d63c1|yes|8.02 GB|
|qwen3-embedding:0.6b|ac6da0dfba84|ac6da0dfba84|yes|0.64 GB|

The same tag, `gpt-oss:20b`, reported `a0b38d0b19f7` on Ollama 0.22.1 on 3 November (chapter 15's judge run,
`labs/ch15/results/2026-11-03/judge-w2-gpt-oss-20b.json`) and reports `f38aa0c53da5` on 0.40.13 now, so the
server's version is part of a local pin and the register records both. The Ollama on this
workstation's PATH, 0.22.1 when the labs' earlier runs used it, reports client 0.40.14 today and wasn't running; step
8 used the portable server alone. The vLLM deployment of chapter 9's part 2 is pinned by its weights' revision,
`6cee5e81ee83917806bbde320786a8fb61efebee`, and the SHA-256 list of `labs/ch09/k8s/weights-digests.yaml`.

`register.py --check` reads every LiteLLM configuration the register names, 14 files across chapters 6 and 9, step
7's two, step 8's three, and W1's and W2's gateways, and compares deployment by deployment: the id must be a register
deployment that names the file; the model string's identifier, the alias, the Region, and the hosting must be the
register's; and every register deployment that names a file must be in it. Chapter 7's `runtime.tf` and chapter 8's
`variables.tf` are read the way the chapters' own tests read them. Chapter 5's configuration and steps 4 and 5's are
excluded, and the register says why: their deployments are fakes. On 9 November the check found no problem: 13
models, 6 that Larkspur runs on, 14 deployments.

### The retirement alert

`lifecycle/alerts.yaml` writes the rule the way `slo/alerts.yaml` writes the others, and `lifecycle/retirement.py`
evaluates it over the register for a date. Chapters 7 and 8 hold the 90-day rule as a test that fails 90 days before
a pinned model retires; here it is a ticket to the model's owner, the alias move. O-D15's review window puts every
model within 180 days of retirement in the monthly review, pinned or not. A pinned model past its date pages the
platform's on-call, since its calls fail (ch05:498). Chapter 6's Legacy rule is a ticket while a pinned model sits in
a provider's notice stage, AWS's Legacy or Foundry's Legacy and Deprecated. A model with no published date fires
nothing, and its row shows the earliest date the provider gives. The three dates below are the day of the run, a day
inside gpt-4o's 90 days, and a day past its retirement:

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

On 9 November nothing Larkspur runs on retires within 90 days. The review window holds four models: gpt-4o (156
days, in Legacy, which also tickets the notice), text-multilingual-embedding-002 (143 days, with no replacement
processed in Canada, as chapter 7's register found), and two that Larkspur doesn't run on, Llama 3 70B and
gpt-4.1-mini. Claude 3 Haiku retires in four days and is nobody's at Larkspur, so it gets a review row and no ticket.
Eight models have no published date, Nova Lite among them, whose earliest date passed in December 2025, so a Legacy
notice can come any day with at least six months before the end of life. The tickets for gpt-4o and the embedding
model fall on 14 January and 1 January 2027.

### The candidate behind the alias on staging

`lifecycle/litellm.staging.yaml` puts Gemma 4 12B behind `larkspur-chat` and leaves `larkspur-chat-restricted` on
gpt-oss-20b, since W2's manifest names both aliases and chapter 5's rules check the manifest's aliases against the
configuration. Chapter 15's live job (`labs/ch15/ci/live.py`) ran W2's 25 questions on it through W2's own harness
and three servers, replayed the outputs through step 2's layers, had the other local model, gpt-oss-20b, judge the
prose as E-D4 requires, and set the result against the baseline as the gate does. That baseline is the one chapter
15 built from the kept runs, W2's of 2 November on gpt-oss-20b judged by Gemma 4 12B, since no live run has been
accepted yet; the Baseline column below is that run. `upgrade.py` imports the job and points its W2 configuration at
the staging file; nothing in chapter 15 changed. The set took 44 seconds and
56 calls; the judge read 19 outputs (W2's five fixed refusals and one empty answer aren't judged) and called 17 right
and 2 wrong, none withheld, since no live text repeats a sampled one.

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

Nine checks held and one regressed. `trajectory.allowed` lost w2-01 and w2-05, where Gemma read what the cases don't
name (the alerts and the events for "Is claims-api healthy?", a metric series for w2-05), two cases where the
threshold allows one. Gemma's kept W2 run of 2 November passed that check on all 25, and on these servers
temperature 0 doesn't make a reply repeat (chapter 15's thresholds say so), so whether this is Gemma's habit or the
run's noise is a question for a second live run; the rule doesn't wait for one. W2's own scorer rose from 22 to 23 of
25, which the gate reports and doesn't gate.

The pins the gate lists are what a remap changes by design; they go to the review that accepts the new baseline, and
the decision doesn't read them:

|Pins|What differs from the baseline|
|---|---|
|w2|the alias map changed: larkspur-chat ollama_chat/gpt-oss:20b -> ollama_chat/gemma4:12b|
|w2|ollama_chat/gemma4:12b: the baseline holds no digest for it|
|w2|ollama_chat/gpt-oss:20b: the baseline holds no digest for it|
|the judge|the judge's model changed: gemma4-12b -> gpt-oss-20b|
|the judge|the judge's served changed: ollama_chat/gemma4:12b -> ollama_chat/gpt-oss:20b|
|the judge|the judge's alias map changed: larkspur-chat ollama_chat/gemma4:12b -> ollama_chat/gpt-oss:20b; larkspur-chat-restricted ollama_chat/gemma4:12b -> ollama_chat/gpt-oss:20b|
|the judge|the judge's digest changed: 6114515d63c1 -> f38aa0c53da5|

The judge's side reads backwards from the baseline's because E-D4 has the other local model judge: with Gemma behind
the alias, gpt-oss-20b judges, and the baseline was built with Gemma judging gpt-oss-20b's runs. The digests the
baseline holds none of are the two the register pins.

|Judge|Outputs read|Withheld as sampled texts|Right|Wrong|No verdict|
|---|---|---|---|---|---|
|gpt-oss-20b|19|0|17|2|0|

|Tokens|Calls|Prompt|Completion|
|---|---|---|---|
|the candidate, W2's set|56|62,595|2,116|
|the judge|19|11,728|6,694|

Which part of E-D9 ran: the live job end to end for one set, with the set, the layers, the judge, the result file,
and the comparison. The other five sets did not run, so the job marks the result partial and keeps it out of
`labs/ch15/live/`, and the gate as chapter 15 built it, which gates complete runs against a baseline whose pins
match, fails the comparison on the partial run and the unmatched pins and lists the regression beside them. The path
reads the W2 rows the gate computed, which is what the author's review would read, and `gate.md` is the gate's own
rendering of the whole.

### The canary

`lifecycle/litellm.canary.yaml` gives `larkspur-chat` two deployments, gpt-oss-20b at weight 3 and Gemma 4 12B at
weight 1. LiteLLM 1.106.6's simple-shuffle weights the choice by `weight`, then `rpm`, then `tpm`, so a quarter of
the alias's calls go to the candidate, and chapter 5's rules check both deployments against the grid and the
manifest's Regions. The gateway's cost line names the deployment that served each call, which is how the arms are
told apart. `lifecycle/canary.py` started that gateway once and sent W2's 25 questions through W2's harness four
times, each pass a run of its own.

|Deployment|Arm|Model|Weight|Share asked|Thinking|num_ctx|
|---|---|---|---|---|---|---|
|local-gpt-oss-20b-chat|control|ollama_chat/gpt-oss:20b|3|75%|model default|16,384|
|candidate-gemma4-12b-chat|candidate|ollama_chat/gemma4:12b|1|25%|False|16,384|

|Passes|Cases a pass|Runs|Calls|Failed calls|Calls a run (median)|Seconds|Ollama|Swaps: loads of each model|Both models resident at once|
|---|---|---|---|---|---|---|---|---|---|
|4|25|100|196|0|2|554|0.40.13|gemma4:12b 39, gpt-oss:20b 38|no|

Both models sit on one server because the two don't fit the card together (chapter 9 measured 12,549 and 8,811
MiB) and two servers on one card would push the second model to the CPU. The server swapped them as the weight
alternated: Ollama loaded Gemma 39 times and gpt-oss 38 times in the 554 seconds, never held both, and a load took
4.4 seconds at the median and 6.4 at most, as `canary.py` saw on `/api/ps` every half second. The call that followed
a swap paid for it: 77 of the 196 calls did, and because a candidate call follows a control call three times in
four, 39 of the candidate's 54 calls paid where 38 of the control's 142 did.

|Arm|Calls|Share served|Failed|Latency ms, median|p95|Calls after a swap|Median after a swap|Median with no swap|Load s, median|Load s, max|Load s, total|
|---|---|---|---|---|---|---|---|---|---|---|---|
|control|142|72.45%|0|928|5,751|38|5,228|647|4.4|6.35|166|
|candidate|54|27.55%|0|4,678|5,192|39|4,718|372|4.4|5.86|174|

With no swap in the way, Gemma answered a W2 call in 372 ms at the median against gpt-oss-20b's 647, on 1,111 prompt
tokens a call against 969 and 39 completion tokens against 128, since gpt-oss-20b's completions carry its reasoning.

A weight routes calls and a W2 run makes two at the median, so the arms split the runs three ways: 49 runs the
control served alone, 11 the candidate served alone, 36 both served, and 4 that no model served (W2's out-of-scope
question, which the harness refuses before any call). The SLIs of `slo/slis.py` are computed over each group and over
the runs each arm served at all, where a mixed run counts for both arms, as does its failure:

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

Success was 100 percent on every arm and in every group: 42 answers and 5 refusals by rule on the candidate's 47
runs, 77 and 8 on the control's 85, and no step-budget stop, no read failure, and no failed call. The latency SLI
as measured reads the swaps: 31 of the candidate's 47 runs and 69 of the control's 85 finished inside 10 seconds,
66.0 and 81.2 percent, both under W2's 95 percent target, and in the mixed group, where every run paid at least one
load, 20 of 36. With each run's loads taken out, measured
from the watcher's samples as the time from the call's start to the model showing as loaded, every run of both arms
is inside the threshold, at 1.5 and 1.7 seconds at the median. The 11 runs Gemma served alone took 4.8 seconds at
the median with their loads and 0.7 without.

### The decision and the remap

`lifecycle/decision.py` reads the gate first, then whether the candidate served at least 20 valid runs, then the two
SLIs with a target, the candidate's ratio not below the control's over the runs each served; equal is enough. It
reads the latency SLI with the loads taken out, since the swaps are this workstation's and a candidate in production
has replicas of its own (chapter 9, part 2), and it records the decision as measured beside it.

|SLI|Read from|Control|Candidate|Candidate not below control|
|---|---|---|---|---|
|success|success|85 / 85 (100%)|47 / 47 (100%)|yes|
|latency|latency_without_loads|85 / 85 (100%)|47 / 47 (100%)|yes|

|Decision|Gate|Minimum runs|As measured, loads included|Because|
|---|---|---|---|---|
|remap back|9 held, 1 regressed, 1 not gated|20|remap back|the gate: trajectory.allowed regressed past the threshold|

The decision is a remap back, on the gate alone: `trajectory.allowed` regressed, and the rule ends the path there.
The canary would have allowed a promotion, both SLIs equal at 100 percent. As measured, with the loads in, the
candidate's latency ratio was below the control's (66 against 81 percent) and the rule would have remapped back on
that as well; on one shared card the smaller arm pays the loads more often.

`lifecycle/remap.py` then wrote the configuration the alias served before, `lifecycle/litellm.current.yaml`, whole
and atomically as `litellm.restored.yaml` beside the results (the committed configurations stay as the run started),
and one line in `changes.jsonl` in the shape step 4's switches leave: the change, its kind (an emergency change by the
on-call lead, since the playbook's lever "the alias remapped back" is theirs, where a promotion would be a planned
change by the platform team), the deployments before and after, the time by which it must be documented (ch02:163),
the review, the decision's reason, and the evidence files. The proxy reads its configuration at start, so the remap
takes effect at the next start, and three of W2's questions through a gateway started from the restored file
confirmed the alias serves gpt-oss-20b again. The restored file and its record were written again after the run, from
the kept files and with the run's timestamp, when the review found the first version carrying the canary's
`router_settings` block and a reason that named neither the gate nor the canary; the probe's three questions ran
against that first version, whose `model_list` is the same:

|Change|Kind|Lever|Alias|From|To|By|Authority|Document by|Review|Takes effect|
|---|---|---|---|---|---|---|---|---|---|---|
|CH-20261109-01|emergency|alias remap, back|larkspur-chat|local-gpt-oss-20b-chat (weight 3), candidate-gemma4-12b-chat (weight 1)|local-gpt-oss-20b-chat|oncall.lead@larkspur.example|on-call lead|2026-11-10T11:54:11.440+00:00|the next board meeting|at the proxy's next start, which reads the configuration once|

|After the remap|Cases|Calls|Served by|Every call on the expected deployment|Ends|Seconds|
|---|---|---|---|---|---|---|
|litellm.restored.yaml|w2-01, w2-02, w2-03|6|local-gpt-oss-20b-chat|yes|answer, answer, answer|8.64, 0.9, 2.05|

### fig-16-04

`lifecycle/upgrade_path.yaml` holds the figure's stages and what gates each, and `fig-16-04.json` carries them with
the run's numbers. The sixth stage, the live job on the new map and the review that accepts it as the baseline
(E-D9), did not run here.

|Stage|Name|What gates it|The run's numbers|
|---|---|---|---|
|register|the register|the register and the gateways name the same deployments (lifecycle/register.py --check)|models 13; pinned 6; deployments 14; problems 0; candidate local-gemma4-12b; candidate_pin 6114515d63c1|
|staging|the candidate behind the alias on a staging gateway|the gate of E-D9 (labs/ch15/ci/gate.py): no check may lose more cases against the baseline than its threshold allows (the baseline built from the kept runs, until a live run is accepted); the pins are listed for the review that accepts the new baseline|cases 25; checks 11; held 9; not_gated 1; pin_problems 7; verdict regressed; seconds 136.4|
|canary|a canary weight in the gateway|O-D12's SLIs over each arm's runs (slo/slis.py): the candidate's success and latency ratios not below the control's on the same traffic, with at least 20 valid runs on the candidate|share 0.25; passes 4; runs 100; calls 196; candidate_calls 54; seconds 553.9|
|decision|promote, remap back, or extend|the rule above|decision remap back; latency_read_from latency_without_loads; as_measured remap back|
|remap|the alias remapped|the change record (ch02:163)|change CH-20261109-01; kind emergency; lever alias remap, back; probe_calls 6|
|after|after the remap|the review that accepts the baseline (labs/ch15/ci/live.py --accept)|ran False; waits_for the live job on the new map and the review that accepts it (E-D9)|

### What the chapter takes from here

- The limit on Claude's identifier: `anthropic.claude-sonnet-5-5` and `ca.anthropic.claude-haiku-5-5` carry no
  version and no date, so a register can't tell a changed model from the same one under either ID; the live job of
  E-D9 is the only check, and the register says so beside each pin.
- A local pin is a digest on a named server. One tag, `gpt-oss:20b`, from one model store reported two digests on
  two Ollama versions, and the Ollama on the PATH moved from 0.22.1 to 0.40.14 under the labs between runs.
- The gate did its job on the model's reads: two cases over a threshold of one, on a check the model decides, after
  a kept run that passed all 25. The rule doesn't wait; a second live run tells habit from noise.
- A per-call weight splits an agent's run. 36 of 100 runs were served by both arms, so the run-level SLIs read a
  joint result there; a canary for an agent workflow needs the trace id in the routing decision, and the gateway's
  configuration can't express that.
- On one card the latency SLI reads the server's model loads, 4.4 seconds each at the median, and the arm with the
  smaller share pays more often: 39 of its 54 calls against 38 of 142. The SLI with the loads taken out stands for
  the production shape, where each model has its replicas.
- Gemma 4 12B was faster a call and shorter in its completions than gpt-oss-20b on W2 (372 against 647 ms with no
  swap; 39 against 128 completion tokens), and W2's scorer gave it 23 of 25 against 22; the gate refused it on its
  reads, which is the order the path puts the checks in.
- Nothing Larkspur runs on retires within 90 days on 9 November. gpt-4o and the Canadian embedding model are inside
  the 180-day window, their tickets fall on 14 January and 1 January 2027, and the embedding model has no replacement
  processed in Canada.
- The run cost nothing: 277 local model calls (the set's 56, the judge's 19, the canary's 196, the probe's 6) and
  about twelve minutes of the GPU.

### What step 8 did not do

- Run the other five golden sets on the candidate: E-D9's gate as built needs a complete run, and the brief asked
  for one workflow.
- Run the live job after the remap or accept a baseline; both are the author's review, and nothing in
  `labs/ch15/baseline/` or `labs/ch15/live/` changed.
- Promote: the gate refused the candidate, so the committed configurations are as the run started, the restored map
  is beside the results, and the register still lists Gemma 4 12B as a candidate.
- Keep a run's calls on one arm: LiteLLM's weight is per request.
- Run the two models on two servers, or on the installed Ollama 0.40.14; one server swapped them, and the run
  measured the swaps.
- Call a cloud, open anything under `secrets/`, or draw the figure.

## The monthly review (step 9)

Step 9 builds O-D15 on this workstation, with no model, no gateway process, and no network. `review/monthly_review.py`
reads what the other steps committed and writes one month's review for Ingrid Holm, the page whose shape the chapter
prints, as `results/2026-11-09/review/review-2026-11.md`, with `review-2026-11.json` beside it holding every figure, its
basis, and its source. Its inputs are the ledger of steps 2, 3b, and 9 (`results/2026-11-03/ledger.json`), step 6's SLIs,
simulated month, budgets, and alerts (`results/2026-11-09/slo/`), step 4's drills (`results/2026-11-03/budget/drills.json`),
step 8's change record and the register (`results/2026-11-09/lifecycle/changes.jsonl`, `lifecycle/register.yaml`), the
playbook, the manifests, and W5's ledger as its run after the review kept it
(`workflows/w5-drift/eval/results/2026-11-03/after-review/nights-gpt-oss-20b/ledger.json`), read through W5's own
`Ledger.summary(month)` so that the savings arithmetic stays W5's. The review is for November 2026, the month the kept
runs and the drills fall in, on 9 November 2026, the day the register was read.

The month filters what carries a date: W5's ledger rows, the budget alerts and the stop, and the change records. The kept
runs, the estimated volumes, step 6's simulated month, and the register carry none, so another month changes sections 6
and 8, another date changes section 7, and the page's opening says which sections read files with no month of their own.
A month in which W5 ran no night says so in its place: `--month 2026-12` and `--month 2026-10` write the page with "W5 ran
no night and no alarm in December 2026" and with no alert, stop, or change record, since the committed files hold none.
An input that doesn't exist stops the run with a `FileNotFoundError` before anything is written, and the page and its JSON
are written together or not at all. An injected event of step 6's month that the generator has no reading for stops the
run too: `SYMPTOM_OF` in `monthly_review.py` says which of the playbook's symptoms each event is, and a new event needs a
line there.

Each section of the page opens with a line that says what its figures are, in five words the page defines once. Measured
figures were read or computed from a kept run, a drill, or a live run; priced ones are measured tokens or calls times a
price of the dated table at chapter 6's design (the local models cost nothing, so the price is what the same tokens would
cost on the managed alias); estimated ones are Larkspur's monthly volumes and anything multiplied by them, and the
guardrail's estimate; simulated ones are step 6's month; recorded ones are dates, states, and change records read from a
register or a record file. The page names the dated price table by its entries and its dates (49 entries, 28 October to 3
November 2026), and gives the year on the dates of step 6's month, which starts on 5 January 2027. Where a decision names
something no file holds, the page says so in its place: the controls' breaches are not evaluated, the only budget stop
of the month is step 4's seeded drill, and a throttled hour has no symptom of its own in the playbook.

### Runs and cost per run

The runs kept are measured, the runs a month are the ledger's estimates with their sources, and the cost per run is
priced: the kept runs' measured tokens on gpt-oss-20b, the ledger's reference model, at chapter 6's design. The 95th
percentile is the nearest rank, a value some run had.

|Workflow|Runs kept (measured)|Runs a month (estimated)|Unit|The volume's source|Model calls a run, median / 95th (gpt-oss-20b)|Cost per run, median / 95th (USD, priced from the gpt-oss-20b tokens)|Of per_run_usd, median / 95th|per_run_usd|
|---|---|---|---|---|---|---|---|---|
|W1|75|6,000|question|lab assumption, not in the book|2 / 3|0.000241 / 0.000407|0.12% / 0.204%|0.2|
|W2|135|43,030|question|ch09:405|2 / 5|0.000187 / 0.000453|0.0374% / 0.0906%|0.5|
|W3|48|300|incident|lab assumption, not in the book|7 / 9|0.000887 / 0.00118|0.0443% / 0.0588%|2|
|W4|48|200|change|ch13:9|1 / 1|0.0000610 / 0.0000884|0.0061% / 0.00884%|1|
|W5|33|34|night or alarm|nights: ch14:29; alarms: lab assumption, not in the book|14 / 14|0.00286 / 0.00709|0.286% / 0.709%|1|

No median run costs more than 0.286 percent of its per-run budget, W5's; the highest 95th percentile over every kept
run and model is 2.84 percent, W5's on Gemma 4 12B, from the kept run that looped in its reasoning (step 2). The page
also gives every model's row, since W1 on Nova Lite is the one managed-model measurement the lab has:

|Workflow|Model|Runs|With tokens|Cost per run, median / 95th (USD, priced)|Of per_run_usd, median / 95th|
|---|---|---|---|---|---|
|W1|gemma4-12b|25|25|0.000243 / 0.000488|0.121% / 0.244%|
|W1|gpt-oss-20b|25|25|0.000241 / 0.000407|0.12% / 0.204%|
|W1|nova-lite|25|25|0.000253 / 0.000496|0.127% / 0.248%|
|W2|gemma4-12b|25|25|0.000183 / 0.000326|0.0365% / 0.0652%|
|W2|gpt-oss-20b|110|110|0.000187 / 0.000453|0.0374% / 0.0906%|
|W3|gpt-oss-20b|48|24|0.000887 / 0.00118|0.0443% / 0.0588%|
|W4|gemma4-12b|16|8|0.0000147 / 0.0000205|0.00147% / 0.00205%|
|W4|gpt-oss-20b|32|8|0.0000610 / 0.0000884|0.0061% / 0.00884%|
|W5|gemma4-12b|15|15|0.00100 / 0.0284|0.1% / 2.84%|
|W5|gpt-oss-20b|18|18|0.00286 / 0.00709|0.286% / 0.709%|

The page then gives chapter 15's judge, now in the ledger under the workflow it judged ("The judge's tokens in the
ledger", above): the 1,439 judgments' tokens set against the tokens of the outputs they read, with the basis column
saying where step 3b's run of the same case stands in for W3's and W4's outputs, which kept no tokens, and a count of the
judgments whose completion tokens exceed the output's. Its sentences are generated from the ledger's conclusion, so each
holds only where the rows say it does. In completion tokens, in total, gpt-oss-20b, the judge that thinks, wrote more than
the outputs it read in every workflow it judged, which is chapter 15's sentence as written (ch15:156); W3 had no such judge.
In all tokens its total is above the output's for W4 and W5 and about a third of the run's tokens for W1 and W2, and Gemma
4 12B's is above it for W4 alone. These are token figures and not prices.

|Workflow|Judge|Judgments (measured)|Judge's tokens, prompt / completion / total|Judged outputs' tokens, prompt / completion / total|Ratio, prompt / completion / total|Judgments with more completion tokens than the output|Judged tokens' basis|
|---|---|---|---|---|---|---|---|
|W1|gemma4-12b|165|118,984 / 4,625 / 123,609|470,352 / 49,236 / 519,588|0.25 / 0.09 / 0.24|0|measured|
|W1|gpt-oss-20b|171|123,707 / 68,260 / 191,967|531,852 / 49,308 / 581,160|0.23 / 1.38 / 0.33|117|measured|
|W2|gemma4-12b|222|144,666 / 5,731 / 150,397|480,663 / 69,603 / 550,266|0.30 / 0.08 / 0.27|0|measured|
|W2|gpt-oss-20b|90|57,810 / 32,946 / 90,756|224,457 / 18,024 / 242,481|0.26 / 1.83 / 0.37|84|measured|
|W3|gemma4-12b|69|53,571 / 2,039 / 55,610|645,669 / 48,132 / 693,801|0.08 / 0.04 / 0.08|0|stand-in|
|W4|gemma4-12b|54|27,353 / 1,418 / 28,771|9,900 / 9,136 / 19,036|2.76 / 0.16 / 1.51|6|stand-in|
|W4|gpt-oss-20b|32|17,758 / 8,895 / 26,653|4,902 / 2,474 / 7,376|3.62 / 3.60 / 3.61|27|stand-in|
|W5|gemma4-12b|362|405,396 / 11,892 / 417,288|233,934 / 307,636 / 541,570|1.73 / 0.04 / 0.77|0|measured|
|W5|gpt-oss-20b|274|282,682 / 202,432 / 485,114|180,488 / 68,476 / 248,964|1.57 / 2.96 / 1.95|254|measured|

### The month against the monthly budget

The month is the estimated volume times the mean cost per run, which the table prints beside the volume so that the month
can be rebuilt from the page; it is an estimate. The mean is over the runs section 1's median and 95th percentile
summarize. The range is over the kept runs the profile pools and says "one kept run" where the profile holds one, the
recounted column applies step 2's Nova Lite ratios, and the guardrail column is the estimate the cost lines don't carry.

|Workflow|Runs a month (estimated)|Tokens a month (estimated)|Mean cost per run (USD, priced)|Direct cost (USD, estimated)|per_month_usd|Of per_month_usd|Range over the kept runs|Recounted as Nova Lite|Guardrail estimate, of per_month_usd|Basis of the per-run figures|
|---|---|---|---|---|---|---|---|---|---|---|
|W1|6,000|19,181,280|0.000240|1.44|100|1.44%|one kept run|1.59%|20.5%|measured|
|W2|43,030|100,000,000|0.000209|9.01|200|4.51%|4.33% to 4.88%|4.71%|63%|measured|
|W3|300|3,112,038|0.000708|0.213|500|0.0425%|one kept run|0.051%|0.66%|measured on the 24 of 48 runs with tokens|
|W4|200|77,775|0.0000626|0.0125|200|0.00626%|one kept run|0.00439%|0.0563%|measured on the 8 of 32 runs with tokens|
|W5|34|604,660|0.00328|0.112|100|0.112%|0.0684% to 0.165%|0.0719%|0.695%|measured|

### The shared lines

O-D6 as amended: the GPUs' hours are split among the alias's tenants by their share of its tokens, with the idle
remainder on the platform team's line, and the platform's fixed costs are split by tokens (ch02:144). The page sets
them beside each workflow's direct cost and says they are showback, never a charge against the budget.

|Workflow|Tenant of the self-hosted alias|Tokens to it a month (estimated)|Share of them|GPU hours (USD)|Of per_month_usd|Share of tokens, all aliases|Fixed costs by tokens (USD)|Of per_month_usd|Direct cost (USD), for comparison|
|---|---|---|---|---|---|---|---|---|---|
|W1|yes|1,933,440|87.2%|0.795|0.795%|15.6%|72.77|72.8%|1.44|
|W2|yes|0|0%|0|0%|81.3%|379.38|190%|9.01|
|W3|yes|284,075|12.8%|0.117|0.0234%|2.53%|11.81|2.36%|0.213|
|W4|no|0||0|0%|0.0632%|0.295|0.148%|0.0125|
|W5|no|0||0|0%|0.492%|2.29|2.29%|0.112|
|idle, the platform team||||2,716.15||||||

### The error budget left

The SLIs are measured on the kept runs; the error budgets and what is left of them are step 6's simulated month, and
the page says so in its basis line and in the table's header. Five budgets were spent in that month, and the page says
when each went, with the year, and what the policy did next.

|Workflow|SLI|Target|Threshold|Good / valid on the kept runs (measured)|Measured|
|---|---|---|---|---|---|
|W1|success|99.5%||75 / 75|100%|
|W1|latency|95%|30 s|74 / 75|98.67%|
|W2|success|99.5%||129 / 135|95.56%|
|W2|latency|95%|10 s|128 / 129|99.22%|
|W3|success|95%||40 / 48|83.33%|
|W3|latency|95%|120 s|40 / 40|100%|
|W3|outcome|90%||2 / 2|100%|
|W4|success|99%||48 / 48|100%|
|W4|latency|95%|60 s|48 / 48|100%|
|W4|outcome|90%||no events||
|W5|success|90%||33 / 33|100%|
|W5|latency|90%|21,600 s|33 / 33|100%|
|W5|outcome|80%||11 / 11|100%|

|Workflow|SLI|Error budget (events, simulated month)|Bad events in the month|Budget used|Budget left|Bad events by cause|
|---|---|---|---|---|---|---|
|W1|success|29.6|54|182.5%|spent, Sat 30 Jan 2027 21:56 (used 182.5%)|self-hosted-down 53, throttled-hour 1|
|W1|latency|296|3|1.01%|99%|throttled-hour 3|
|W2|success|212|5,432|2,560%|spent, Sun 17 Jan 2027 04:24 (used 2,560%)|baseline 261, model-regression 5,161, throttled-hour 10|
|W2|latency|2,098|1,106|52.71%|47.3%|model-regression 1,029, provider-outage 47, throttled-hour 30|
|W3|success|14.8|45|304.2%|spent, Fri 22 Jan 2027 21:38 (used 304.2%)|baseline 40, self-hosted-down 5|
|W3|latency|12.3|0|0%|100%|none|
|W3|outcome|2.77|5|180.2%|spent, Wed 20 Jan 2027 11:18 (used 180.2%)|baseline 2, model-regression 3|
|W4|success|1.97|3|152.1%|spent, Thu 28 Jan 2027 18:00 (used 152.1%)|w4-records-refused 3|
|W4|latency|9.86|0|0%|100%|none|
|W4|outcome|19.7|9|45.63%|54.4%|baseline 9|
|W5|success|3.4|0|0%|100%|none|
|W5|latency|3.4|0|0%|100%|none|
|W5|outcome|3.6|3|83.33%|16.7%|baseline 2, model-regression 1|

### Incidents

The controls' breaches (residency, the never-list, the budgets) are not evaluated, and the page says so with the reason.
Nothing in the lab checks a run against a control: a run's `violation` field is set by no kept run and no simulated run
(`slo/slis.py`), so the empty incident lists in `kept.json` and `month.json` say nothing about the controls. They hold by
refusal, and the gateway's refusal counts, the `refused` and `failed` cost lines, could stand in for a check; no step
reads them for that. The page then reads step 6's five injected events as the playbook's symptoms, the lab's reading: the
outage and the weekend without the self-hosted path are "a provider outage", the regression "a model that changed under
its alias", the day of refused records "a run of refusals or tool errors", and the throttled hour has no symptom of its
own, since O-D13's list gives a 429 to the platform's page (ch05:498). The last column names the policy action each event
helped cause, with its share of the bad events at the moment the budget went: the throttled hour's 10 of W2's 213 say the
baseline spent that budget, and the weekend's 29 of W1's 30 say the weekend spent W1's.

|Injected event (simulated)|When (ET)|The playbook's symptom|Runs it changed|Bad events|First alert (with-probe)|Policy action it helped cause|
|---|---|---|---|---|---|---|
|provider-outage|Mon 11 Jan 2027 10:00 to Mon 11 Jan 2027 10:45|a provider outage|W1 2, W2 55|none|page: W4 success fast-burn-1h, Mon 11 Jan 2027 10:35|none|
|throttled-hour|Wed 13 Jan 2027 14:00 to Wed 13 Jan 2027 15:00|none in the playbook; the platform's page, provider-429-across-workflows (ch05:498)|W1 5, W2 44|W1 1, W2 10|page: W2 success fast-burn-1h, Wed 13 Jan 2027 14:10|W2 freeze (success, Sun 17 Jan 2027 04:24; 10 of the 213 bad events when spent); W1 freeze (success, Sat 30 Jan 2027 21:56; 1 of the 30 bad events when spent)|
|model-regression|Wed 20 Jan 2027 10:00 to Thu 04 Feb 2027 00:00|a model that changed under its alias|W2 20,403, W3 10, W5 15|W2 5,161, W3 3, W5 1|page: W2 success fast-burn-1h, Wed 20 Jan 2027 10:30|W3 freeze (outcome, Wed 20 Jan 2027 11:18; 1 of the 3 bad events when spent); W3 rung down (outcome, Wed 20 Jan 2027 11:18; 1 of the 3 bad events when spent)|
|self-hosted-down|Sat 30 Jan 2027 00:00 to Mon 01 Feb 2027 00:00|a provider outage|W1 53, W3 5|W1 53, W3 5|page: W1 success fast-burn-1h, Sat 30 Jan 2027 00:45|W1 freeze (success, Sat 30 Jan 2027 21:56; 29 of the 30 bad events when spent)|
|w4-records-refused|Thu 28 Jan 2027 00:00 to Fri 29 Jan 2027 00:00|a run of refusals or tool errors|W4 3|W4 3|page: W4 success fast-burn-1h, Thu 28 Jan 2027 14:35|W4 freeze (success, Thu 28 Jan 2027 18:00; 2 of the 2 bad events when spent)|

|Scope|Pages by cause (simulated)|Tickets by cause (simulated)|
|---|---|---|
|W1|self-hosted-down 21, throttled-hour 1|self-hosted-down 1|
|W2|baseline 5, model-regression 2, throttled-hour 1|baseline 1, model-regression 1|
|W3|baseline 2|baseline 5, model-regression 1|
|W4|provider-outage 2, w4-records-refused 4|provider-outage 1, w4-records-refused 1|
|platform|throttled-hour 1|none|

|When (ET, simulated)|Workflow|Action|SLI|Decided by|Change record|
|---|---|---|---|---|---|
|Sun 17 Jan 2027 04:24|W2|freeze|success|the policy, agreed in advance||
|Wed 20 Jan 2027 11:18|W3|freeze|outcome|the policy, agreed in advance||
|Wed 20 Jan 2027 11:18|W3|rung down|outcome|the on-call lead (oncall.lead@larkspur.example)|EC-SIM-01|
|Fri 22 Jan 2027 21:38|W3|budget spent|success|||
|Thu 28 Jan 2027 18:00|W4|freeze|success|the policy, agreed in advance||
|Sat 30 Jan 2027 21:56|W1|freeze|success|the policy, agreed in advance||

### Budget events and switches pulled

The month's records are step 4's drills of 3 November (UTC), whose month was set through LiteLLM's admin API, and the
alias remap of step 8's run on 9 November; the page says which is which, and counts the change records by the run that
left them. The alerts are the four the receiver got, and two of them show no soft budget: they are LiteLLM's projection
alerts, which pass the soft budget as their `max_budget` and add a projected spend (the 80 percent alert, above). The stop
is the 422, and the change records are grouped by change, with each lever's from and to.

|Received (UTC)|Workflow|Event|What it is|Spend (USD)|Soft budget|max_budget|Projected|Forwarded to|
|---|---|---|---|---|---|---|---|---|
|2026-11-03T23:45:39|w2-ops-assistant|threshold_crossed|the month's pace projected past the soft budget|159.751||160|1,722.87|sam.okafor@larkspur.example, finops@larkspur.example|
|2026-11-03T23:45:41|w2-ops-assistant|soft_budget_crossed|the soft budget reached|160.0004|160|200||sam.okafor@larkspur.example, finops@larkspur.example|
|2026-11-03T23:45:58|w2-ops-assistant|budget_crossed|the month's pace projected past the soft budget|199.751||160|2,154.10|sam.okafor@larkspur.example, finops@larkspur.example|
|2026-11-03T23:47:05|w2-ops-assistant|budget_crossed|the budget reached|200|160|200||sam.okafor@larkspur.example, finops@larkspur.example|

|Change|Lever (from, to)|Workflow or alias|By|At (UTC)|Document by (UTC)|Run as|
|---|---|---|---|---|---|---|
|EC-DRILL-01|kill switch, gateway half (open to blocked); kill switch released (blocked to open)|w2-ops-assistant|oncall.lead@larkspur.example|2026-11-03T23:45:02|2026-11-04T23:45:02|drill|
|EC-DRILL-02|kill switch, gateway half (open to blocked); kill switch released (blocked to open)|w2-ops-assistant|oncall.lead@larkspur.example|2026-11-03T23:45:06|2026-11-04T23:45:06|drill|
|EC-DRILL-03|kill switch, gateway half (open to blocked); kill switch released (blocked to open)|w2-ops-assistant|oncall.lead@larkspur.example|2026-11-03T23:45:10|2026-11-04T23:45:10|drill|
|EC-DRILL-04|kill switch, gateway half (open to blocked); kill switch released (blocked to open)|w2-ops-assistant|oncall.lead@larkspur.example|2026-11-03T23:45:14|2026-11-04T23:45:14|drill|
|EC-DRILL-05|kill switch, gateway half (open to blocked); kill switch released (blocked to open)|w2-ops-assistant|oncall.lead@larkspur.example|2026-11-03T23:45:19|2026-11-04T23:45:19|drill|
|EC-DRILL-RUNG|rung down (manifest (3) to 1); rung restored (unreadable to manifest (3))|w3-incident|oncall.lead@larkspur.example|2026-11-03T23:47:21|2026-11-04T23:47:21|drill|
|CH-20261109-01|alias remap, back (local-gpt-oss-20b-chat (weight 3), candidate-gemma4-12b-chat (weight 1) to local-gpt-oss-20b-chat)|larkspur-chat|oncall.lead@larkspur.example|2026-11-09T11:54:11|2026-11-10T11:54:11|the upgrade path, run once|

### Models within 180 days of retirement

`retirement.evaluate` for the review's date, over the register: five models inside the window, two of them behind a
Larkspur alias, no page, one ticket (gpt-4o's Legacy notice), and five review rows. Eight models have no published
date, and for two of them, Nova Lite and Mistral Large, the provider's earliest possible date has passed, so a notice
can come any day.

|Model|Cloud|Larkspur runs on it|Stage|Retires (recorded)|Days left|What fires|
|---|---|---|---|---|---|---|
|Claude 3 Haiku|aws|no|Legacy|2026-11-13|4|review|
|Llama 3 70B Instruct|aws|no|Legacy|2027-03-30|141|review|
|text-multilingual-embedding-002|google|yes|GA|2027-04-01|143|review|
|gpt-4.1-mini|azure|no|Deprecated|2027-04-14|156|review|
|gpt-4o|azure|yes|Legacy|2027-04-14|156|review, ticket (Legacy notice)|

### W5's savings, and what finding them cost

The savings are W5's ledger's own shares, as `Ledger.summary` gives them: the detectors' estimates for the findings
that got a pull request over the three accounts' spend the nights read, with the one merged and applied credited when
the next night found the volume gone. The accounts are the lab's fixtures, and the ledger gives shares and counts and
never an amount (W5-D10), so the page prints no amount for a cost or a saving. Chapter 14 leaves "what it cost to find" to
this review (ch14:171), so the page prices the month's gateway calls at the dated table's price for `larkspur-chat`, on
the kept runs' token counts, and gives the result as shares: 0.00621 percent of W5's monthly budget and 0.00647 percent
of the saving it realized, with the range over W5's six kept runs on gpt-oss-20b beside it, since the agent's cost
differs by run while the savings rows don't.

|Proposed, share of the accounts' spend|Pull requests by state|Realized, share of spend|Realized, share of proposed|Findings realized|Findings|Runs in the month|
|---|---|---|---|---|---|---|
|0.77%|open 14, merged 1, closed 0|0.33%|42.77%|1|16 seen, 6 with an estimate, 1 suppressed|3: 1 alarm run, 2 scheduled nights|

|Gateway calls (measured)|Prompt tokens|Completion tokens|Seconds|Cost to find, of per_month_usd (priced at nova-lite-ca)|Cost to find, of the saving realized|Range over W5's kept runs on the same model|
|---|---|---|---|---|---|---|
|31|19,577|19,358|135|0.00621%|0.00647%|18,696 to 51,682 completion tokens, 135 to 1,460 s, over 6 kept runs|

### What the chapter takes from step 9

- The review's shape: eight sections, each opening with its basis and its source, each a table with a line of prose
  where a number needs one, and a legend of five words. The chapter prints the shape and the percentages, never a price.
- The percentages: medians from 0.0061 to 0.29 percent of `per_run_usd`; months from 0.0063 to 4.5 percent of
  `per_month_usd`, and the guardrail estimate at 63 percent of W2's; the fixed costs at 190 percent of W2's budget by
  tokens and the GPUs 99.966 percent idle; W3 at 83 percent success on the kept runs against a 95 percent target; five
  simulated budgets spent; two pinned models inside 180 days; W5's 0.77, 0.33, and 42.77 percent, found for 0.0062 percent
  of its budget.
- The review answers chapter 14's sentence (ch14:171) with W5's three shares and a priced cost, and chapter 1's question
  of what a workflow costs per run and per month (ch01:264) with measured per-run figures and estimated months, marked
  apart as O-D15 asks.
- Chapter 15's judge is in the ledger under the workflow it judged (ch15:305): 1,439 judgments, 1,231,927 prompt and
  338,238 completion tokens, set against the tokens of the outputs they read. Its sentence that a judge that thinks
  before it answers writes more tokens than the answer it judges (ch15:156) holds as written for completion tokens:
  gpt-oss-20b, the judge that thinks, wrote more of them in total than the outputs it read in every workflow it judged,
  1.38 to 3.60 times (W1, W2, W4, W5; W3 had no such judge). In all tokens its total is above the output's for a W4
  rationale (3.61, on the stand-in) and a W5 body (1.95) and is about a third of the run's tokens for a W1 or W2 run
  (0.33, 0.37), which are token figures and not prices.

### What step 9 did not do

- Read a live month. Every figure comes from the kept files; nothing in the lab produces a month of production records,
  so the volumes are estimates, the error budgets are a simulation's, and the budget events are a drill's.
- Evaluate a control. Nothing checks a kept or a simulated run against residency, the never-list, or a budget, so the
  page says the breaches are not evaluated and prints no count; the gateway's refusal counts could stand in for a check,
  and no step reads them for one.
- Price W5's savings beyond the ratio: the ledger's spend and savings are the fixtures' and stay out of the page as
  amounts, by W5-D10.
- Put a figure where a decision names one that no file holds. The page says so in its place instead: the controls not
  evaluated, no budget stop outside the drill, no symptom for a throttled hour.
- Find the tokens of W3's and W4's judged outputs: chapter 15's kept runs of both kept none, so step 3b's run of the
  same case on the same model stands in, and every table says so.
- Open a console or a dashboard (O-D17), or compute chargeback, which is chapter 18's.

## What the chapter takes from here

The lab's findings across steps 2 to 9, gathered; each step's own list above stays, with the numbers behind each line.

- A run costs little against its budget. No median run on the kept runs costs more than 0.29 percent of its
  `per_run_usd`, and the largest month, W2's at Larkspur's 100 million tokens, is 4.5 percent of its `per_month_usd`
  (steps 2 and 3b). Chapter 3's median holds: two model calls and one read for W2, in every kept run.
- The tokens are a small part of the bill. Chapter 6's guardrail, which no cost line carries, is estimated at 63 percent
  of W2's monthly budget against 4.5 for the tokens, and needs a line of its own in the ledger (step 2). The platform's
  fixed costs come to about 467 US dollars a month at the table's prices and land mostly on W2, 190 percent of its
  budget when split by tokens, so they are showback beside the direct costs and never a charge against a budget. The
  GPUs sit 99.966 percent idle; without the idle line on the platform team, W1 alone would carry 24 times its budget.
- The self-hosted alias has three tenants by the manifests and chapter 10 (W1, W2, W3); chapter 9's "two workflows"
  needs correcting on book #26 (step 2).
- A price estimated from a local model's token count carries two ratios: Nova Lite counted 1.36 times gpt-oss-20b's
  input and 0.54 times its output on the same cases (step 2). LiteLLM's built-in map holds no price for the Canadian
  profile, prices a Region-prefixed name at the base Region's rate, and lets a zero-priced alias skip every budget
  check, so the gateway needs the dated table as custom prices.
- A sampled month can be priced only when each trace records the share it was kept at. Scaled naively, a tail-sampled
  month overstates W2's cost by 33 to 48 percent, and at 1 percent W5's 34 nights keep no trace at all in 707 of 1,000
  seeds (step 2). The cost lines are never sampled, which is why cost per run comes from them.
- The trace id joins the logs and the cost lines in every workflow, and since the follow-ups to W3 and W4 the spans form
  one tree a run in all five (steps 3 and 3b). Ollama sends no span, so the gateway's span is the whole model call. In
  the cloud the id reaches Bedrock's invocation log in `requestMetadata` with text delivery off or on, and CloudTrail
  through the session name and the tag, and `join.py` prints one run from five stores and finds the run behind one audit
  event (step 7). Two gaps stay: a refusal at the key leaves a cost line with no trace id (step 4), and W2's failed lines
  during a cooldown name the fallback (step 5).
- The Collector drops every opt-in content attribute, keeps every failed, refused, slow, over-budget, and fallback run,
  and records the share and the policy on each kept trace through two alpha feature gates. It holds a trace about 30.7
  seconds, judges a run longer than its wait on the first spans, and sees one call's cost at a time (steps 3 and 3b).
  Transaction Search keeps the policy and loses the tracestate, indexes 1 percent of spans as trace summaries, and
  lists no service for a Collector's spans; Langfuse 4.74.0 prices a generation from `gen_ai.usage.cost` to the
  gateway's own figure (step 7).
- LiteLLM's database works on native Windows at the labs' Python, so the monthly budget, the 80 percent alert, and the
  key block are LiteLLM's own, with no callback of the lab's (step 4). The alert and the stop come one reservation early,
  since LiteLLM reserves 16,384 output tokens when `max_tokens` is unset; the stop is a 422, it holds across a restart,
  and the month resets at midnight in Toronto. LiteLLM's projection alerts take the 24-hour slots of the real 95 and 100
  percent alerts.
- The kill switch at the gateway takes effect from the next call, 0.142 seconds to the loop's first refusal at the
  median (step 4); the identity half bites in about eight seconds and lifts in about eight on real credentials, and the
  trust policy with the trace id needs two statements (step 7). The rung-down switch drops every write tool, since the
  manifest marks writes and nothing finer (step 4).
- A tokens-per-minute limit per key keeps the incident workflow served through the operations assistant's burst; the
  request rate alone does not, and the deployment's own limits count too late (step 5). Without a shared store the
  limiter's windows sat in a 200-entry in-memory cache that step 4's alerts filled 30.5 seconds into the burst; on Garnet
  with its Lua transaction mode the windows hold, and when the store stops LiteLLM fails open unless told to fail closed
  (step 5b).
- Naive retries made 9.07 times the load and served no more than sending each request once; honoring Retry-After served
  56 of 80 at 4.25 calls a success, and every workflow's client now waits out a 429 that names its wait (steps 5 and
  5b). The gateway adds about 10 milliseconds a call, 39 with eight calls at once.
- A cooldown comes at the third failure. W2 fails over to us-east-2; W3, whose data may not leave Canada, got the
  primary's error and then a 429 until the gateway knew the self-hosted alias as its hop, and then was served through
  every failure mode (steps 5 and 5b). The approval's number is the idempotency key: W3's store, its approval binding,
  and the need for a fresh yes stop a repeated write.
- Committed capacity has no break-even in the table, since section 8.8 holds no matching on-demand rates. W2 would fill
  3 to 9 percent of the smallest commitment on each cloud, which would have to sell at least 91 percent below the
  on-demand rate (step 5).
- The SLO targets are the lab's proposals: 99.5 percent success for W1 and W2, 95 for W3, 99 for W4, and 90 percent of
  nights for W5; W3 at 83 percent on the kept runs doesn't meet its own (step 6). One read failure in 90 questions is
  twice what 99.5 percent allows, so W2's baseline spent its budget on day 12 of the simulated month. The regression
  paged W2 in 30 minutes; the green probe hid W3's weekend failures and the group hid W4's complete failure, the
  workbook's two cautions. Three probes cost about 14 US cents a month, and W4's sends 4.2 times W4's own tokens.
- Nothing Larkspur runs on retires within 90 days on 9 November 2026; gpt-4o and the Canadian embedding model are within
  180, and Claude's identifiers on Bedrock carry no version, so chapter 15's live job is the only check that the model
  behind them is the same (step 8). A local pin is a digest on a named server.
- The gate refused the candidate on its reads, two cases over a threshold of one, where the canary would have promoted
  it; a per-call weight splits an agent's run, so 36 of 100 runs were served by both arms, and a canary for an agent
  needs the trace id in the routing decision (step 8).
- The monthly review is eight sections with a basis line each, and the percentages above are what it prints; it answers
  chapter 14's sentence with W5's three shares and a priced cost of finding them, 0.0062 percent of W5's budget (step 9).
- Chapter 15's judge is in the ledger under the workflow it judged, 1,439 judgments with 1,231,927 prompt and 338,238
  completion tokens, and its sentence holds as written for completion tokens: the judge that thinks wrote more of them,
  in total, than the outputs it read in every workflow it judged (1.38 to 3.60 times; W3 had no such judge). In all
  tokens its total is above the output's only where the output is one short call, a W4 rationale or a W5 body, and about
  a third of the run's tokens against a W1 or W2 run; those are token figures and not prices (step 9).

## What the lab did not do

The limits across the steps, with their reasons; each step's own list stays above.

- Measure a month. The volumes are Larkspur's estimates, three from the book (W2's tokens, W4's changes, W5's nights)
  and the rest assumed in `ledger/volumes.yaml`; the error budgets are a simulated month's, built from kept runs that are few (W2's
  read failure is one question in 90, W3's stops 8 of 48); the budget events are a drill's on a month seeded through the
  admin API; and no kept run holds a person's decision, so every outcome is an assumption and W4's outcome event is not
  emitted by anything (steps 2, 4, 6).
- Price everything. No source prices Gemini's tokens in Montréal, the two enterprise licenses, or chapters 7 and 8's
  private endpoints, so they stay parameters; us-east-2's EC2 prices stand in for ca-central-1's; the guardrail is an
  estimate from tokens, since no cost line carries it; and the break-even is missing for all four committed products,
  since section 8.8 holds no matching on-demand rate (steps 2 and 5).
- Count tokens on the managed model beyond W1's. The other workflows' kept runs ran on gpt-oss-20b and Gemma 4 12B, and
  the Nova Lite ratios come from 17 cases of one workflow (step 2). W3's and W4's judged outputs kept no tokens at all, so
  the judge's ratio for those two rests on step 3b's run of the same case (step 9).
- Evaluate a control. Nothing checks a kept or a simulated run for a residency, never-list, or budget breach, so the
  review says the breaches are not evaluated and prints no count; the gateway's refusal counts could stand in for a
  check, and no step reads them for one (step 9).
- Keep the share a trace was kept at past the Collector. The file exporter and the two feature gates are alpha, and
  neither CloudWatch nor Langfuse keeps the tracestate (steps 3 and 7).
- Run more than one cloud session. One account, one day, us-east-2 alone; ca-central-1's logs are unreadable under the
  SCP, the console's views are unmeasured, Langfuse's backup and restore were not tried, and chapter 6's one-statement
  trust policy is untested (step 7).
- Drill the platform's failures beyond one proxy and one store: no second gateway Region (O-D17), no proxy killed with
  calls in flight, no fleet behind a load balancer, no managed database failover, no store persistence, replication, or
  slow store, no Collector restart, no audit store loss, no replica failover, no fork restore, and the self-hosted
  replicas were not loaded with W3's whole traffic during an outage (steps 5 and 5b). A Confidential call that falls
  back to the self-hosted alias carries no `cache_salt`.
- Set `max_tokens` in chapter 5's harness, so the alarm and the stop stay one reservation early; put back the spend a
  database outage loses; or join a refusal at the key to its run (steps 4 and 5).
- Run a pager, run the probe against a live gateway, name the source of the Foundry sessions panel, settle the
  workbook's 1,000x by its definition, or model a response to an alert in the simulated month (step 6). The playbook
  names six symptoms the lab emits nothing or only part of, and `oncall.py` has no command for the rate or the remap.
- Run the other five golden sets on the candidate, run the live job after the remap, accept a baseline, promote, keep a
  run's calls on one arm, or run the two models on two servers (step 8).
- Open a console or a dashboard, compute chargeback, deploy a second Region, detect anomalies with a model, page anyone,
  export FOCUS, buy committed capacity, or handle PII in traces beyond the collector's content drop (O-D17).

## Run

```
cd labs/ch16
python ledger/report.py --out results/<date>   # every table, the summary, the JSON, and the cost lines, 13 seconds
python ledger/costlines.py                     # the cost lines, counted per workflow
python ledger/price.py --write-litellm         # after prices.yaml changes; then review the diff
python ledger/litellm_map.py                   # the table against LiteLLM's built-in map
python ledger/month.py                         # the month and the allocation of the GPU hours and the fixed costs, as JSON
python ledger/judge_lines.py                   # step 9: chapter 15's judge against what it judged, from its logs, with the
                                               #   conclusion on ch15:156 as data
python collector/fetch.py                      # once: the pinned Collector, checked, into collector/bin/
python collector/run_local.py                  # step 3's run, about four minutes; raw records in collector/_lab/
python collector/analyze.py collector/_lab/<stamp> --out results/<date>/collector
python collector/join.py <trace id>            # one run from every store; --stores, --cloudtrail, --event
python collector/run_workflows.py w2           # step 3b, one run a process: w2, w3, w4 --model <model>,
                                               #   w5 --wait step3 or root; raw records in collector/_lab/
python collector/analyze_workflows.py collector/_lab/<stamp>-<run> ... --out results/<date>/workflows
python collector/run_workflows.py w3 --only w3-01   # the follow-up's one case; one_trace.py keeps it
python collector/one_trace.py collector/_lab/<stamp>-w3-gpt-oss-20b-smoke collector/_lab/<stamp>-w4-gpt-oss-20b-smoke --out results/<date>/one-trace
python budget/postgres.py                      # once: PostgreSQL 16.15, checked, into budget/pg/
python budget/smoke.py --out results/<date>/budget --prisma-home <short folder>
python budget/drills.py --out results/<date>/budget   # step 4's drills, about five minutes
python budget/drills.py --summarize results/<date>/budget
python budget/oncall.py kill w2-ops-assistant --by <lead> --change <number> --reason <why>
python budget/receiver.py --port 8899 --outbox budget/_lab/alerts.jsonl   # the webhook receiver alone, on 127.0.0.1
python budget/identity.py pull --manifest ../ch05/manifest/w3-incident.yaml --dry-run
python capacity/run_drills.py --out results/<date>/capacity   # step 5's drills, about 65 minutes
python capacity/run_drills.py --limiter-cache results/<date>/capacity    # the limiter-cache drill alone, 12 minutes
python capacity/run_drills.py --summarize results/<date>/capacity
python capacity/repeat_write.py                # the repeated-write check alone, with W3's code
python capacity/calculator.py --workflow w2    # --product <id>, --on-demand-input and --on-demand-output in USD
python capacity/calculator.py --report results/<date>/capacity    # calculator.json for W2 and W3
python capacity/fake_provider.py --name primary --port 8811 --tpm 100000    # the fake provider alone
python capacity/garnet.py                      # once: Garnet 2.2.5, checked, into capacity/garnet/
python capacity/run_5b.py --out results/<date>/capacity   # step 5b's drills, about 65 minutes
python capacity/run_5b.py --only stopped --out results/<date>/capacity   # one part: probe, contention, cache,
                                                          #   latency, stopped or outage, repeatable
python capacity/run_5b.py --summarize results/<date>/capacity
python slo/run_slo.py --out results/<date>/slo        # step 6: the SLIs, the simulated month, the rest, 4 seconds
python slo/run_slo.py --summarize results/<date>/slo  # the summary again from the committed files
python slo/simulate.py                                # the month's runs, counted by workflow and end
python slo/probe.py w3 --gateway <url> --key-env <variable>   # one probe; --every 3600 for the hourly one
cd cloud/terraform && terraform init && terraform apply -var-file=<secrets>.tfvars -target=aws_budgets_budget.session   # step 7: the budget first
python cloud/cloud_budget.py start --out results/<date>/cloud          # then end, before the destroy
python cloud/transaction_search.py on --out results/<date>/cloud       # status, off; in a step of its own
terraform apply -var-file=<secrets>.tfvars -var instance_type=m7i-flex.large   # the rest; the free plan refuses t3.xlarge
python cloud/langfuse_vm.py wait --out results/<date>/cloud            # then tunnel --local-port 3100, held in a second console
python cloud/export_run.py --langfuse http://127.0.0.1:3100 --out results/<date>/cloud
python cloud/bedrock_calls.py calls --out results/<date>/cloud         # then cloudtrail, minutes later
python cloud/tool_role.py run --trace-id <a trace id of the live run> --out results/<date>/cloud
python cloud/tool_role.py cloudtrail --stores results/<date>/cloud/export-run --out results/<date>/cloud
python cloud/cost_explorer.py --out results/<date>/cloud
terraform destroy -var-file=<secrets>.tfvars -target=aws_instance.langfuse   # as soon as Langfuse's check is recorded
terraform destroy -var-file=<secrets>.tfvars                            # everything else, after the budget's end read-back
python cloud/leftovers.py --json results/<date>/cloud/leftovers.json   # then tools/cloudcheck/aws_sweep.py from the book's root
python cloud/cloud_summary.py --results results/<date>/cloud
python lifecycle/register.py --check                   # step 8: the register against the gateways and the Terraform
python lifecycle/register.py --digests http://127.0.0.1:11435   # the local pins against what that Ollama reports
python lifecycle/retirement.py --on 2027-02-01         # the retirement alert for a date; --json for the file's shape
python lifecycle/upgrade.py --out results/<date>/lifecycle --passes 4   # the whole path, about 12 minutes on the GPU
python lifecycle/upgrade.py --out results/<date>/lifecycle --only canary --passes 4   # one stage alone, in the path's order
python lifecycle/upgrade.py --out results/<date>/lifecycle --only summarize           # the summary again from the files
python lifecycle/canary.py --passes 4 --out results/<date>/lifecycle    # the canary alone, which upgrade.py's canary stage runs
python lifecycle/lifecycle_summary.py results/<date>/lifecycle          # summary.md again from the files in that folder
python lifecycle/remap.py promote --config lifecycle/litellm.canary.yaml --candidate lifecycle/litellm.staging.yaml \
    --out <folder>/litellm.promoted.yaml --change <number> --by <who> --reason <why>   # or back --previous ...
python review/monthly_review.py --month 2026-11 --on 2026-11-09 --out results/2026-11-09/review   # step 9: the review, 4 seconds
```

`price.py --check-litellm` needs `LITELLM_LOCAL_MODEL_COST_MAP=True` in its environment and refuses to
run without it; `litellm_map.py` sets it before it imports LiteLLM. The report runs both in processes of
their own with the variable set and the network blocked, since a Router changes LiteLLM's price map for the
rest of its process, and it blocks the network in its own process too. Two runs write the same bytes; the
report takes about 13 seconds, the judge's 1,439 lines included. The environment is chapter 5's (`pip install -r ../ch05/requirements.txt`),
for PyYAML, numpy, and litellm 1.106.6.

`run_local.py` needs the same environment and ports 8801 to 8803 free, the ones chapter 5's gateway config
names for its fake backends. Its own process refuses every connection that would leave the machine, the
processes it starts talk only to each other and to the Collector on 127.0.0.1, and the Collector's
environment holds dummy credentials alone. `analyze.py --summarize results/<date>/collector` writes the
summary again from the committed files, and two runs of it write the same bytes.

`run_workflows.py` needs the same environment, which runs the four workflows' code too, and the models:
Ollama 0.22.1 serving gpt-oss:20b on 11434 and, for `w4 --model gemma4-12b`, the portable Ollama 0.40.13 on
11435. It refuses to start while the other Ollama holds a model, so one model is on the GPU at a time. Its
own process refuses every connection that would leave the machine, and the gateways it starts read LiteLLM's
price map from the wheel. W2's run writes a fresh membership table first, since W1's goes stale after 36
hours. `analyze_workflows.py` copies each workflow's results and cost lines to its `eval/traced/<date>/` and
writes the summary, and `analyze_workflows.py --summarize results/<date>/workflows` writes it again from the
committed files, the same bytes each time. A run with `--only` is a smoke run, which `analyze_workflows.py`
refuses to keep; `one_trace.py` keeps the follow-up's two, w3-01 and `w4 --model gpt-oss-20b --only w4-01`, with
nothing written to the workflows' `eval/traced/`, and `one_trace.py --summarize results/<date>/one-trace` writes
their summary again from the committed files.

Step 4's smoke test and drills need chapter 5's environment plus Prisma's client, `pip install -r
../ch05/requirements.txt "prisma>=0.11.0,<1.0"` (prisma 0.15.0 and nodeenv 1.12.0 on 3 November), with the
environment's `Scripts` folder on PATH, as activating it puts it; the drills run `prisma generate` once
through the smoke test, or by hand with `python -m prisma generate --schema <litellm>/proxy/schema.prisma`.
Prisma fetches its CLI from npm and its engines on first use, so that first run needs the network, and Node
on PATH (22.19.0 here) or nodeenv. Its home must be short (`--prisma-home`), since npm works about 110
characters below it and Windows refuses a working directory of 260 characters or more. Everything else runs on
127.0.0.1 with ports chosen free, and the proxy gets a console of its own with its window hidden.
`identity.py` without `--dry-run` calls IAM with the credentials in its environment, which this step never
does; step 7 runs it.

Step 5's drills run in step 4's environment, with step 4's PostgreSQL in `budget/pg/` (`budget/postgres.py`) and
Prisma's client generated. Every process they start listens on 127.0.0.1 on a port chosen free: the fake
providers, PostgreSQL, step 4's webhook receiver, and the proxy, given a console of its own as in step 4. A drill
that stops a fake provider leaves its port refusing connections, which is how the outage drill makes a connection
error. The raw records stay in `capacity/_lab/drills-<stamp>/` and `capacity/_lab/census-<stamp>/`, which git
ignores, and two runs of `--summarize` write the same bytes. `repeat_write.py` and `calculator.py` need chapter 5's environment only; the repeated-write check
runs W3's approval service on 127.0.0.1 and imports W3's code and W3's test fixtures, changing nothing in W3.

Step 5b's drills run in the same environment, with redis-py 8.1.0 from chapter 5's requirements, and Garnet 2.2.5 in
`capacity/garnet/`, which `capacity/garnet.py` fetches once from the project's GitHub release, the one step that needs
the network, and checks at every start. Garnet's build needs the .NET 10 runtime (10.0.14 on this workstation). The
store listens on 127.0.0.1 on a port chosen free, with a password made for the run; its settings go in a file the
store reads at its start, deleted once it answers, so the password is on no command line. Each drill stops the store,
the proxy, the fakes, the receiver and PostgreSQL by their process ids and records the ids it stopped and that none
was left. The raw records stay in `capacity/_lab/step5b-<stamp>/`, and two runs of `--summarize` write the same
bytes.

Step 6 needs chapter 5's environment only, and no model, no gateway and no network: `run_slo.py` blocks every
connection that would leave the machine, reads the kept runs and step 5's committed results, and writes the same bytes
from any process. The rung down runs as a dry run in a temporary folder that `budget_policy.py` removes. `probe.py`
without its tests sends real calls to the gateway it is given, with the key in the variable it names, and appends one
line a probe to `slo/_lab/probe.jsonl`, which git ignores.

Step 7 runs in chapter 5's environment with the AWS CLI (2.28.21 here), Terraform 1.13 and OpenSSH on the path, and the
lab account's profile given through the environment alone: `AWS_SHARED_CREDENTIALS_FILE` at a credentials file
outside this repository, `AWS_CONFIG_FILE` at a path that doesn't exist, `AWS_PROFILE=book-lab` and
`AWS_DEFAULT_REGION=us-east-2`; `cloud_session.require_environment` refuses anything else, and no script opens the
credentials file. The Langfuse secrets go in a tfvars file outside the repository (git ignores `*.tfvars` anyway), and
`LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` in the environment are the same keys for the Collector and the checks. The
order above is the session's: the budget before anything else, Transaction Search in a step of its own, the VM destroyed
as soon as its check is recorded, the budget read back before the destroy, and the two sweeps after it. The scripts
write to `results/<date>/cloud/` through `cloud_session.redact`, and the raw records, the tunnel's key pair, and the
gateways' logs stay in `cloud/_lab/`. The destroy of the tool role needs `tool_role.py run` to have reached
`release --purge`: `force_detach_policies` removes managed policies and not the inline `larkspur-kill-switch`, so a
run that died between the pull and the purge leaves the destroy failing with `DeleteConflict` until
`python budget/identity.py release --purge --manifest ../ch05/manifest/w3-incident.yaml --role w3-incident-get-pod-status`
has run.

Step 8 runs in chapter 5's environment (which runs W2's harness and servers and chapter 15's live job), with python-hcl2
for chapter 8's Terraform, and with the portable Ollama 0.40.13 started on 11435 alone
(`OLLAMA_HOST=127.0.0.1:11435 <larkspur-lab>/ollama-v0.40.13/bin/ollama.exe serve`) and stopped afterwards by its process
id with the tree flag (`taskkill /PID <pid> /T /F`), never by image name, which would also stop the Ollama on 11434. The
two lifecycle configurations and the canary's put every deployment on that one server, since the two models don't fit
the card together and two servers on one card would push the second model to the CPU; the server swaps them, and the
run measures the swaps. `upgrade.py` blocks every connection that would leave the machine, the gateways it starts read
LiteLLM's price map from the wheel, and the raw records (the live job's scratch, the canary's passes, the gateways' and
W2's servers' logs) stay in `lifecycle/_lab/`, which git ignores. `register.py --check` and `retirement.py` need neither
the GPU nor a server; `--digests` asks the Ollama it names and nothing else.

Step 9 needs chapter 5's environment only, and no model, no gateway, and no network: `monthly_review.py` blocks every
connection that would leave the machine, reads the newest dated results folder that holds each of its inputs, W5's ledger,
the register, and the manifests, and writes the same bytes from any process. `--month` and `--on` default to November
2026 and 9 November 2026, the month the kept runs and the drills fall in and the day the register was read. Another
month or date reads the same files: a month in which W5 ran no night says so, and an input that doesn't exist stops the
run before anything is written. `ledger/judge_lines.py` needs the same environment and reads chapter 15's judge logs
alone.

## Test

```
cd labs/ch16
python -m pytest tests -q
```

The 593 tests take about two minutes and make no network call beyond 127.0.0.1; `conftest.py` blocks every connection
that would leave the machine, for the tests and every process they start. The 24 tests that run the pinned Collector
skip when `collector/bin/` doesn't hold it, and fail when it holds a binary other than the pinned one; the one that
runs PostgreSQL skips when `budget/pg/` doesn't hold the pinned binaries, and the two that run Garnet when
`capacity/garnet/` doesn't hold the pinned build. Step 4's smoke test and the drills of steps 4, 5 and 5b need
Prisma's client, and step 5b's need Garnet as well, so they run by hand (Run, above); the tests read what they
recorded:

- `test_prices.py`, 7 tests: a source, a date and a page on every entry; the values copied from the cost
  sheets read back from the sheets; the quotes from the fact sheet carry every number; the rates confirmed
  on 3 November; a reason or the vendor's words for every null; chapter 6's design prices every alias a
  kept run asked for; the Canadian profile about 7 percent above us-east-2.
- `test_costlines.py`, 10 tests: every output a run and every call a line, against each workflow's own count;
  step 3b's runs outside chapter 15's registry, which keeps its 26; step 3b's lines the gateway's own, one a
  call, joined to each case by its trace id, W2's tokens the harness's own record of each call; one shape from
  each workflow; the Nova Lite run's served models; W5's lines against each night's record; W4's one call per
  change; tool calls where kept; no fallback; no model tag by guess.
- `test_price.py`, 11 tests: a line at its alias's deployment, a fallback at its own Region's price, zero on
  the restricted alias, no cost (never zero) without tokens, W1's Nova Lite calls priced as the gateway
  priced them, the guardrail's text units, the generated YAML, and LiteLLM 1.106.6 charging the custom
  prices, skipping budget checks on the zero-priced alias only, pricing the Canadian name alone at zero,
  and refusing to run without the local map.
- `test_litellm_map.py`, 4 tests: the wheel's map in use, every difference as listed, section 8.1's probe
  reproduced, and the prices the map can't hold.
- `test_report.py`, 5 tests: nearest rank, a row for every workflow and model with W3's and W4's tokens from
  step 3b's runs, W2 against chapter 3, chapter 11's prompt sizes, and the token counts across models.
- `test_month.py`, 5 tests: a source for every volume, the month against `per_month_usd` with W3 and W4
  measured, step 2's month back from chapter 15's runs alone, the GPU hours split into tenants and idle on
  both readings, and the fixed costs adding up with the parameters left out.
- `test_sampling.py`, 5 tests on synthetic months: exact at full sampling, head sampling unbiased, naive
  tail scaling biased and weighting not, over-budget runs always kept; and the experiment on the kept runs
  reproducible.
- `test_results.py`, 4 tests: the committed results, in the newest folder that holds the ledger, are what the report
  writes; two reports in two processes write the same bytes; the README's tables are the ledger summary's, except those
  of the sections of steps 3 to 9 that the tests of their own results read (the judge's section of step 9 is checked
  here); and the network block holds.
- `test_collector_config.py`, 17 tests: the binary's `validate` accepts `config.yaml` and rejects a statement
  that doesn't parse, while a bad tail-sampling condition passes it and stops a start; the content drop holds
  every opt-in attribute of the pinned span definitions, for spans and span events in two groups, and fails
  closed; every manifest says `trace_content: false`; the policies and their order, with `over-budget` from
  the manifests' `per_run_usd`; the receiver on loopback; CloudWatch's endpoint and SigV4 settings;
  Langfuse's basic auth from the environment and its header; the cost copy on the Langfuse pipeline alone;
  the span file appended to; what the overlay changes; dummy credentials only; a tarball or a binary other
  than the pinned one refused; and the binary here the pinned one.
- `test_collector_run.py`, 18 tests on the pinned binary, with synthetic spans and a 2-second
  `decision_wait`: every content attribute dropped from spans and span events and nothing else, and the same
  statements in one list leaving the arguments on a span without events; each keep-all policy keeping its
  trace and recording itself at a share of one; traces just short of a policy left to the share; the share
  as the FNV-1a hash, recording ten percent; the same spans in the file and at both fakes; the cost copy at
  Langfuse alone; Langfuse's basic auth and header; CloudWatch's SigV4 signature, valid for the dummy secret
  and no other; a root that arrives after the decision missed; and the whole trace judged with the root
  trigger.
- `test_policies.py`, 15 tests: FNV-1a against its reference vectors, the threshold as the processor computes
  it, the share read from eight tracestates, each policy at its edge, the recorded policy and share, the
  hash's need for random trace ids, the settings from `config.yaml`, and template attributes.
- `test_otlp_fakes.py`, 4 tests: the recorded CloudWatch request's signature, from the dummy secret and not
  after one byte of its body changes; the check against botocore's signer; a fake reading gzip protobuf and
  JSON as the same spans and refusing another path; and the span file read back.
- `test_join.py`, 9 tests: one run from every local store, a dropped run with its logs and cost lines, the
  printed tree, the README's example as `join.py` prints it, CloudTrail events by session name, tag and
  access key, a session name with no tag, the run behind an event, LookupEvents output and JSON lines, and
  the trace id's form.
- `test_collector_results.py`, 10 tests: the summary is what `analyze.py` writes from the committed files;
  every kept run in all three stores with the same spans; one trace id across the logs and the cost lines;
  the five runs made to be kept did what they were made for; the decisions and the shares recorded; no
  content attribute in any store; the delay within `decision_wait` and 2.5 seconds more; the headers and the
  cost copy; the README's step 3 tables are the summary's; and no path or name of this machine in the
  results.
- `test_workflows.py`, 15 tests, 2 of them on the pinned binary: the local config is `config.yaml` without
  CloudWatch and Langfuse and nothing else, with no credential in its environment, and the binary validates
  it with the run's overlay; the root trigger brings a decision forward and never past `decision_wait`; and
  step 3b's committed results: the summary is what `analyze_workflows.py` writes from them, every span sent
  was kept and left through the sink, each case's gateway lines are its own calls, which processes sent spans,
  what a run's trace id holds in each workflow, fig-16-01 from W2's real trace and as `join.py` prints it, W5's
  night under the two settings, what 10 percent would keep, the README's step 3b tables, and the runs kept
  beside each workflow's results with no path of this machine.
- `test_one_trace.py`, 5 tests: the follow-up's summary is what `one_trace.py` writes from the committed files;
  w3-01 and w4-01 each one tree under its harness's span, every span under the case's trace id, each model call's
  span inside it, and nothing elsewhere; step 3b's rows for the same cases with more than one root; the tree
  check on small fixtures; and no path of this machine in the results.
- `test_budget_postgres.py`, 7 tests: the pin names one file and one digest; only the server's `bin`, `lib` and
  `share` unpacked; a member that would land outside the folder refused; a zip other than the pinned one refused;
  every start checking the programs against the zip; `pg_ctl start` never waiting on a pipe; and a cluster on the
  pinned binaries that listens on 127.0.0.1, takes only its run's password, and stops.
- `test_budget_keys.py`, 24 tests: each of the eight manifests gives its key (alias, models, `max_budget`, the soft
  budget at 80 percent, `1mo`, the metadata, no tags); the reset at midnight on the 1st in Toronto at six moments,
  and LiteLLM's own `get_next_standardized_reset_time` at the same six; five hours early at UTC; the config the
  drills rely on; the aliases served where chapter 5's are, at its stand-in prices; and the month by Toronto's
  calendar.
- `test_budget_binding.py`, 11 tests: eight cases of a key and its tags; the callback's 400, its log line, and the
  phrase that keeps chapter 5's failure hook from logging it twice; an agreeing request passing unchanged; and the
  tags read as chapter 5 reads them.
- `test_budget_stops.py`, 16 tests: eleven refusals classified, LiteLLM's 422 and FastAPI's among them; the message
  read from three shapes; a 422 ending a run after one call through chapter 5's `GatewayModel`; a blocked key as the
  kill switch; a rate limit the only retry; and the tally.
- `test_budget_receiver.py`, 4 tests: the owners from the manifests; an alert to the owner and FinOps, and one for an
  unknown key to FinOps alone; each alert named for what it is, LiteLLM's projection included; and the app
  recording what LiteLLM posts, built with LiteLLM's own `WebhookEvent`.
- `test_budget_oncall.py`, 4 tests: `kill` blocking the key found by its alias, by its hashed token, with its change
  record; `reopen` and both records; an alias naming exactly one key; and a refused admin call.
- `test_budget_rungs.py`, 26 tests: no override; an override that lowers the rung and drops every write; three that
  would raise it; fourteen malformed files failing closed; the write reaching its tool at the manifest's rung and
  refused before it is called at rung 1; reads at rung 1; a malformed file stopping the run before any call; the
  record of each change; and the override written whole.
- `test_budget_identity.py`, 9 tests, all on botocore's Stubber with no AWS call: chapter 6's role names; the pull
  document; `pull` on the harness role and every tool role; a role of another workflow left alone; a missing role
  reported; `release` keeping the revoke, moved to the release; `--purge`; a dry run that calls nothing; and role
  names IAM accepts for every manifest.
- `test_budget_results.py`, 16 tests: the summary is what `drills.py` writes from the committed files; the README's
  step 4 tables are the summary's; the smoke test's run and probe; each key's reset; the kill switch both ways; the
  alert to the owner and FinOps, and every alert named; the 422 counted and never retried; the restart and the
  reset; the key binding; the rung down; every lever's change record; and no path, key or password of this machine
  in the three files.
- `test_capacity_provider.py`, 10 tests, the fake provider driven in-process: a reservation that fits until the
  window is full and the wait it is told; settling at what was used; a request larger than the quota; Retry-After in
  whole seconds; the estimate from the prompt and `max_tokens` or the default; the usage an answer reports; the
  429's headers; the failure modes and the forced throttle; the burndown; and chapter 5's rule model for tools.
- `test_capacity_retry.py`, 19 tests: the `honour` policy's waits and its six attempts; `retry-after-ms`, then
  `Retry-After`, then LiteLLM's `llm_provider-` forms; the SDKs' backoff with no wait given; only 429, 503 and 529
  retried, and never past the deadline; the naive policy; twelve answers named for the limit that gave them; a
  prompt the size the ledger says; and a throttled run of each policy against the fake on 127.0.0.1.
- `test_capacity_calculator.py`, 13 tests: every term priced from the dated table, which this step left at 49
  entries; the fact sheet's words on every product and a comparator or a reason; the Reserved tier's minimums,
  input and output apart; the regional PTUs rounded up to fifty; the GSU's burndown; a model unit of unknown size;
  the commitment winning exactly when utilization passes the break-even, at four duty cycles; the busy hours from
  the ledger; the committed `calculator.json`; and the CLI with the on-demand rate the table lacks.
- `test_capacity_repeat.py`, 7 tests, W3's approval service, writer, store and harness, unchanged: the first run's
  write and the pod lost after it; the same run resumed, which verifies; run A's approval refused to run B, and
  refused again to a harness without run A's store; run B's write only after a person approves it; every refusal in
  the approval service's log; and the drills' record of the same cases.
- `test_capacity_configs.py`, 9 tests: the outage config's `allowed_fails` and `cooldown_time` written out on chapter
  5's routes and prices; the deployment config's limits and its explicit `max_parallel_requests` on step 4's
  gateway; the census configs, step 4's with the census callback and one without its alerts; the retry config's
  groups; the hooks this folder names, loaded in a process of their own; no module name shared with another folder
  on the tests' path; and the continuity table, a row for each component the plan names, every number it cites
  found in its drill.
- `test_capacity_census.py`, 5 tests, the census callback on LiteLLM's own in-memory cache: a key's kind with its
  ids taken out; a snapshot's size, its kinds and the limiter's entries with the time each has left; a full cache
  dropping the limiter's window and counter before the request statuses; and a line a call, none when no file is
  named, and never a failed call.
- `test_capacity_results.py`, 18 tests: the summary is what `summary.py` writes from the committed files; the
  README's step 5 tables are the summary's; the contention numbers recomputed from every request; W3 served at
  once under the per-key limits in every round and not under the others; the burst spending W2's request rate,
  the key refusing nothing after the burst's first seconds, and the provider refusing W3 only after the burst; the
  limiter-cache drill's numbers recomputed from its requests, the cache full and the windows evicted on step 4's
  gateway, and kept without its alerts; the deployment limits counting too late; naive retries against honoring
  ones; where the router waits; the gateway's own time against the baseline with no gateway; the cooldown's cycles
  in each mode; W2's fallback and W3's error inside each manifest's Regions; the runs in flight; the database
  stopped, and its numbers recomputed from every call; and no path, key or password of this machine in the
  results.
- `test_capacity_store.py`, 14 tests, 2 of them on the pinned Garnet: the pin names one asset, one digest and its
  size, and git ignores `capacity/garnet/`; only the server's own files unpacked, and nothing outside the folder; a
  zip or a program other than the pinned one refused; the server on loopback with a password, its scripts run whole;
  a throwaway store that answers its own password alone, empties, and stops by its process id; LiteLLM's
  check-and-increment admitting exactly the limit in transaction mode, and its scripts answering as Redis answers;
  the watch alerting once after two missed pings and once when the store answers again; the alert naming the store
  and never carrying its password; the ping reading `+OK` and `+PONG` and naming what went wrong; both alerts sent
  through the webhook as a store goes and comes back; the receiver sending them to the platform's on-call alone; a
  window counted as evicted only when it leaves the store with time still to live; the census reading the store off
  the call path; and the store configs, step 4's gateway with the store and the alert and nothing else.
- `test_capacity_fallback.py`, 6 tests: the Canada config is step 5's outage config with the section and the
  callback, and chapter 5's config is unchanged; chapter 5's rules turning W3's chain off and leaving W2's on; the
  grid letting a Confidential call reach the self-hosted alias in ca-central-1 and not the fallback in us-east-2; a
  request given only the named hops its class and Regions allow, and a Restricted call none; the callback giving W3
  its hop, marking the metadata and writing its line, and leaving W2's request alone; and the new callbacks loaded by
  file, in a process of their own, as LiteLLM loads them.
- `test_capacity_5b_results.py`, 15 tests: the summary is what `summary_5b.py` writes from the committed files; the
  README's step 5b tables are the summary's; the fetch record is the pin; Garnet running LiteLLM's scripts as Redis
  does, and running them whole only in transaction mode; the contention numbers recomputed from every request; the
  keys' limits holding through step 4's alerts with the windows in the store; the limiter-cache rounds on the store;
  with the store stopped, LiteLLM's default carrying on from a memory that holds no window, and, failing closed, the
  gateway refusing every keyed call until the store is back; the alert reaching the platform's on-call both ways in
  each round; every process the drills started stopped; W3 served in Canada through every failure mode, and W2 as
  before; on step 5's config, W3 waiting out the cooldown and ending as model unavailable a run it can't wait for;
  the continuity rows step 5b changes citing only what its drills found; and no path, key or password of this machine
  in the results.
- `test_slo_slis.py`, 12 tests: an unknown end, decision, control or unit refused; success, latency and outcome, what
  each counts good, bad and not at all; a breached control an incident and never budget spent, in the SLIs, the burn
  rates and the budget accounts alike; the probe's runs spending no budget; the sentences the harnesses' own; W2's
  step-budget stops told from its refusals by the calls; W1's search limit a refusal and W3's stops its own sentence;
  W5's decisions its ledger's; the committed measurement the kept runs'; and a source and a lack for every SLI.
- `test_slo_month.py`, 14 tests: the month marked simulated and refused otherwise; seeded, the same twice and
  different on another seed; the ledger's volumes and W5's nights at 02:00 ET; every run one of the kept runs the
  file names; the shapes read from step 5's files, the outage's cooldown among them; each of the five injected
  events doing what month.yaml says, and touching no run outside its window, with no W4 or W5 run in the outage and
  the outage's shape driven on a W4 run of its own; the decisions as assumed; and the events each budget expects.
- `test_slo_burn.py`, 12 tests: the workbook's table as the fact sheet quotes it, with its three short windows; the
  burn rate's definition; the workbook's ten requests an hour and its 13.9 percent, with the 1,000x the definition
  doesn't give; a low target leaving the page unable to fire; episodes, their continuation, the short window that ends
  a page five minutes after the burn and not an hour, and attribution; the three designs; W5's tickets, the fourth
  failed run spending the budget of 3.4; the platform's page on 429s across workflows, and which platform rules
  burn.py evaluates; and the outcome SLI never paging.
- `test_slo_policy.py`, 7 tests: who decides and the record of every action, and the workbook's line; a budget in
  events; when a budget is spent, and the month an outcome counts in; W3's rung down through step 4's switch in a dry
  run, read back as the harness reads it; one freeze a workflow, told to its owner and sponsor; and no rung below
  for W1 and W2.
- `test_slo_probe.py`, 9 tests against a fake model on 127.0.0.1: the cases from the kept first calls; what the probe
  sends; a 500, a 429 and an empty reply, a late answer, and no gateway, each a bad probe; its cost line priced like
  any line; and the month's lines at the kept tokens.
- `test_slo_results.py`, 13 tests: the committed results what `run_slo.py` writes from another process; the summary
  what `--summarize` writes; every simulated file marked; the month table and the policy counting every SLI by one
  rule; the green probe hiding W3's failures that its own traffic
  pages; the group missing W4's complete failure; the alerts and the policy citing only what the month holds;
  fig-16-03's workflow and its data; the dashboard's panels and the Foundry panel open; the probe's cost; the README's
  step 6 tables the summary's; no path of this machine in the results; and no module name shared with another folder.
- `test_playbook.py`, 6 tests: a row for each of O-D13's symptoms; a signal, two levers and what isn't emitted on
  every row; the four levers with their records under ch02:163; the commands the lab's; every file and alert the
  playbook names in the lab; and the runbook taking every symptom and command.
- `test_cloud_terraform.py`, 11 tests: the provider pinned and every resource tagged as the session's; us-east-2 alone;
  the budget first, with an SNS subscriber and no address, and every root resource waiting for it; no security group
  rule naming the internet, and the endpoint without client IP preservation; the VM from Canonical's parameter with
  IMDSv2 and a disk that goes with it; the tool role's trust policy in the amended O-D2's shape, with the session name
  the script makes fitting it and chapter 6's not; text delivery off to start; the Compose file at its pinned SHA-256
  and the override pinning its two images; the user data's markers; no ARN in the outputs; and `terraform validate`
  and `fmt` when the folder is initialized.
- `test_cloud_scripts.py`, 26 tests, every AWS call answered by botocore's Stubber: the redaction, idempotent and
  distinct per key; the environment check; the budget read back; Transaction Search's status, its three calls and
  their reversal; the requestMetadata hook, through LiteLLM's own Converse transformation, and the two gateway
  configs; the invocation record's shape with text off and on, and CloudTrail's Converse events; the tool role's
  AssumeRole request, the refused shapes, and the deny-all drill timed on stubbed answers; the trace id found in a
  CloudWatch record; the Langfuse comparison; Cost Explorer's rows and the reconciliation in tokens; the live run's
  overlay and the tunnel's command; and the sweep's names against the Terraform's.
- `test_cloud_results.py`, 10 tests on the committed results: every file there; the summary what `cloud_summary.py`
  writes; the README's step 7 tables the summary's; nothing kept naming the account, a key, a principal, an address,
  a public IP address or this machine; `join.py` printing `join.txt` again from the kept stores and events, both
  ways; and the measurements the README cites, store by store.
- `test_lifecycle_register.py`, 10 tests: the register's shape; the register and the gateways naming the same
  deployments; the models per cloud and the six Larkspur runs on; every model of chapters 6, 7 and 8's registers in it
  with its dates and stage; the Claude pins without a version, and saying so; a local pin a digest on a named server,
  the vLLM deployment's revision and digest list, and the other server's digest for the same tag beside the pin; an
  unregistered or misnamed deployment reported, and a register deployment a configuration lacks; the two Terraform
  files read as chapters 7 and 8 read them; the identifier behind a provider prefix; and the excluded configurations
  holding fakes alone.
- `test_lifecycle_retirement.py`, 8 tests: the rules the code fires are the file's; a date before the window (a
  review row, no ticket, and a model four days from retirement that Larkspur doesn't run on reviewed and not
  ticketed), inside it (the two tickets, with the replacement in each), and past it (two pages, none for a retired
  model Larkspur doesn't run on); no alert for a model with no published date, its earliest date shown; the Legacy
  notice for a pinned model in a notice stage alone; the window's edges on a synthetic register; and the rendering.
- `test_lifecycle_canary.py`, 8 tests: the current map W2's on the portable server; the staging map with the candidate
  behind the alias alone and thinking off; the canary's two weighted deployments on one server; chapter 5's rules
  accepting each configuration for W2 and refusing a class above its maximum and an alias outside its manifest; the
  arms, groups, ends, and loads from a synthetic gateway log with the watcher's samples; the SLIs three ways; and the
  watcher's summary.
- `test_lifecycle_decision.py`, 5 tests: a regression ends the path; too few runs extend the canary; a candidate below
  the control is remapped back; not below on every SLI promotes, equal included; and the latency key recorded.
- `test_lifecycle_remap.py`, 6 tests: a promotion moves the alias to the candidate alone and keeps the rest, accepted by
  chapter 5's rules, with the record's fields and one line in `changes.jsonl`; a remap back writes the configuration
  before, whole; two remaps, the second reading the first; a remap to where the alias already is refused, with no
  record; the header and the names the record carries; and the alias's tenants from the manifests.
- `test_lifecycle_results.py`, 12 tests on the committed results: every file there and nothing else; the summary what
  `lifecycle_summary.py` writes from them; the README's step 8 tables the summary's; the register check clean with every
  digest matched; the retirement file what the code computes for its three dates; the gate's rows W2's checks, with the
  pins a remap changes; the canary's counts adding up, run by run and call by call; the decision the rule on the files;
  the remap matching the decision with its record and its probe; fig-16-04's six stages with the run's numbers; no
  path of this machine; and no module name shared with another folder, chapter 15's included.
- `test_judge_lines.py`, 12 tests: every judgment counted once, with chapter 15's totals (1,439 calls, 1,231,927 and
  338,238 tokens) and its six runs' counts; each a line under the workflow judged, marked as the judge's, under the
  judged workflow's tag, with the line's own `kept_run` format, and the workflows' own runs carrying none of it; the
  judge's lines after the workflows' in `costlines.jsonl`, only they carrying the fields, and the workflows' lines byte
  for byte as before; nothing else in the committed ledger moved (the JSON without the judge's section, and the summary
  before section 14, at the hashes of the files as committed before step 9); the judged outputs' tokens measured for W1,
  W2, and W5 and step 3b's stand-in for W3 and W4, with one call a body in W5; the ratios pinned and where the sentence
  holds; the two populations of the median (the three runs' 567 and 872 judgments, the current files' 240 and 360
  calls); the think flags as the result files record them; the sentence counted by judgment, so that no page says
  "every output"; the conclusion and its phrases following the rows they are given; the lines priced like any line;
  and the layout chapter 15's own.
- `test_review.py`, 19 tests, the generator over a fixture month written for the test: every section marked with one of
  the five words, or "not evaluated" or "listed" for the controls, and its source, and the page's shape; the legend's and
  the opening's counts and dates read from the files; the per-run figures priced from measured tokens and the volumes
  marked estimates; the month as the volume times the mean cost per run, the mean printed, and "one kept run" where a
  profile holds one; the judge's paragraph generated from the rows it is given, in total and never "every output"; the
  shared lines by O-D6 as amended; the budget left as 1 minus the share spent, a spent budget saying when and in which
  year; the controls not evaluated, with the reason, and a breach a file lists reported as listed; the incidents reading
  the playbook with the simulated month's years, and an event the playbook doesn't name stopping the review; the month's
  records filtered by month and grouped by change, with the projection alerts' blank soft budget explained; the 180-day
  window with every model in it sorted by days left, and "0 pages"; W5's shares through W5's own `summary(month)` and
  the cost to find as shares, with no amount; another month with no W5 night, written whole; the two files written
  together or not at all, with no path of this machine; and the formats and the words.
- `test_review_results.py`, 16 tests on the committed results: the two files are what the generator writes from another
  process; the review is for the month and the date from the committed files, every source of it in the repository; the
  cost per run and the month are the ledger's, row by row, and the judge's rows and conclusion the ledger's; the error
  budget and the incidents are step 6's, with the controls not evaluated; the month's records are the drills' and the
  remap's; the window is the register's on the review's date, as `retirement.py` computes it; W5's savings are its
  ledger's and the cost to find is priced, as shares; every section says what its figures are; the judge paragraph cites
  ch15:156 and claims it in tokens; W5's section prints no amount; December and October 2026 write both files and say W5
  ran no night; a missing input writes nothing; the README's step 9 tables are the review's; no path of this machine; and
  no module name shared with another folder.

Step 7's session drivers run by hand against the account and have no test of their own: `cloudwatch_spans.poll`,
`langfuse_check.poll`, `tool_role.cloudtrail`, `leftovers.sweep`, `cost_explorer.main`'s fallback to the service
filter, `langfuse_vm.wait` and `hold_tunnel`, and `bedrock_calls.calls`; the tests cover the functions they call and
read what they recorded.

`ruff check` passes with its default rules, as for the other labs.

The runs and their environments, by date. On 3 November, on Windows 11 with Python 3.12.9, in chapter 5's
environment: PyYAML 6.0.3, numpy 2.5.4, litellm 1.106.6, openai 2.54.0, opentelemetry-sdk 1.45.1, botocore 1.43.121,
mcp 2.3.0, a2a-sdk 1.3.0, pytest 9.2.0, ruff 0.14.2, and the contrib Collector 0.164.0 from its Windows tarball. Step
3b's runs used Ollama 0.22.1 for gpt-oss-20b and the portable Ollama 0.40.13 for Gemma 4 12B, on an RTX 5080.
Step 4's smoke test and drills ran in chapter 5's environment plus prisma 0.15.0 and nodeenv 1.12.0, with Node
22.19.0 and PostgreSQL 16.15-5 from EDB's zip. Step 5's drills ran in step 4's environment, with psycopg 3.3.6,
httpx 0.28.1, uvicorn 0.54.0 and starlette 1.10.0, on the evening of 3 November in Toronto: the full run in 53
minutes, before the limiter-cache drill joined it, and that drill alone in 12.

On 4 November the suite ran again in step 5's environment, which has redis-py 8.1.0 from chapter 5's
requirements: 353 passed with Garnet 2.2.5 in `capacity/garnet/` and PostgreSQL in `budget/pg/`, and the
Collector's 24 skipped, since this checkout had no Collector binary. Step 5b's drills ran in the same
environment, with Garnet on the .NET 10.0.14 runtime, in the early hours of 4 November in Toronto: the full run
in 65 minutes.

On 9 November step 6 ran in chapter 5's environment (Python 3.12.9, PyYAML 6.0.3, numpy 2.5.4, litellm 1.106.6,
httpx 0.28.1, pytest 9.2.0, ruff 0.14.2), with no model and no network: `run_slo.py` in about four seconds, and the
whole suite in a checkout with neither the Collector, PostgreSQL nor Garnet, so 423 passed and those 27 skipped.

On 9 November step 7 ran in chapter 5's environment (boto3 1.43.121, httpx 0.28.1, PyYAML 6.0.3), with the AWS CLI
2.28.21, Terraform 1.13.1 and hashicorp/aws 6.71.0, OpenSSH 10.2 and the pinned Collector in `collector/bin/`, against
the lab account between 09:37 and 10:11 UTC; the suite then ran in the same checkout, with the Collector's 24 tests
running and PostgreSQL's one and Garnet's two skipped, so 494 passed and 3 skipped.

On 9 November step 8 ran in chapter 5's environment (Python 3.12.9, litellm 1.106.6, httpx 0.28.1, PyYAML 6.0.3,
python-hcl2 8.1.4) against the portable Ollama 0.40.13 on 11435, alone on the RTX 5080, between 11:41 and 11:54 UTC:
chapter 15's live job on W2 in 136 seconds, the canary's four passes in 554, and the remap's probe in about 15. The
suite then ran in a fresh checkout of the branch with neither the Collector, PostgreSQL, Garnet, nor an initialized
Terraform folder, so 518 passed and 28 skipped. That checkout had turned step 7's vendored Compose file into CRLF,
which failed its SHA-256 pin until `.gitattributes` kept the file LF.

On 9 November step 9 ran in chapter 5's environment (Python 3.12.9, PyYAML 6.0.3, pytest 9.2.0, ruff 0.14.2), with no
model and no network: `monthly_review.py` in about four seconds, `ledger/report.py` with the judge's lines in about 13,
and the suite, after the fixes the review of the pull request asked for, in a worktree of the branch with neither the
Collector, PostgreSQL, Garnet, nor an initialized Terraform folder: 593 tests, 565 passed and 28 skipped in two
minutes.
