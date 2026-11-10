# Step 5: capacity and continuity, 2026-11-04

## Contention

A provider quota of 100,000 tokens a minute; W3 every 6 s and W2 every 3 s for 150 s, and W2's burst from 15 to 75 s; each limit three times. W3's requests made during the burst:

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

W2 during the burst, and the provider over the whole run:

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

## The limiter's cache

Each per-key limit once more, with a callback that reads the in-memory cache LiteLLM's rate limiter counts in without Redis, on step 4's gateway and on the same gateway without its budget alerts; times in seconds from the start of the round.

|Gateway|Limit|Most entries|Full at (s)|What it held then|W2's window evicted at (s)|The key's refusals of W2, the last at (s)|W2's burst tokens served from 60 to 120 s|W3 in the burst, served and on the first attempt|Provider refusals, W3|
|---|---|---|---|---|---|---|---|---|---|
|step 4's|tokens per minute per key|200 of 200|30.5|request_status 192, {api_key}:requests 2, {api_key}:tokens 2|30.8|105, 16.8|70,000|10 of 10, 10|12|
|step 4's|tokens per minute per key, with headroom|200 of 200|31.1|request_status 192, {api_key}:requests 2, {api_key}:tokens 2|31.6|111, 15.8|56,000|10 of 10, 10|0|
|step 4's without alerts|tokens per minute per key|8 of 200||{api_key}:requests 2, {api_key}:tokens 2, {api_key}:window 2||109, 117|56,000|10 of 10, 10|0|
|step 4's without alerts|tokens per minute per key, with headroom|8 of 200||{api_key}:requests 2, {api_key}:tokens 2, {api_key}:window 2||123, 117|21,000|10 of 10, 10|0|

## Retries

A minute of W2's requests, one every 0.75 s with 1,500 tokens reserved each, against a fresh quota of 60,000 a minute: the quota admits the first forty, and the rest of the minute is throttled.

|Through|Policy|Requests|Served|Calls|Calls a success|Calls in the minute|Calls over requests, in the minute|Refused by|
|---|---|---|---|---|---|---|---|---|
|the provider directly|none|80|46|80|1.74|80|1|the provider's quota 34|
|the provider directly|honour|80|56|238|4.25|80|1|the provider's quota 182|
|the provider directly|naive|80|46|726|15.8|726|9.07|the provider's quota 680|
|step 4's gateway|honour|80|75|222|2.96|80|1|chapter 5's requests per minute 72, the provider's quota 75|
|step 4's gateway|naive|80|46|726|15.8|726|9.07|chapter 5's requests per minute 606, the provider's quota 74|

LiteLLM's router on its own, `num_retries: 2`, the first deployment throttled:

|Case|Attempts|Gaps between attempts (s)|Served by|Status|
|---|---|---|---|---|
|one deployment in the group, Retry-After 5 s|t1 429, t1 429, t1 200|5.11, 5.49|t1-single|200|
|one deployment in the group, Retry-After 90 s|t1 429, t1 429, t1 200|0.815, 1.48|t1-single|200|
|two deployments in the group, the first throttled, Retry-After 5 s|t1 429, t2 200|0.013|t2-pair|200|

## The gateway's own latency

Each call's time at the client less the provider's own time for it, matched by its id, both on the performance counter; the provider answers 152 output tokens at 1 ms each after 50 ms, unless the setup says otherwise. The first row has no gateway, so its figure is the client's and the provider's own overhead, which every other row includes.

|Setup|Calls|At once|Client, median (ms)|Provider, median (ms)|Client less provider, median (ms)|Client less provider, 95th percentile (ms)|LiteLLM's own figure, median (ms)|
|---|---|---|---|---|---|---|---|
|the provider alone, no gateway|60|1|206|205|0.973|1.2||
|chapter 5's gateway, no database|60|1|207|197|9.82|11.6|2.56|
|chapter 5's gateway, the provider answering in 50 ms|60|1|62.1|52.5|9.55|11.1|3.35|
|step 4's gateway, W2's virtual key|60|1|207|193|13.3|18.5|6.81|
|step 4's gateway, W2's key with a tpm_limit|60|1|206|195|11.5|13.6|0|
|step 4's gateway, W2's key with a tpm_limit, 8 at once|96|8|236|196|38.9|49|25.9|

## The outage drill

`allowed_fails: 2` and `cooldown_time: 30`; times in seconds from the moment the primary began to fail.

|Mode|First cycle|Cooldown first answered (s)|Second cycle|Healed at (s)|Primary serving again after the heal (s)|
|---|---|---|---|---|---|
|5xx|3 failures, 0.223 to 0.542|1.48|3 failures, 30.8 to 31.8|60|2.15|
|timeout|4 failures, 5.23 to 6.76|6.78|4 failures, 41.1 to 46.9|60|16.6|
|connection|4 failures, 2.29 to 3.88|3.89|4 failures, 35.3 to 38.1|60|7.76|

What the workflows' calls got, those sent after the failure took effect and answered before the primary healed:

