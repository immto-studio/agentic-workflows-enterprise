# The misbehaving-agent runbook

For the on-call lead on Tomasz's rota. `playbook.yaml` beside this file is the same playbook as a table, the one
chapter 16 prints; this file adds the commands and the order to work in. O-D12's fast burns page (`fast-burn-1h`,
`fast-burn-6h`, and the platform's `provider-429-across-workflows`); everything else arrives as a ticket. A workflow
that hit its own budget or request rate is never a page (ch05:498): its owner sees it on the workflow's dashboard.

Every lever below is an emergency change: "authorized by the on-call lead, documented within twenty-four hours, and
reviewed at the next board meeting" (ch02:163). Give each pull a change number, and write the reason in the words
you'd use at the board.

## The levers

Run from `labs/ch16`, with the gateway's admin key in `LITELLM_MASTER_KEY` for the gateway levers.

- The rate in the manifest. Lower the workflow's rate live through its key, with LiteLLM's `/key/update`
  (`budget/keys.Admin.update(token, rpm_limit=..., tpm_limit=...)`); there's no `oncall.py` command for it yet, so
  write the change line by hand in the shape `oncall.change_record` writes. Then change `requests_per_minute` in the
  manifest through its change record. Chapter 5's callback reads the manifests when the gateway starts, so the
  manifest's number takes over at the next restart.
- The alias remapped back. Point the alias at the deployment it served before, in the gateway's model list, and
  restart the gateway. Every workflow on the alias goes back at once. The remap is a model change: it reruns the
  golden sets (chapter 15's live job), and its record says so. Nothing in the lab pulls this lever yet.
- A rung down. `python budget/oncall.py rung <workflow> <rung> --by <lead> --change <number> --reason <why>`.
  The harness reads the override before its next run and drops every write tool. It changes nothing for W1, at rung
  0, or for W2, which has no write tool. `restore-rung` takes it back once the workflow has its evidence again
  (ch01:221).
- The kill switch. `python budget/oncall.py kill <workflow> --by <lead> --change <number> --reason <why>`. The
  workflow's key is blocked and its next call refused (step 4: 0.142 seconds to the first refusal at the median). On
  AWS, follow it with the identity half, `python budget/identity.py pull --manifest <manifest>`, which puts the
  deny-all on the harness role and every tool role. `reopen` and `identity.py release` undo them.

Each lever appends its line to `changes.jsonl` in the state folder. The line opens the record; your write-up within
the day completes it.

## By symptom

### A loop that exhausts its step budget

You'll see a success burn: W3's runs ending in "Stopped: step budget exhausted.", or W2's harness refusing after
its fourth read and a fifth model call (count the calls for the trace id in the gateway's cost lines; W2's log line
looks like a refusal). If a remap or a new model came shortly before, remap the alias back. If nothing changed, pull
the kill switch for the workflow while its owner looks, and reopen it when they have a fix.

### A cost spike

The 80 percent alarm reaches the owner and FinOps, and the budget stops the month at 100 percent on its own, so this
one is rarely urgent. Read the cost lines by trace id to find the runs that grew. Lower the rate first; pull the kill
switch if the spend is still climbing toward the stop with nothing to show for it. The month's regressed W5 nights
spent about one and a half times their output tokens and moved no SLI: only the cost lines show that kind.

### A run of refusals or tool errors

Tool errors that end runs show as a success burn. Refusals don't: a refusal is a good event, and nothing alerts on
their share yet, so a run of them reaches you as a ticket from the owner or a person. Look at the harness's `answer`
lines and the tool servers' refused spans. If they began with a model change, remap the alias back; if a tool keeps
failing, pull the kill switch until the tool's owner has it working.

### A planted text restated

For W5 the prose seam has already refused the reply and written the stub; the night's record names the words. For W1
to W4 nothing fires at run time: the report comes from a person or from chapter 15's red-team runs. Lower the
workflow a rung, which takes away every write tool it has, then decide on the kill switch with the owner.

### A denied egress

Nothing in the lab emits this yet; the signal would come from the egress allowlist's deny log or the rendering
allowlist. Treat it as an exfiltration attempt: pull the kill switch, then the identity half with
`budget/identity.py pull`, and open the security incident.

### Confident wrong answers reported by people

For W3, W4 and W5 the outcome SLI counts a person declining; its ticket and, once its budget is spent, the policy's
rung down reach you on their own. For W1 and W2 no channel collects the reports, so they come to you directly. Remap
the alias back if a model change came first; otherwise lower the workflow a rung (W3 to W5) or pull the kill switch
(W1, W2) until the owner has looked.

### A provider outage

The gateway's cooldown and fallback act on their own: W1 to W3 fall back to the self-hosted alias in Canada and
W4's and W5's seams write their stub sentences. Watch the fallback panel and the self-hosted replicas' load; if the
fallback can't carry the traffic, lower the rate of the heaviest workflow. Pull the kill switch only for a workflow
that can't run usefully without the model; W3 ends such a run as "model unavailable" and hands the incident to a
person by itself.

### A model that changed under its alias

The platform's models panel shows a step in `served_model`; the SLIs move after it (in the month, W2's step-budget
stops paged 30 minutes after the remap). Remap the alias back, then lower any workflow that acted on the new model's
output a rung until chapter 15's live job has run on the model again. A provider that updates a model in place under
an identifier with no version leaves `served_model` as it was; then the SLIs and people are the only signal.
