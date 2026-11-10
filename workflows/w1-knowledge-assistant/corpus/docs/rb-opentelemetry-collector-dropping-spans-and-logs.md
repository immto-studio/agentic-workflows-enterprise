---
title: OpenTelemetry Collector dropping spans and logs
doc_type: runbook
owner_team: observability
classification: Internal
system: Amazon EKS
last_reviewed: 2026-02-26
access_groups:
- lm-eng-all
---

# OpenTelemetry Collector dropping spans and logs

**Service:** `otel-collector` · **Platform:** Amazon EKS · **Owner:** observability · **Alert:** `OtelCollectorDropping`

## When to use this runbook

The alert fires when `otelcol_exporter_send_failed_log_records` is above 1000 per minute. In most cases no data is lost, but downstream work falls behind the longer it lasts.

## Before you start

- Acknowledge the page in ServiceNow On-Call and join the incident bridge from the incident record.
- `aws eks update-kubeconfig --name lm-prod-use1-02 --region us-east-1` (production clusters are read-only for engineers; mutating commands need the `lm-prod-operator` role)

## Diagnose

1. `kubectl -n observability logs ds/otel-collector-agent --since=15m | grep -iE 'dropping|429|exporter'`
2. A `429` from Splunk HEC means the indexers are throttling; check the Splunk HEC health dashboard.
3. Check the collector memory limiter: `otelcol_processor_refused_log_records`.

## Mitigate

1. Raise the sending queue size in `observability-config/otel/agent.yaml` and roll the DaemonSet.
2. If a single namespace is flooding, apply the debug-log filter for that namespace.

## Verify

- `OtelCollectorDropping` resolves in Grafana and stays clear for 30 minutes.
- Post a short summary in the incident: what you saw, what you changed, the time it recovered.

## Escalate

If the alert is not mitigated within 45 minutes, declare a Sev2 incident if none is open and page the owning team's secondary through assignment group `LM-Observability`.

## History

- 2025-08-03: first version.
- 2026-02-26: reviewed after a game day; commands re-tested.
