---
title: Splunk HEC ingestion backlog
doc_type: runbook
owner_team: observability
classification: Internal
system: Amazon EKS
last_reviewed: 2026-02-22
access_groups:
- lm-eng-all
---

# Splunk HEC ingestion backlog

**Service:** `splunk-hec` · **Platform:** Amazon EKS · **Owner:** observability · **Alert:** `SplunkHecBacklog`

## When to use this runbook

The alert fires when Splunk HEC indexer queue fill ratio is above 90% for 10 minutes. Reports may reach #ops-announce before the alert does; check there for context.

## Before you start

- Acknowledge the page in ServiceNow On-Call and join the incident bridge from the incident record.
- `aws eks update-kubeconfig --name lm-prod-use1-01 --region us-east-1` (production clusters are read-only for engineers; mutating commands need the `lm-prod-operator` role)

## Diagnose

1. Splunk Monitoring Console, Indexing, Indexing performance: find the blocked queue.
2. `index=_internal sourcetype=splunkd component=HttpInputDataHandler earliest=-30m | stats count by reply`

## Mitigate

1. Ask the Splunk admins to add indexer capacity in the cluster manager.
2. Temporarily drop debug-level logs at the collector with the `drop-debug` processor.

## Verify

- `SplunkHecBacklog` resolves in Grafana and stays clear for 10 minutes.
- Post a short summary in the incident: what you saw, what you changed, the time it recovered.

## Escalate

If the alert is not mitigated within 45 minutes, declare a Sev2 incident if none is open and page the owning team's secondary through assignment group `LM-Observability`.

## History

- 2025-04-26: first version.
- 2026-02-22: reviewed after a game day; commands re-tested.
