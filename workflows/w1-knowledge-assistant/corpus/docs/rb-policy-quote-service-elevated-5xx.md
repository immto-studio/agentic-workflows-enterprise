---
title: policy-quote-service elevated 5xx
doc_type: runbook
owner_team: policy-engineering
classification: Internal
system: Amazon EKS
last_reviewed: 2026-06-12
access_groups:
- lm-eng-all
---

# policy-quote-service elevated 5xx

**Service:** `policy-quote-service` · **Platform:** Amazon EKS · **Owner:** policy-engineering · **Alert:** `PolicyQuote5xxRate`

## When to use this runbook

The alert fires when the 5xx ratio on `policy-quote-service` is above 1% for 5 minutes. Impact is usually internal at first and can become customer-facing after about 30 minutes.

## Before you start

- Acknowledge the page in ServiceNow On-Call and join the incident bridge from the incident record.
- `aws eks update-kubeconfig --name lm-prod-use1-02 --region us-east-1` (production clusters are read-only for engineers; mutating commands need the `lm-prod-operator` role)

## Diagnose

1. Break errors down by route: `index=eks_prod app=policy-quote-service status>=500 earliest=-30m | stats count by route, upstream`
2. If the upstream is `underwriting-rules-engine`, follow that service's runbook first.
3. Check recent deploys: `gh run list -R larkspur-policy/policy-quote-service --workflow deploy-prod.yml --limit 5`

## Mitigate

1. Roll back a bad deploy: `kubectl -n policy-prod rollout undo deploy/policy-quote-service`
2. If the rating tables cache is cold after a restart, warm it with `kubectl -n policy-prod create job --from=cronjob/quote-cache-warm warm-$(date +%s)`

## Verify

- `PolicyQuote5xxRate` resolves in Grafana and stays clear for 15 minutes.
- Post a short summary in the incident: what you saw, what you changed, the time it recovered.

## Escalate

If the alert is not mitigated within 45 minutes, declare a Sev2 incident if none is open and page the owning team's secondary through assignment group `LM-Policy-Eng`.

## History

- 2025-03-16: first version.
- 2026-06-12: reviewed after a game day; commands re-tested.
