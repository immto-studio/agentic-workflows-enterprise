---
title: Alerts not creating ServiceNow incidents
doc_type: runbook
owner_team: it-service-management
classification: Internal
system: AWS Lambda
last_reviewed: 2026-06-16
access_groups:
- lm-eng-all
---

# Alerts not creating ServiceNow incidents

**Service:** `snow-event-bridge` · **Platform:** AWS Lambda · **Owner:** it-service-management · **Alert:** `SnowEventBridgeErrors`

## When to use this runbook

The alert fires when `snow-event-bridge-prod` errors are above 10 in 10 minutes. Check the service's SLO panel first to see how fast the error budget is burning.

## Before you start

- Acknowledge the page in ServiceNow On-Call and join the incident bridge from the incident record.
- `aws sso login --profile lm-prod-operator`

## Diagnose

1. `aws logs tail /aws/lambda/snow-event-bridge-prod --since 30m --filter-pattern ERROR`
2. `401` means the ServiceNow integration user password expired or the OAuth client secret rotated.
3. `429` means the ServiceNow rate limit for the integration user was hit (500 requests per hour).

## Mitigate

1. Re-sync the secret from Vault: `vault kv get secret/itsm/snow-event-bridge` and confirm the Lambda environment was updated by Vault Secrets Operator.
2. While broken, on-call engineers watch Grafana alerting directly; post that in #ops-announce.

## Verify

- `SnowEventBridgeErrors` resolves in Grafana and stays clear for 30 minutes.
- Post a short summary in the incident: what you saw, what you changed, the time it recovered.

## Escalate

If the alert is not mitigated within 45 minutes, declare a Sev2 incident if none is open and page the owning team's secondary through assignment group `LM-ITSM`.

## History

- 2025-04-04: first version.
- 2026-06-16: reviewed after a game day; commands re-tested.
