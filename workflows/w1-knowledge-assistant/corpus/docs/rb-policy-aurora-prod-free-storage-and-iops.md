---
title: policy-aurora-prod free storage and IOPS
doc_type: runbook
owner_team: policy-engineering
classification: Internal
system: Amazon Aurora PostgreSQL
last_reviewed: 2025-07-31
access_groups:
- lm-eng-all
---

# policy-aurora-prod free storage and IOPS

**Service:** `policy-store` · **Platform:** Amazon Aurora PostgreSQL · **Owner:** policy-engineering · **Alert:** `PolicyAuroraFreeLocalStorage`

## When to use this runbook

The alert fires when `FreeLocalStorage` on a `policy-aurora-prod` instance is below 20 GB. Impact is usually internal at first and can become customer-facing after about 30 minutes.

## Before you start

- Acknowledge the page in ServiceNow On-Call and join the incident bridge from the incident record.
- `aws sso login --profile lm-prod-dba-readonly`, then connect with `lm-dbctl psql <cluster> --readonly` (IAM authentication, 15-minute tokens)

## Diagnose

1. Local storage holds temp files; look for large sorts: `SELECT pid, temp_files, temp_bytes FROM pg_stat_database WHERE datname='policy';`
2. Find the query: `SELECT pid, now()-query_start AS age, left(query,120) FROM pg_stat_activity WHERE state='active' ORDER BY age DESC LIMIT 10;`

## Mitigate

1. Cancel the offending query: `SELECT pg_cancel_backend(<pid>);`
2. If it is a report from `policy-reporting`, ask the owner to add the missing index before re-running.
3. Scaling up the instance class (`db.r7g.2xlarge` to `db.r7g.4xlarge`) doubles local storage but needs a change record.

## Verify

- `PolicyAuroraFreeLocalStorage` resolves in Grafana and stays clear for 15 minutes.
- Post a short summary in the incident: what you saw, what you changed, the time it recovered.

## Escalate

If the alert is not mitigated within 45 minutes, declare a Sev2 incident if none is open and page the owning team's secondary through assignment group `LM-Policy-Eng`.

## History

- 2025-07-17: first version.
- 2025-07-31: reviewed after a game day; commands re-tested.
