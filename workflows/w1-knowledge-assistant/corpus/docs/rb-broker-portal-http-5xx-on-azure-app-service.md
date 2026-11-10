---
title: broker-portal HTTP 5xx on Azure App Service
doc_type: runbook
owner_team: commercial-lines-dotnet
classification: Internal
system: Azure App Service
last_reviewed: 2026-06-18
access_groups:
- lm-eng-all
---

# broker-portal HTTP 5xx on Azure App Service

**Service:** `broker-portal` · **Platform:** Azure App Service · **Owner:** commercial-lines-dotnet · **Alert:** `BrokerPortal5xx`

## When to use this runbook

The alert fires when `Http5xx` on `app-broker-portal-prod` is above 50 per 5 minutes. Reports may reach #ops-announce before the alert does; check there for context.

## Before you start

- Acknowledge the page in ServiceNow On-Call and join the incident bridge from the incident record.
- `az login` with your Entra ID account and activate the `CL-Prod-Operator` PIM role.

## Diagnose

1. `az account set --subscription sub-commercial-lines-prod`
2. `az monitor app-insights query --app appi-broker-portal-prod --analytics-query 'requests | where timestamp > ago(30m) and success == false | summarize count() by name, resultCode | top 10 by count_'`
3. Check the Azure SQL DTU on `sqldb-broker-prod`; above 90% causes timeouts.

## Mitigate

1. Swap back to the previous release: `az webapp deployment slot swap -g rg-broker-portal-prod -n app-broker-portal-prod --slot staging --target-slot production`
2. Scale out the plan: `az appservice plan update -g rg-broker-portal-prod -n asp-broker-portal-prod --number-of-workers 8`

## Verify

- `BrokerPortal5xx` resolves in Grafana and stays clear for 15 minutes.
- Post a short summary in the incident: what you saw, what you changed, the time it recovered.

## Escalate

If the alert is not mitigated within 45 minutes, declare a Sev2 incident if none is open and page the owning team's secondary through assignment group `LM-CL-DotNet`.

## History

- 2025-11-07: first version.
- 2026-06-18: reviewed after a game day; commands re-tested.