|Mode|W2's calls|W2's answers|Served by|W2's latency, median / longest (s)|W3's calls|W3's answers|W3's refusals|
|---|---|---|---|---|---|---|---|
|5xx|59|200 59|fallback 59|0.0822 / 0.104|30|429 29, 503 1|status 503 1, the router's cooldown 29|
|timeout|47|200 47|fallback 47|0.0816 / 5.1|25|408 3, 429 22|status 408 3, the router's cooldown 22|
|connection|56|200 56|fallback 56|0.0856 / 2.13|29|429 26, 500 3|status 500 3, the router's cooldown 26|

Runs in flight when the primary began to fail, and a W3 run started during the cooldown:

|Mode|W2's run|W3's run|W3's run during the cooldown|
|---|---|---|---|
|5xx|answered; calls served by primary in ca-central-1, then fallback in us-east-2|unavailable (model unavailable) after 2 model calls|raised HTTPStatusError 429 after 1 model call|
|timeout|answered; calls served by primary in ca-central-1, then fallback in us-east-2|raised HTTPStatusError 408 after 2 model calls|raised HTTPStatusError 429 after 1 model call|
|connection|answered; calls served by primary in ca-central-1, then fallback in us-east-2|unavailable (model unavailable) after 2 model calls|raised HTTPStatusError 429 after 1 model call|

Where each workflow's calls were served, from chapter 5's cost lines:

|Mode|W2's calls by Region|W3's calls by Region|W3's failed lines with fallback disabled|W2's cooldown failures logged as the fallback|
|---|---|---|---|---|
|5xx|ca-central-1 50, us-east-2 62|ca-central-1 26|33 of 33|58|
|timeout|ca-central-1 36, us-east-2 64|ca-central-1 19|35 of 35|60|
|connection|ca-central-1 45, us-east-2 64|ca-central-1 24|35 of 35|60|

## The database stopped

One W2 call a second, each sent whatever happened to the last; times in seconds from the moment PostgreSQL stopped, and from the moment it started again for the calls after it.

|Stopped for (s)|Calls sent while down|Answered from the key cache|The cache answered until (s)|Refused|A refusal held its caller, median / longest (s)|Answered after waiting for it|First answered call after the restart, sent at (s)|After the restart|Spend counted over the answered calls' cost|
|---|---|---|---|---|---|---|---|---|---|
|90.1|91|51|50.1|503 31|14.6 / 18.8|9|0.862|200 59|0.543|

What the refusals said: "Service Unavailable, the authentication database is temporarily unreachable. Please retry shortly." (31).

## The repeated write

|Case|Presented|Write ran|Generation|Stopped by|Reason|
|---|---|---|---|---|---|
|run A writes under its approval, and its pod is lost before it records the result|run A's approval|yes|1 to 2||the process died after the write|
|run A resumed by a new harness process, its store intact|run A's approval, reserved in run A's store|no|2 to 2|W3's store|the write is marked started; the run ended done after verifying|
|run B presents run A's approval|run A's approval, under run B's trace id|no|2 to 2|the approval service|the approval is for another run|
|run A's approval presented again, by a harness that lost run A's store|run A's approval, under run A's trace id|no|2 to 2|the approval service|already applied|
|run B presents its own approval before anyone has decided|run B's approval, pending|no|2 to 2|the approval service|the approval is pending|
|a person approves run B's own request|run B's approval, approved|yes|2 to 3||a second restart, decided by a person; the run ended done|

Restarts in all: 2; run A's approval approved, run B's approved.

## The provisioned calculator

|Workflow|Busy hour (runs)|Runs a month|Input tokens a minute|Output tokens a minute|Duty cycle|
|---|---|---|---|---|---|
|w2-ops-assistant|200|43,030|6,692|1,054|0.295|
|w3-incident|10|300|1,480|91.3|0.0411|

Ratios only, as the chapter prints them; the prices are in `calculator.json`:

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

What each product lacked for u*:

|Product|Lacks|
|---|---|
|bedrock-reserved-sonnet-4.5-cac1|the on-demand rate (section 8.8 quotes no on-demand rate for Claude Sonnet 4.5 through the Canadian profile, and the offer file it cites for the Reserved tier holds only the Reserved rows)|
|bedrock-pt-nova-lite-use1|the tokens a minute one unit carries, which the fact sheet doesn't give|
|azure-ptu-gpt-5.5-regional-canadaeast|the on-demand rate (section 8.8 quotes no on-demand rate for gpt-5.5, and the table's Azure rate is gpt-4o's, whose tokens per PTU the fact sheet doesn't give)|
|google-gsu-gemini-3.6-flash|the on-demand rate (section 8.8 quotes no Gemini token rate, and the table's Gemini entry is null for the same reason)|

The busy hour's Restricted calls on the self-hosted path, against chapter 9's measured speeds:

|Workflow|Input tokens|Output tokens|Replica-seconds|Share of one replica-hour|Share of the two-replica floor|
|---|---|---|---|---|---|
|w2-ops-assistant|0|0|0|0%|0%|
|w3-incident|8,226|1,243|8.34|0.232%|0.116%|

## Continuity

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

LiteLLM 1.106.6, Python 3.12.9, PostgreSQL 16.15-5, prisma 0.15.0.
