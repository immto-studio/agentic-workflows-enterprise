---
title: agent-portal returns 502 from the load balancer
doc_type: runbook
owner_team: digital-channels
classification: Internal
system: Amazon EKS
last_reviewed: 2025-08-19
access_groups:
- lm-eng-all
---

# agent-portal returns 502 from the load balancer

**Service:** `agent-portal` · **Platform:** Amazon EKS · **Owner:** digital-channels · **Alert:** `AgentPortalAlb5xx`

## When to use this runbook

The alert fires when the ALB `HTTPCode_ELB_502_Count` for `agent-portal` is above 20 per minute. In most cases no data is lost, but downstream work falls behind the longer it lasts.

## Before you start

- Acknowledge the page in ServiceNow On-Call and join the incident bridge from the incident record.
- `aws eks update-kubeconfig --name lm-prod-use1-01 --region us-east-1` (production clusters are read-only for engineers; mutating commands need the `lm-prod-operator` role)

## Diagnose

1. Check target health: `aws elbv2 describe-target-health --target-group-arn $(aws elbv2 describe-target-groups --names k8s-portalpr-agentpor --query 'TargetGroups[0].TargetGroupArn' --output text)`
2. Check pods for failing readiness: `kubectl -n portal-prod get pods -l app.kubernetes.io/name=agent-portal`
3. Look for keep-alive mismatches: Node.js `keepAliveTimeout` must exceed the ALB idle timeout of 60 seconds.

## Mitigate

1. Roll back: `kubectl -n portal-prod rollout undo deploy/agent-portal`
2. If targets flap during scaling, raise `minReadySeconds` in the Helm values and redeploy.

## Verify

- `AgentPortalAlb5xx` resolves in Grafana and stays clear for 15 minutes.
- Post a short summary in the incident: what you saw, what you changed, the time it recovered.

## Escalate

If the alert is not mitigated within 30 minutes, declare a Sev2 incident if none is open and page the owning team's secondary through assignment group `LM-Digital`.

## History

- 2025-03-11: first version.
- 2025-08-19: reviewed after a game day; commands re-tested.
