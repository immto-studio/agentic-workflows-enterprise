---
title: LPAS CICS response time degraded
doc_type: runbook
owner_team: mainframe-operations
classification: Internal
system: LPAS mainframe
last_reviewed: 2025-07-25
access_groups:
- lm-eng-all
---

# LPAS CICS response time degraded

**Service:** `lpas-cics-region` · **Platform:** LPAS mainframe · **Owner:** mainframe-operations · **Alert:** `LpasCicsResponseTime`

## When to use this runbook

The alert fires when average CICS transaction response time in region `LPCICSP1` is above 600 ms. Reports may reach #ops-announce before the alert does; check there for context.

## Before you start

- Acknowledge the page in ServiceNow On-Call and join the incident bridge from the incident record.
- Mainframe access is through mainframe operations; open the bridge with them first.

## Diagnose

1. Mainframe operations check the region with `CEMT INQ TASK` and the OMEGAMON CICS response-time view.
2. From AWS, check the MQ bridge depth on the **Integration / MQ bridge** dashboard; a backlog often means CICS is slow, not the bridge.
3. Agent portal quote calls go through `policy-quote-service` to CICS via the `lpas-gateway`; check its p95.

## Mitigate

1. Mainframe operations may route new sessions to the second region `LPCICSP2`.
2. On the AWS side, reduce pressure by enabling the quote cache flag `quote.lpas.cache_ttl_seconds=300`.

## Verify

- `LpasCicsResponseTime` resolves in Grafana and stays clear for 30 minutes.
- Post a short summary in the incident: what you saw, what you changed, the time it recovered.

## Escalate

If the alert is not mitigated within 45 minutes, declare a Sev3 incident if none is open and page the owning team's secondary through assignment group `LM-Mainframe-Ops`.

## History

- 2025-01-03: first version.
- 2025-07-25: reviewed after a game day; commands re-tested.
