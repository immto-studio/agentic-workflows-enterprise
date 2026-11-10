---
title: cl-document-service slow responses
doc_type: runbook
owner_team: commercial-lines-dotnet
classification: Internal
system: Azure App Service
last_reviewed: 2025-04-01
access_groups:
- lm-eng-all
---

# cl-document-service slow responses

**Service:** `cl-document-service` · **Platform:** Azure App Service · **Owner:** commercial-lines-dotnet · **Alert:** `ClDocumentServiceSlow`

## When to use this runbook

The alert fires when average response time of `app-cl-docs-prod` is above 2500 ms. Impact is usually internal at first and can become customer-facing after about 30 minutes.

## Before you start

- Acknowledge the page in ServiceNow On-Call and join the incident bridge from the incident record.
- `az login` with your Entra ID account and activate the `CL-Prod-Operator` PIM role.

## Diagnose

1. `az webapp log tail -g rg-cl-docs-prod -n app-cl-docs-prod`
2. Check Blob Storage throttling on `stcldocsprod` (`ServerBusy` errors in the storage metrics).

## Mitigate

1. Restart one instance at a time from the portal (Diagnose and solve problems, Advanced Application Restart).
2. If throttled, move the document cache to the premium account per the commercial lines architecture page.

## Verify

- `ClDocumentServiceSlow` resolves in Grafana and stays clear for 15 minutes.
- Post a short summary in the incident: what you saw, what you changed, the time it recovered.

## Escalate

If the alert is not mitigated within 30 minutes, declare a Sev2 incident if none is open and page the owning team's secondary through assignment group `LM-CL-DotNet`.

## History

- 2025-01-27: first version.
- 2025-04-01: reviewed after a game day; commands re-tested.
