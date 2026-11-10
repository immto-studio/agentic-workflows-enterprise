---
title: payments-ledger Aurora replica lag
doc_type: runbook
owner_team: billing-engineering
classification: Internal
system: Amazon Aurora PostgreSQL
last_reviewed: 2026-01-06
access_groups:
- lm-eng-all
---

# payments-ledger Aurora replica lag

**Service:** `payments-ledger` · **Platform:** Amazon Aurora PostgreSQL · **Owner:** billing-engineering · **Alert:** `PaymentsLedgerReplicaLag`

## When to use this runbook

The alert fires when `AuroraReplicaLag` on `payments-ledger-aurora-prod` is above 1000 ms for 5 minutes. Impact is usually internal at first and can become customer-facing after about 30 minutes.

## Before you start

- Acknowledge the page in ServiceNow On-Call and join the incident bridge from the incident record.
- `aws sso login --profile lm-prod-dba-readonly`, then connect with `lm-dbctl psql <cluster> --readonly` (IAM authentication, 15-minute tokens)

## Diagnose

1. `aws rds describe-db-clusters --db-cluster-identifier payments-ledger-aurora-prod --query 'DBClusters[0].DBClusterMembers'`
2. Check long-running write transactions on the writer: `SELECT pid, now()-xact_start AS age, left(query,80) FROM pg_stat_activity WHERE xact_start IS NOT NULL ORDER BY age DESC LIMIT 10;`
3. The month-end reconciliation job `ledger-reconcile` causes lag on the 1st business day; check whether it is running.

## Mitigate

1. Route reporting reads to the writer temporarily: set `LEDGER_READ_ENDPOINT=writer` in the `ledger-reporting` ConfigMap and restart.
2. If one reader is lagging and the others are fine, reboot it: `aws rds reboot-db-instance --db-instance-identifier <reader-id>`

## Verify

- `PaymentsLedgerReplicaLag` resolves in Grafana and stays clear for 10 minutes.
- Post a short summary in the incident: what you saw, what you changed, the time it recovered.

## Escalate

If the alert is not mitigated within 30 minutes, declare a Sev3 incident if none is open and page the owning team's secondary through assignment group `LM-Billing-Eng`.

## History

- 2025-08-08: first version.
- 2026-01-06: reviewed after a game day; commands re-tested.
