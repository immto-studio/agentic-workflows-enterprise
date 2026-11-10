---
title: S3 replication lag for claims documents
doc_type: runbook
owner_team: claims-engineering
classification: Internal
system: Amazon S3
last_reviewed: 2026-06-04
access_groups:
- lm-eng-all
---

# S3 replication lag for claims documents

**Service:** `claims-documents-replication` · **Platform:** Amazon S3 · **Owner:** claims-engineering · **Alert:** `ClaimsDocsReplicationLatency`

## When to use this runbook

The alert fires when `ReplicationLatency` for `lm-claims-documents-prod` to `lm-claims-documents-dr` is above 15 minutes. Impact is usually internal at first and can become customer-facing after about 30 minutes.

## Before you start

- Acknowledge the page in ServiceNow On-Call and join the incident bridge from the incident record.
- `aws sso login --profile lm-prod-readonly`

## Diagnose

1. `aws s3api get-bucket-replication --bucket lm-claims-documents-prod`
2. Check `OperationsFailedReplication` in CloudWatch for the rule `dr-usw2`.
3. A KMS permission error on the destination key appears as failed operations, not as latency.

## Mitigate

1. For failed objects, start an S3 Batch Replication job for `FAILED` status from the console or `aws s3control create-job`.
2. RPO for claims documents is 1 hour; tell the DR coordinator if latency exceeds that.

## Verify

- `ClaimsDocsReplicationLatency` resolves in Grafana and stays clear for 15 minutes.
- Post a short summary in the incident: what you saw, what you changed, the time it recovered.

## Escalate

If the alert is not mitigated within 45 minutes, declare a Sev3 incident if none is open and page the owning team's secondary through assignment group `LM-Claims-Eng`.

## History

- 2025-07-26: first version.
- 2026-06-04: reviewed after a game day; commands re-tested.
