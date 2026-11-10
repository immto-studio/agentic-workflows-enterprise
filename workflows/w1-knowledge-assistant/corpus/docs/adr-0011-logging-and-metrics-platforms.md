---
title: 'ADR-0011: Splunk for logs, Grafana stack for metrics and traces'
doc_type: adr
owner_team: observability
classification: Internal
system: Splunk
last_reviewed: 2025-10-14
access_groups:
- lm-eng-all
---

# ADR-0011: Splunk for logs, Grafana stack for metrics and traces

**Status:** Accepted

## Decision

- Application and audit logs go to Splunk through the OpenTelemetry Collector HEC exporter.
  Logs are kept **hot in Splunk for 90 days**, then frozen to S3 (`lm-splunk-frozen-prod`) and
  kept for **7 years** for regulatory retention.
- Metrics go to Grafana Mimir with 13 months of retention; traces go to Grafana Tempo with 14 days.
- Dashboards and alert rules live in Grafana and are managed as code in `observability-config`.

## Consequences

Splunk licence is sized for 1.4 TB per day of ingest; debug logging in production must be enabled
per pod and expires after 4 hours.
