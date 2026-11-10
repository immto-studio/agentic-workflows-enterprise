---
title: customer-identity-service login latency
doc_type: runbook
owner_team: identity-access-management
classification: Internal
system: Amazon EKS
last_reviewed: 2025-06-06
access_groups:
- lm-eng-all
---

# customer-identity-service login latency

**Service:** `customer-identity-service` · **Platform:** Amazon EKS · **Owner:** identity-access-management · **Alert:** `CustomerLoginLatency`

## When to use this runbook

The alert fires when p95 latency for `POST /oauth2/token` is above 400 ms. Check the service's SLO panel first to see how fast the error budget is burning.

## Before you start

- Acknowledge the page in ServiceNow On-Call and join the incident bridge from the incident record.
- `aws eks update-kubeconfig --name lm-prod-use1-02 --region us-east-1` (production clusters are read-only for engineers; mutating commands need the `lm-prod-operator` role)

## Diagnose

1. Check the token endpoint on **Identity / Customer login** dashboard; split by grant type.
2. Check ElastiCache `cis-sessions-prod` CPU and evictions: `aws cloudwatch get-metric-statistics --namespace AWS/ElastiCache --metric-name Evictions --dimensions Name=CacheClusterId,Value=cis-sessions-prod-001 --statistics Sum --period 300 --start-time $(date -u -d '-1 hour' +%FT%TZ) --end-time $(date -u +%FT%TZ)`
3. A spike in `password` grants from few IPs is credential stuffing; involve Security Operations.

## Mitigate

1. Scale out: `kubectl -n identity-prod scale deploy/customer-identity-service --replicas=10`
2. If evictions are high, fail over the ElastiCache replication group: `aws elasticache test-failover --replication-group-id cis-sessions-prod --node-group-id 0001`

## Verify

- `CustomerLoginLatency` resolves in Grafana and stays clear for 30 minutes.
- Post a short summary in the incident: what you saw, what you changed, the time it recovered.

## Escalate

If the alert is not mitigated within 45 minutes, declare a Sev2 incident if none is open and page the owning team's secondary through assignment group `LM-IAM`.

## History

- 2025-05-30: first version.
- 2025-06-06: reviewed after a game day; commands re-tested.
