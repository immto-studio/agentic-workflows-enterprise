# Step 4: budgets and switches, 2026-11-03

## The smoke test

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

## The keys

|Workflow|max_budget|soft_budget|budget_duration|Reset at (UTC)|Reset in Toronto|Midnight on the 1st in Toronto|
|---|---|---|---|---|---|---|
|w2-ops-assistant|200.0|160.0|1mo|2026-12-01T05:00:00+00:00|2026-12-01T00:00:00-05:00|yes|
|w3-incident|500.0|400.0|1mo|2026-12-01T05:00:00+00:00|2026-12-01T00:00:00-05:00|yes|

## The kill switch, gateway half

|Cycle|/key/block (s)|First refusal in the loop (s)|In-flight calls that succeeded|Call right after the block|/key/unblock (s)|First success after the unblock (s)|Call right after the unblock|
|---|---|---|---|---|---|---|---|
|1|0.034|0.142|0|401|0.027|0.101|200|
|2|0.024|0.064|0|401|0.023|0.042|200|
|3|0.027|0.249|1|401|0.024|0.22|200|
|4|0.024|0.189|0|401|0.023|0.163|200|
|5|0.026|0.142|0|401|0.023|0.105|200|

Loop: one call every 0.25 s, 86 calls, outcomes {"answered": 46, "kill_switch": 40}. First refusal: median 0.142 s, max 0.249 s. First success after the unblock: median 0.105 s, max 0.22 s.

## The reservation

Before each call LiteLLM reserves the input tokens and 16384 output tokens, since these requests set no max_tokens: about 0.24636 US dollars at the stand-in prices (3e-06 and 1.5e-05 a token). Each month below starts one reservation and about three runs short of its threshold.

## The 80 percent alert

|Run|Answered|Cost (USD)|Month after (USD)|
|---|---|---|---|
|1|yes|0.000876|159.751516|
|2|yes|0.000876|159.752392|
|3|yes|0.000876|159.753268|
|4|yes|0.000876|159.754144|
|5|yes|0.000876|159.75502|

Seeded at 159.75064 of 200.0 (0.798753) after the spend settled at 0.018972; soft budget 160.0. The alert arrived during run 5, with the month's priced calls at 159.754144 before that run (the priced calls alone never reached it): event `soft_budget_crossed`, spend 160.00035100000002, 0.246207 beyond the month's priced calls, forwarded to sam.okafor@larkspur.example, finops@larkspur.example.

## The stop

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

Seeded at 199.75064 of 200.0 after the spend settled at 159.75502. First stopped run: 5, status 422, counted by the harness as `monthly_budget`. Tally {"answered": 4, "monthly_budget": 4}; the stopped runs made 4 model calls between them. Spend in the database afterwards: 199.755632, 0.244368 short of the budget. The gateway said: Budget has been exceeded! Key=w2-ops-assistant (sk-...pb9A) Current cost: 200.0, Max budget: 200.0

## Every alert the receiver got

|Received (UTC)|Event|What it is|Spend|max_budget|soft_budget|Projected spend|Forwarded to|
|---|---|---|---|---|---|---|---|
|23:45:39.755|threshold_crossed|the month's pace projected past the soft budget|159.751012|160.0||1722.8720211343243|sam.okafor@larkspur.example, finops@larkspur.example|
|23:45:41.851|soft_budget_crossed|the soft budget reached|160.00035100000002|200.0|160.0||sam.okafor@larkspur.example, finops@larkspur.example|
|23:45:58.200|budget_crossed|the month's pace projected past the soft budget|199.751012|160.0||2154.0959676841035|sam.okafor@larkspur.example, finops@larkspur.example|
|23:47:05.864|budget_crossed|the budget reached|200.0|200.0|160.0||sam.okafor@larkspur.example, finops@larkspur.example|

## A restart

With the month set to 200.0, the database held 200.0 and the run before the restart got status 422 (`monthly_budget`). The proxy came back in 20.38 s, reported the key's spend as 200.0, and the next run got status 422 (`monthly_budget`) after 0 model calls.

## The monthly reset

With `budget_reset_at` moved into the past, the reset job set the spend to 0.0 in 13.47 s and the next reset to 2026-12-01T05:00:00+00:00 (midnight on the 1st in Toronto: yes). Runs until one was answered: 1, the first answered 0.81 s after the reset.

## The key bound to its workflow

|Case|Status|Kind|Message|
|---|---|---|---|
|W2's key, its own tags|200|answered||
|W2's key, W3's workflow tag|400|refused|request refused: the key is 'w2-ops-assistant''s, and the request says it is 'w3-incident'|
|W2's key, data class above its maximum|400|refused|request refused: data class 'confidential' is above the key's maximum ('internal')|
|the master key, which names no workflow|400|refused|request refused: the key names no workflow; model calls go through a workflow's own key|
|W3's key, its own tags|200|answered||

## The rung down

|Case|Started|Rung|Write tools dropped|Model calls|Tool calls|Answer or why|
|---|---|---|---|---|---|---|
|no override; the model asks to restart|yes|3||2|{"restart_deployment": 1}|Restarted claims-api.|
|lowered to rung 1; the model asks to restart|yes|1|restart_deployment|1|{}|Refused: restart_deployment is not an allowed call.|
|lowered to rung 1; the model asks to read|yes|1|restart_deployment|2|{"get_pod_status": 1}|claims-api has 2 of 3 pods ready.|
|an override of rung 4, above the manifest's 3|yes|3||2|{"restart_deployment": 1}|Restarted claims-api.|
|a malformed override (rung: one)|no|||0|{}|w3-incident.yaml: rung 'one' is not an integer from 0 to 5|
|an override that isn't YAML|no|||0|{}|w3-incident.yaml: not YAML (ScannerError)|
|override removed; the model asks to restart|yes|3||2|{"restart_deployment": 1}|Restarted claims-api.|

## The change log

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

Gateway log (chapter 5's callback and the key binding): 131 lines, {"call": 77, "failed": 51, "refused": 3}; served calls with a cost: 77; failed lines by reason {"budget exceeded": 6, "key blocked": 45}, 51 of them with no trace id.
