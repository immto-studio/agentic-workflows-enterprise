---
title: Failing over the claims Aurora cluster
doc_type: runbook
owner_team: sre-core
classification: Internal
system: Amazon Aurora PostgreSQL
last_reviewed: 2025-03-11
access_groups:
- lm-eng-all
---

# Failing over the claims Aurora cluster

Use this when the writer of `claims-aurora-prod` is unhealthy and Aurora has not failed over by itself.

## Steps

1. Page the DBA team through ServiceNow (`LM-DBA`) before doing anything.
2. Trigger the failover directly:

   ```
   aws rds failover-db-cluster --db-cluster-identifier claims-aurora-prod \
     --target-db-instance-identifier claims-aurora-prod-instance-2
   ```

3. Expect about **120 seconds** of write unavailability. `claims-api` reconnects on its own after
   its connection pool times out.
4. Confirm the new writer with `aws rds describe-db-clusters --db-cluster-identifier claims-aurora-prod`.
