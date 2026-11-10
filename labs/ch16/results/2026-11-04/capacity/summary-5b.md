# Step 5b: the limiter on a shared store, and the outage drill again, 2026-11-04

## The store's probe

LiteLLM 1.106.6's rate-limiter scripts, each run once against Garnet 2.2.5 with known inputs and set against what Redis answers, then 1,000 check-and-increments at once over 100 connections against a limit of 250, 3 times in each mode. Redis admits exactly 250.

|Lua transaction mode|Script steps answered as Redis answers|Admitted, each trial|Counter after, each trial|Errors|
|---|---|---|---|---|
|on|18 of 18|250, 250, 250|250, 250, 250|0|
|off|18 of 18|251, 250, 251|250, 250, 250|0|

## Contention on the store

Step 5's drill as it ran: a quota of 100,000 tokens a minute, W3 every 6 s and W2 every 3 s for 150 s, W2's burst from 15 to 75 s, each limit three times, the store emptied before each round. W3's requests made during the burst:

|Limit|Round|Requests|Served|On the first attempt|Attempts a request|Median wait (s)|Longest wait (s)|What refused W3's attempts|
|---|---|---|---|---|---|---|---|---|
|requests per minute alone|1|10|10|2|3.9|20.4|52.8|the provider's quota 29|
|tokens per minute per key|1|10|10|10|1|0.161|0.177||
|tokens per minute per key, with headroom|1|10|10|10|1|0.162|0.177||
|deployment limits|1|10|10|1|4.3|22.7|54.2|the deployment's parallel requests 7, the provider's quota 26|
|requests per minute alone|2|10|8|1|4.7|21.8|52|the provider's quota 39|
|tokens per minute per key|2|10|10|10|1|0.161|0.178||
|tokens per minute per key, with headroom|2|10|10|10|1|0.161|0.175||
|deployment limits|2|10|5|1|4.8|3.67|48.3|the deployment's parallel requests 2, the provider's quota 41|
|requests per minute alone|3|10|10|3|3.7|21.9|52|the provider's quota 27|
|tokens per minute per key|3|10|10|10|1|0.175|0.535||
|tokens per minute per key, with headroom|3|10|10|10|1|0.162|0.178||
|deployment limits|3|10|7|1|4.8|16.1|39.9|the deployment's parallel requests 4, the provider's quota 37|

W2 during the burst, and the provider over the whole run:

|Limit|Round|W2's burst requests|Served|W2's questions served|W3 served, whole run|Provider refusals, W2|Provider refusals, W3|What refused W2's burst|
|---|---|---|---|---|---|---|---|---|
|requests per minute alone|1|20|18|10 of 20|25 of 25|92|29|the provider's quota 18|
|tokens per minute per key|1|138|9|5 of 19|25 of 25|0|0|chapter 5's requests per minute 179, the key's tokens per minute 106|
|tokens per minute per key, with headroom|1|151|7|5 of 20|25 of 25|0|0|chapter 5's requests per minute 196, the key's tokens per minute 118|
|deployment limits|1|21|17|11 of 21|24 of 25|113|41|chapter 5's requests per minute 8, the deployment's parallel requests 17, the provider's quota 19|
|requests per minute alone|2|20|19|10 of 20|23 of 25|95|41|the provider's quota 18|
|tokens per minute per key|2|151|17|7 of 20|25 of 25|0|0|chapter 5's requests per minute 204, the key's tokens per minute 107|
|tokens per minute per key, with headroom|2|149|7|5 of 20|25 of 25|0|0|chapter 5's requests per minute 186, the key's tokens per minute 119|
|deployment limits|2|17|16|11 of 20|20 of 25|88|43|chapter 5's requests per minute 11, the deployment's parallel requests 2, the provider's quota 15|
|requests per minute alone|3|20|19|10 of 21|25 of 25|93|28|the provider's quota 18|
|tokens per minute per key|3|154|17|6 of 20|25 of 25|0|0|chapter 5's requests per minute 220, the key's tokens per minute 107|
|tokens per minute per key, with headroom|3|141|3|6 of 19|25 of 25|0|0|chapter 5's requests per minute 198, the key's tokens per minute 111|
|deployment limits|3|16|15|13 of 20|22 of 25|86|56|chapter 5's requests per minute 9, the deployment's parallel requests 4, the provider's quota 14|

Beside step 5's three rounds of each limit, which had no store: W3 in the burst, the provider's refusals of W3 after the burst (from 75 s), the key's refusals of W2 in its second minute (60 to 120 s), and the burst's tokens served from 60 to 120 s, in each round:

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

## The limiter's cache on the store

