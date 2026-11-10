---
title: SAML sign-in failures after certificate rollover
doc_type: runbook
owner_team: identity-access-management
classification: Internal
system: Microsoft Entra ID
last_reviewed: 2026-01-19
access_groups:
- lm-eng-all
---

# SAML sign-in failures after certificate rollover

**Service:** `entra-sso` · **Platform:** Microsoft Entra ID · **Owner:** identity-access-management · **Alert:** `EntraSamlFailures`

## When to use this runbook

The alert fires when sign-in failures with `AADSTS` errors for one enterprise application exceed 50 in 15 minutes. Reports may reach #ops-announce before the alert does; check there for context.

## Before you start

- Acknowledge the page in ServiceNow On-Call and join the incident bridge from the incident record.
- Activate the `Application Administrator` role in PIM (eligible for IAM on-call).

## Diagnose

1. Entra admin center, Sign-in logs, filter by application and status Failure; note the AADSTS code.
2. `az ad sp show --id <app-id> --query '{name:displayName,certs:keyCredentials[].endDateTime}'`
3. AADSTS50011 means a reply URL mismatch; AADSTS700027 means the signing certificate changed and the app has not picked it up.

## Mitigate

1. If the new certificate is active and the app has not updated metadata, make the previous certificate active again until the app owner imports the new one.
2. Record the app owner's metadata refresh in the change record.

## Verify

- `EntraSamlFailures` resolves in Grafana and stays clear for 10 minutes.
- Post a short summary in the incident: what you saw, what you changed, the time it recovered.

## Escalate

If the alert is not mitigated within 20 minutes, declare a Sev2 incident if none is open and page the owning team's secondary through assignment group `LM-IAM`.

## History

- 2025-07-14: first version.
- 2026-01-19: reviewed after a game day; commands re-tested.
