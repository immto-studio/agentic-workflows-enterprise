---
title: Grafana unavailable or slow
doc_type: runbook
owner_team: observability
classification: Internal
system: Amazon EKS
last_reviewed: 2026-03-08
access_groups:
- lm-eng-all
---

# Grafana unavailable or slow

**Service:** `grafana` · **Platform:** Amazon EKS · **Owner:** observability · **Alert:** `GrafanaDown`

## When to use this runbook

The alert fires when the Grafana synthetic check on `grafana.larkspur.internal` fails 5 times in 5 minutes. Check the service's SLO panel first to see how fast the error budget is burning.

## Before you start

- Acknowledge the page in ServiceNow On-Call and join the incident bridge from the incident record.
- `aws eks update-kubeconfig --name lm-prod-use1-02 --region us-east-1` (production clusters are read-only for engineers; mutating commands need the `lm-prod-operator` role)

## Diagnose

1. `kubectl -n observability get pods -l app.kubernetes.io/name=grafana`
2. Check the Grafana database `grafana-aurora-prod` connections.
3. Slow dashboards with heavy Mimir queries can exhaust query-frontend capacity.

## Mitigate

1. Restart Grafana: `kubectl -n observability rollout restart deploy/grafana`
2. During an incident, use Splunk dashboards as fallback for service health.

## Verify

- `GrafanaDown` resolves in Grafana and stays clear for 10 minutes.
- Post a short summary in the incident: what you saw, what you changed, the time it recovered.

## Escalate

If the alert is not mitigated within 30 minutes, declare a Sev3 incident if none is open and page the owning team's secondary through assignment group `LM-Observability`.

## History

- 2025-04-01: first version.
- 2026-03-08: reviewed after a game day; commands re-tested.