Each per-key limit once more with the census, which reads the proxy's in-memory cache at every call and the store every half second; step 5's rounds, with no store, beside them. Times in seconds from the start of the round.

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

## The gateway's own latency on the store

Step 5's setup, sixty single calls with W2's key under a tpm_limit that refuses nothing, beside step 5's row:

|Setup|Calls|At once|Client, median (ms)|Provider, median (ms)|Client less provider, median (ms)|Client less provider, 95th percentile (ms)|LiteLLM's own figure, median (ms)|
|---|---|---|---|---|---|---|---|
|step 4's gateway, W2's key with a tpm_limit|60|1|206|195|11.5|13.6|0|
|step 4's gateway with the store, W2's key with a tpm_limit|60|1|207|192|14.5|16.7|9.03|

## The store stopped

One round of the exact division (W2's key 75,000 tokens a minute, W3's 25,000) on step 4's gateway with the store, its budget alerts on and the census reading both caches. The store was stopped 30 s into W2's burst, at 45 s, and started again, empty, at 105 s. What each workflow's attempts got, by when they were sent:

|Limiter|Sent|W2's answers|What refused W2|W2's burst tokens served|W3's incidents served, and on the first attempt|W3's answers|W2's attempt, median / longest (s)|
|---|---|---|---|---|---|---|---|
|LiteLLM's default|before|200 15, 429 250|chapter 5's requests per minute 145, the key's tokens per minute 105|63,000|8 of 8, 8|200 8|0.0198 / 1.18|
|LiteLLM's default|while down|200 24, 429 158|chapter 5's requests per minute 153, the provider's quota 5|70,000|9 of 10, 8|200 8, 429 5|0.0192 / 3.12|
|LiteLLM's default|after|200 15, 429 25|the provider's quota 25|0|7 of 7, 4|200 8, 429 12|0.0729 / 0.438|
|failing closed|before|200 15, 429 246|chapter 5's requests per minute 141, the key's tokens per minute 105|63,000|8 of 8, 8|200 8|0.0208 / 1.14|
|failing closed|while down|429 162, 503 83|chapter 5's requests per minute 162, status 503 83|0|2 of 10, 0|503 57|0.021 / 2.06|
|failing closed|after|200 17, 503 5|status 503 5|0|7 of 7, 6|200 9, 503 1|0.209 / 0.338|

What the gateway did about it, in seconds from the stop and from the start:

|Limiter|First 503 after the stop|503 answers|Last 503 after the start|First failed ping|Unreachable alert received|First good ping after the start|Answering-again alert received|Forwarded to|
|---|---|---|---|---|---|---|---|---|
|LiteLLM's default||0||1.28|4.47|1.02|1.21|platform.oncall@larkspur.example|
|failing closed|2.86|146|2.68|1.3|4.47|0.981|1.18|platform.oncall@larkspur.example|

The proxy's log over the round, and its in-memory cache while the store was down:

|Limiter|Log lines|A batch of store operations failed|The circuit breaker opened|A store call skipped while the breaker was open, with its traceback|The key cache's subscriber lost the store|A Lua script failed, the local mirror used|A call refused, failing closed|Memory readings while down|Most entries in memory|Readings that held W2's window|
|---|---|---|---|---|---|---|---|---|---|---|
|LiteLLM's default|13,937|5|2|650|4|0|0|237|200|0|
|failing closed|20,503|5|1|920|4|0|0|436|200|0|

What the 503s said: "Rate limit enforcement unavailable: request counters could not be verified against Redis, and fail_closed_rate_limit_enf" (146).

## The outage drill again

Step 5's three failure modes on two configs: step 5's own, with W3's model client of step 5b, and `litellm.outage-canada.yaml`, which gives W3 the self-hosted alias as its fallback. Times in seconds from the moment the primary began to fail.

### step 5's config (`litellm.outage.yaml`)

|Mode|W2's calls|W2's answers|Served by|W3's calls|W3's answers|Served by|W3's refusals|
|---|---|---|---|---|---|---|---|
|5xx|60|200 60|fallback 60|30|429 29, 503 1||status 503 1, the router's cooldown 29|
|timeout|47|200 47|fallback 47|25|408 3, 429 22||status 408 3, the router's cooldown 22|
|connection|56|200 56|fallback 56|29|429 26, 500 3||status 500 3, the router's cooldown 26|

|Mode|W2's calls by Region|W3's calls by Region|W3's calls by deployment|W3's requests the primary saw|W3's requests us-east-2 saw|W3's requests the self-hosted saw|W2's requests the self-hosted saw|
|---|---|---|---|---|---|---|---|
|5xx|ca-central-1 51, us-east-2 62|ca-central-1 29|primary 29|32|0|0|0|
|timeout|ca-central-1 36, us-east-2 64|ca-central-1 21|primary 21|26|0|0|0|
|connection|ca-central-1 45, us-east-2 64|ca-central-1 26|primary 26|22|0|0|0|

