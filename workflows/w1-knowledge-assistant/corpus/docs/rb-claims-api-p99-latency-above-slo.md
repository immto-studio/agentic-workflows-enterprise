---
title: claims-api p99 latency above SLO
doc_type: runbook
owner_team: claims-engineering
classification: Internal
system: Amazon EKS
last_reviewed: 2026-02-05
access_groups:
- lm-eng-all
---

# claims-api p99 latency above SLO

**Service:** `claims-api` · **Platform:** Amazon EKS · **Owner:** claims-engineering · **Alert:** `ClaimsApiLatencyHigh`

## When to use this runbook

The alert fires when p99 latency on `claims-api` is above 800 ms for 10 minutes. In most cases no data is lost, but downstream work falls behind the longer it lasts.

## Before you start

- Acknowledge the page in ServiceNow On-Call and join the incident bridge from the incident record.
- `aws eks update-kubeconfig --name lm-prod-use1-01 --region us-east-1` (production clusters are read-only for engineers; mutating commands need the `lm-prod-operator` role)

## Diagnose

1. Compare p99 for `/claims/{id}` and `/claims/search` on the Grafana dashboard **Claims / API**; search is usually the slow path.
2. Check Aurora reader CPU: `aws cloudwatch get-metric-statistics --namespace AWS/RDS --metric-name CPUUtilization --dimensions Name=DBClusterIdentifier,Value=claims-aurora-prod-v2 --statistics Average --period 60 --start-time $(date -u -d '-30 min' +%FT%TZ) --end-time $(date -u +%FT%TZ)`
3. Look for slow queries: `index=aurora_prod cluster=claims-aurora-prod-v2 duration_ms>2000 earliest=-30m | stats count by normalized_query`

## Mitigate

1. If one query dominates, ask Claims Engineering to disable the search facet with flag `claims.search.facets=false`.
2. Scale out: `kubectl -n claims-prod scale deploy/claims-api --replicas=12`

## Verify

- `ClaimsApiLatencyHigh` resolves in Grafana and stays clear for 30 minutes.
- Post a short summary in the incident: what you saw, what you changed, the time it recovered.

## Escalate

If the alert is not mitigated within 20 minutes, declare a Sev2 incident if none is open and page the owning team's secondary through assignment group `LM-Claims-Eng`.

## History

- 2025-12-05: first version.
- 2026-02-05: reviewed after a game day; commands re-tested.
