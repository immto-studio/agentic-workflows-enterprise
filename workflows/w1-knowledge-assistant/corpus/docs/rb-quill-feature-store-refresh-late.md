---
title: Quill feature store refresh late
doc_type: runbook
owner_team: quill-data-platform
classification: Internal
system: Google BigQuery
last_reviewed: 2025-12-22
access_groups:
- lm-eng-all
---

# Quill feature store refresh late

**Service:** `quill-feature-store-refresh` · **Platform:** Google BigQuery · **Owner:** quill-data-platform · **Alert:** `FeatureStoreRefreshLate`

## When to use this runbook

The alert fires when the `features.driver_daily` table is older than 26 hours. Check the service's SLO panel first to see how fast the error budget is burning.

## Before you start

- Acknowledge the page in ServiceNow On-Call and join the incident bridge from the incident record.
- `gcloud config set project quill-analytics-prod`

## Diagnose

1. `bq show --format=prettyjson quill-analytics-prod:features.driver_daily | jq '.lastModifiedTime'`
2. Check the Dataform workflow invocation in project `quill-analytics-prod`, repository `quill-features`.

## Mitigate

1. Re-run the Dataform workflow for the `driver_daily` tag only.
2. If upstream `trips-raw` ingestion is behind, fix ingestion first; refreshing on partial data publishes wrong features.

## Verify

- `FeatureStoreRefreshLate` resolves in Grafana and stays clear for 10 minutes.
- Post a short summary in the incident: what you saw, what you changed, the time it recovered.

## Escalate

If the alert is not mitigated within 20 minutes, declare a Sev2 incident if none is open and page the owning team's secondary through assignment group `LM-Quill-Data`.

## History

- 2025-03-30: first version.
- 2025-12-22: reviewed after a game day; commands re-tested.
