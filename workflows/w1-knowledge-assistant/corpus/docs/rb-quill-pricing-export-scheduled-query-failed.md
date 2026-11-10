---
title: quill-pricing-export scheduled query failed
doc_type: runbook
owner_team: quill-data-platform
classification: Internal
system: Google BigQuery
last_reviewed: 2026-08-22
access_groups:
- lm-eng-all
---

# quill-pricing-export scheduled query failed

**Service:** `quill-pricing-export` · **Platform:** Google BigQuery · **Owner:** quill-data-platform · **Alert:** `QuillPricingExportFailed`

## When to use this runbook

The alert fires when the BigQuery scheduled query `pricing_factors_daily` has not succeeded by 6:00 UTC. Impact is usually internal at first and can become customer-facing after about 30 minutes.

## Before you start

- Acknowledge the page in ServiceNow On-Call and join the incident bridge from the incident record.
- `gcloud config set project quill-analytics-prod`

## Diagnose

1. `bq ls --transfer_config --transfer_location=us --project_id quill-analytics-prod | grep pricing`
2. `bq ls --transfer_run --run_attempt=LATEST projects/quill-analytics-prod/locations/us/transferConfigs/<config-id>`
3. A `quotaExceeded` error means the reservation `quill-batch` slots are exhausted by ad-hoc queries.

## Mitigate

1. Re-run: `bq mk --transfer_run --run_time=$(date -u +%FT%TZ) projects/quill-analytics-prod/locations/us/transferConfigs/<config-id>`
2. The S3 copy to `lm-quill-exports-prod` is triggered by the table update, so no AWS action is needed after a successful re-run.

## Verify

- `QuillPricingExportFailed` resolves in Grafana and stays clear for 15 minutes.
- Post a short summary in the incident: what you saw, what you changed, the time it recovered.

## Escalate

If the alert is not mitigated within 45 minutes, declare a Sev2 incident if none is open and page the owning team's secondary through assignment group `LM-Quill-Data`.

## History

- 2025-06-27: first version.
- 2026-08-22: reviewed after a game day; commands re-tested.
