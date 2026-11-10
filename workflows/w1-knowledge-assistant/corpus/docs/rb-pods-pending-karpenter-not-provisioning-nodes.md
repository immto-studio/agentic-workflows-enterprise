---
title: 'Pods pending: Karpenter not provisioning nodes'
doc_type: runbook
owner_team: platform-engineering
classification: Internal
system: Amazon EKS
last_reviewed: 2025-02-09
access_groups:
- lm-eng-all
---

# Pods pending: Karpenter not provisioning nodes

**Service:** `karpenter` · **Platform:** Amazon EKS · **Owner:** platform-engineering · **Alert:** `PodsPendingTooLong`

## When to use this runbook

The alert fires when more than 10 pods are `Pending` for over 10 minutes in a production cluster. In most cases no data is lost, but downstream work falls behind the longer it lasts.

## Before you start

- Acknowledge the page in ServiceNow On-Call and join the incident bridge from the incident record.
- `aws eks update-kubeconfig --name lm-prod-use1-02 --region us-east-1` (production clusters are read-only for engineers; mutating commands need the `lm-prod-operator` role)

## Diagnose

1. `kubectl get pods -A --field-selector=status.phase=Pending | head -30`
2. `kubectl -n karpenter logs deploy/karpenter --since=20m | grep -iE 'error|insufficient|could not'`
3. `kubectl get nodeclaims` and look for `Launched=False`; `InsufficientInstanceCapacity` means the instance family is exhausted in the AZ.

## Mitigate

1. Widen the NodePool instance families temporarily (for example add `m7i` next to `m7g`) through `platform-gitops/karpenter/nodepools.yaml`.
2. Check the EC2 vCPU service quota: `aws service-quotas get-service-quota --service-code ec2 --quota-code L-1216C47A`

## Verify

- `PodsPendingTooLong` resolves in Grafana and stays clear for 30 minutes.
- Post a short summary in the incident: what you saw, what you changed, the time it recovered.

## Escalate

If the alert is not mitigated within 45 minutes, declare a Sev2 incident if none is open and page the owning team's secondary through assignment group `LM-Platform`.

## History

- 2025-01-07: first version.
- 2025-02-09: reviewed after a game day; commands re-tested.
