---
title: MSK under-replicated partitions
doc_type: runbook
owner_team: policy-engineering
classification: Internal
system: Amazon MSK
last_reviewed: 2026-05-27
access_groups:
- lm-eng-all
---

# MSK under-replicated partitions

**Service:** `policy-change-events` · **Platform:** Amazon MSK · **Owner:** policy-engineering · **Alert:** `MskUnderReplicatedPartitions`

## When to use this runbook

The alert fires when `UnderReplicatedPartitions` on cluster `lm-msk-prod` is above 0 for 10 minutes. Impact is usually internal at first and can become customer-facing after about 30 minutes.

## Before you start

- Acknowledge the page in ServiceNow On-Call and join the incident bridge from the incident record.
- `aws eks update-kubeconfig --name lm-prod-usw2-01 --region us-west-2` (production clusters are read-only for engineers; mutating commands need the `lm-prod-operator` role)

## Diagnose

1. `aws kafka list-nodes --cluster-arn $MSK_CLUSTER_ARN --query 'NodeInfoList[].BrokerNodeInfo.[BrokerId,ClientVpcIpAddress]'`
2. Check broker disk: `KafkaDataLogsDiskUsed` above 85% on any broker.
3. Check for an MSK maintenance event in the AWS Health dashboard.

## Mitigate

1. If disk is the cause, increase broker storage: `aws kafka update-broker-storage --cluster-arn $MSK_CLUSTER_ARN --current-version <v> --target-broker-ebs-volume-info KafkaBrokerNodeId=All,VolumeSizeGB=3000`
2. Producers use `acks=all` with `min.insync.replicas=2`, so writes fail rather than lose data; tell the producing teams.

## Verify

- `MskUnderReplicatedPartitions` resolves in Grafana and stays clear for 15 minutes.
- Post a short summary in the incident: what you saw, what you changed, the time it recovered.

## Escalate

If the alert is not mitigated within 30 minutes, declare a Sev3 incident if none is open and page the owning team's secondary through assignment group `LM-Policy-Eng`.

## History

- 2025-09-16: first version.
- 2026-05-27: reviewed after a game day; commands re-tested.
