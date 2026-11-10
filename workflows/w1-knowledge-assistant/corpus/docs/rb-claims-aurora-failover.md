---
title: Failing over the claims Aurora cluster (Aurora PostgreSQL 16)
doc_type: runbook
owner_team: sre-core
classification: Internal
system: Amazon Aurora PostgreSQL
last_reviewed: 2026-08-19
access_groups:
- lm-eng-all
---

# Failing over the claims Aurora cluster (Aurora PostgreSQL 16)

Since the June 2026 migration, claims runs on `claims-aurora-prod-v2` (Aurora PostgreSQL 16.4) behind
RDS Proxy `claims-proxy-prod`. The old `claims-aurora-prod` cluster is read-only and will be deleted.

## Steps

1. Do **not** call `aws rds failover-db-cluster` directly; it bypasses the pre-checks. Use the
   wrapper, which checks replica lag, snapshots the parameter group and posts to the incident:

   ```
   lm-dbctl failover claims-aurora-prod-v2 --reason INC<number>
   ```

2. Expect **under 35 seconds** of write unavailability; RDS Proxy holds client connections during
   the switch, so `claims-api` does not need a restart.
3. Confirm with `lm-dbctl status claims-aurora-prod-v2`; the writer and both readers must be `available`.
4. The on-call engineer may fail over without paging the DBA team; inform `LM-DBA` in the incident
   afterwards.
