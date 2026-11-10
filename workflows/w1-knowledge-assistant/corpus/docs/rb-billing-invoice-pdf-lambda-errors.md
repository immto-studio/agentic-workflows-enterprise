---
title: billing-invoice-pdf Lambda errors
doc_type: runbook
owner_team: billing-engineering
classification: Internal
system: AWS Lambda
last_reviewed: 2025-08-24
access_groups:
- lm-eng-all
---

# billing-invoice-pdf Lambda errors

**Service:** `billing-invoice-pdf` · **Platform:** AWS Lambda · **Owner:** billing-engineering · **Alert:** `InvoicePdfErrors`

## When to use this runbook

The alert fires when the error rate of `billing-invoice-pdf-prod` is above 5% for 10 minutes. Impact is usually internal at first and can become customer-facing after about 30 minutes.

## Before you start

- Acknowledge the page in ServiceNow On-Call and join the incident bridge from the incident record.
- `aws sso login --profile lm-prod-operator`

## Diagnose

1. `aws logs tail /aws/lambda/billing-invoice-pdf-prod --since 30m --filter-pattern ERROR`
2. `Task timed out` means the template service is slow; check `document-render-service` first.
3. Check which version the `live` alias points to: `aws lambda get-alias --function-name billing-invoice-pdf-prod --name live`

## Mitigate

1. Roll back the alias: `aws lambda update-alias --function-name billing-invoice-pdf-prod --name live --function-version <previous>`
2. Failed invoices are retried by the nightly `invoice-retry` job; no manual resend is needed.

## Verify

- `InvoicePdfErrors` resolves in Grafana and stays clear for 10 minutes.
- Post a short summary in the incident: what you saw, what you changed, the time it recovered.

## Escalate

If the alert is not mitigated within 30 minutes, declare a Sev2 incident if none is open and page the owning team's secondary through assignment group `LM-Billing-Eng`.

## History

- 2025-01-15: first version.
- 2025-08-24: reviewed after a game day; commands re-tested.
