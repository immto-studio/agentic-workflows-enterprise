---
title: claims-events consumer lag on MSK
doc_type: runbook
owner_team: claims-engineering
classification: Internal
system: Amazon MSK
last_reviewed: 2025-04-27
access_groups:
- lm-eng-all
---

# claims-events consumer lag on MSK

**Service:** `claims-events-consumer` · **Platform:** Amazon MSK · **Owner:** claims-engineering · **Alert:** `ClaimsEventsConsumerLag`

## When to use this runbook

The alert fires when consumer group `claims-events-consumer` lag is above 250000 messages. Check the service's SLO panel first to see how fast the error budget is burning.

## Before you start

- Acknowledge the page in ServiceNow On-Call and join the incident bridge from the incident record.
- `aws eks update-kubeconfig --name lm-prod-use1-01 --region us-east-1` (production clusters are read-only for engineers; mutating commands need the `lm-prod-operator` role)

## Diagnose

1. `kafka-consumer-groups.sh --bootstrap-server $MSK_BOOTSTRAP --command-config ~/msk-iam.properties --describe --group claims-events-consumer`
2. `kubectl -n claims-prod logs deploy/claims-events-consumer --since=20m | grep -i rebalance`; frequent rebalances mean `max.poll.interval.ms` is exceeded.

## Mitigate

1. Scale consumers up to the partition count (24): `kubectl -n claims-prod scale deploy/claims-events-consumer --replicas=24`
2. If one partition is stuck on a poison message, check the DLT `claims-events.dlt` and skip with the documented offset reset only after Claims Engineering agrees.

## Verify

- `ClaimsEventsConsumerLag` resolves in Grafana and stays clear for 30 minutes.
- Post a short summary in the incident: what you saw, what you changed, the time it recovered.

## Escalate

If the alert is not mitigated within 30 minutes, declare a Sev2 incident if none is open and page the owning team's secondary through assignment group `LM-Claims-Eng`.

## History

- 2025-03-17: first version.
- 2025-04-27: reviewed after a game day; commands re-tested.