|Mode|W2's run|W3's run in flight|W3's run started 20 s in|
|---|---|---|---|
|5xx|answered|unavailable after 2 model calls and 0.885 s: the gateway answered 503|answer after 2 model calls and 61.3 s, having waited 30.3 and 30.5 s for 429, 429|
|timeout|answered|unavailable after 2 model calls and 6.03 s: 408 with no wait to wait out|answer after 2 model calls and 61.5 s, having waited 30.4 and 30.4 s for 429, 429|
|connection|answered|unavailable after 2 model calls and 2.74 s: the gateway answered 500|answer after 2 model calls and 61 s, having waited 30 and 30.2 s for 429, 429|

### W3's fallback in Canada (`litellm.outage-canada.yaml`)

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

## W3's fallback on the self-hosted path

Had a provider outage lasted W3's whole busy hour (10 incidents), its Confidential calls, 88,788 input and 5,478 output tokens, would take 46.2 replica-seconds at chapter 9's single-stream speeds, and with the Restricted calls' 8.34 that is 54.5 seconds, 1.51% of one replica's hour.

## Continuity after step 5b

The rows of step 5's continuity table that step 5b's drills change (`capacity/continuity.yaml`, `after_step5b`); step 5's summary keeps them as step 5 found them.

|Component|Failure mode|Recovery objective|Evidence|Gap|
|---|---|---|---|---|
|the gateway|A model behind it fails, with 5xx errors, timeouts or refused connections; or the proxy itself stops, and every call in flight with it.|A failing model off the path within three failures, seconds, or the timeout and a little more when it hangs; back on it within one cooldown of healing, thirty seconds; the proxy back within a minute of a restart; and a workflow whose data may not leave Canada served meanwhile by the self-hosted alias. RPO none: it holds nothing a call needs beyond its database.|Outage drill again, step 5's three modes. With litellm.outage-canada.yaml, W3's calls failed over to the self-hosted alias in ca-central-1 and all 30, 25 and 29 made while the primary failed were answered; the fake in us-east-2 saw none of W3's requests, and W2's calls failed over to us-east-2 as in step 5. On step 5's config, W3's model client of step 5b ended its triage in flight as model unavailable on the primary's 503, the timeout's 408 and the refused connection's 500, and a triage started in the cooldown waited out two 429s of 30 s and was answered by the healed primary 61.3 s after it began.|One Region: the second gateway Region of month five isn't deployed (O-D17). A proxy killed with calls in flight, and a fleet of proxies behind a load balancer, weren't drilled. During an outage the self-hosted replicas carry W3's Confidential calls as well as its Restricted ones; at chapter 9's speeds W3's busy hour would take 1.51% of one replica's hour, and the replicas under that load weren't drilled.|
|Redis|The store unreachable. LiteLLM keeps the keys' windows and counters, the spend counters and the router's state there, and counts in it with Lua scripts that must run whole.|Back within the minute LiteLLM waits before it tries the store again, with the keys' limits failing closed meanwhile (fail_closed_rate_limit_enforcement) and the platform's on-call alerted within seconds. RPO: the current minute's windows, which a restarted store has lost; nothing a budget needs, since the spend is in the database.|Garnet 2.2.5 ran every step of LiteLLM 1.106.6's eight limiter scripts as Redis does; with its Lua transaction mode it admitted 250 of 1,000 check-and-increments against a limit of 250 in each of three trials, and without it 251 in two. With the windows in the store, step 4's alerts still filled the proxy's in-memory cache 31.4 s into a burst, yet W2's key went on refusing until 117 s, no window left the store early, and the provider refused W3 nothing. With the store stopped 30 s into the burst, LiteLLM's default carried on from memory, which held no window of W2's: the key refused nothing until the store came back, and the provider refused W3 5 times while it was down and 12 after. Failing closed, every keyed call got 503 from 2.86 s after the stop until 2.68 s after the restart. In both rounds the alert reached step 4's receiver 4.47 s after the stop, and the second one 1.21 and 1.18 s after the restart. LiteLLM's circuit breaker opened after five failures, and the proxy wrote 13,937 log lines in the default's round, 650 of them tracebacks for spend writes it skipped.|One proxy on one store: a fleet sharing it, the store's own replication and failover, a store that answers slowly rather than not at all, and TLS to it weren't drilled. Garnet ran in memory, so a restarted store came back empty.|

LiteLLM 1.106.6, redis-py 8.1.0, Garnet 2.2.5, Python 3.12.9, prisma 0.15.0.
