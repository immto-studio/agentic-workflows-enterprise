---
title: Break-glass unseal of the production Vault cluster
doc_type: runbook
owner_team: security-engineering
classification: Restricted
system: HashiCorp Vault
last_reviewed: 2026-06-04
access_groups:
- lm-vault-break-glass
---

# Break-glass unseal of the production Vault cluster

**Cluster:** `vault-prod` (5-node integrated storage, EKS `lm-shared-use1-01`, namespace `vault`)
**Use only when:** auto-unseal through AWS KMS key `alias/lm-vault-autounseal-prod` is unavailable
and Vault has been sealed for more than 10 minutes.

## Who can run this

Only members of `lm-vault-break-glass`. The procedure needs the recovery key shards held by the
five named custodians (Security Engineering x2, SRE Core x2, CISO office x1). Shards are stored in
tamper-evident envelopes in the Columbus and Hartford office safes; the custodian roster is in
ServiceNow under knowledge article KB0041877.

## Steps

1. Open a Sev1 in ServiceNow with category **SEC-BG** (break glass). This automatically starts
   the bridge and notifies the CISO duty officer.
2. Confirm KMS is the cause, not the network:

   ```
   aws kms describe-key --key-id alias/lm-vault-autounseal-prod --region us-east-1
   kubectl -n vault exec vault-0 -- vault status -format=json | jq '.sealed, .recovery_seal'
   ```

3. Migrate to Shamir recovery. The recovery threshold is **3 of 5 recovery key shards**. Each
   custodian enters their shard on `vault-0` directly; shards are never pasted into chat or tickets:

   ```
   kubectl -n vault exec -it vault-0 -- vault operator unseal -migrate
   ```

4. Once `vault-0` is unsealed, the raft followers rejoin. Check with
   `vault operator raft list-peers`; all five peers must show `voter=true`.
5. Rotate the root token generated during recovery within 1 hour and revoke it with
   `vault token revoke <token>`. Record the accessor in the incident.

## Afterwards

- Re-key the recovery shards within 5 business days (`vault operator rekey -target=recovery`).
- The custodian envelopes are re-sealed and the serial numbers written to KB0041877.
