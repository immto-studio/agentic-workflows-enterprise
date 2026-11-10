---
title: document-render-service in CrashLoopBackOff
doc_type: runbook
owner_team: policy-engineering
classification: Internal
system: Amazon EKS
last_reviewed: 2025-01-10
access_groups:
- lm-eng-all
---

# document-render-service in CrashLoopBackOff

**Service:** `document-render-service` · **Platform:** Amazon EKS · **Owner:** policy-engineering · **Alert:** `DocRenderCrashLoop`

## When to use this runbook

The alert fires when more than 5 `document-render-service` pods restart within 10 minutes. Reports may reach #ops-announce before the alert does; check there for context.

## Before you start

- Acknowledge the page in ServiceNow On-Call and join the incident bridge from the incident record.
- `aws eks update-kubeconfig --name lm-prod-use1-01 --region us-east-1` (production clusters are read-only for engineers; mutating commands need the `lm-prod-operator` role)

## Diagnose

1. `kubectl -n docs-prod get pods -l app.kubernetes.io/name=document-render-service`
2. `kubectl -n docs-prod logs <pod> --previous | tail -50`; a missing font file means the template bundle failed to download from `s3://lm-doc-templates-prod`.
3. `kubectl -n docs-prod get events --sort-by=.lastTimestamp | tail -20`

## Mitigate

1. If the template bundle is missing, re-publish it from the `policy-doc-templates` repository with the `publish-templates` workflow.
2. Roll back: `kubectl -n docs-prod rollout undo deploy/document-render-service`
3. Queued renders are retried from SQS `doc-render-requests-prod`; nothing is lost while pods restart.

## Verify

- `DocRenderCrashLoop` resolves in Grafana and stays clear for 15 minutes.
- Post a short summary in the incident: what you saw, what you changed, the time it recovered.

## Escalate

If the alert is not mitigated within 20 minutes, declare a Sev2 incident if none is open and page the owning team's secondary through assignment group `LM-Policy-Eng`.

## History

- 2025-01-02: first version.
- 2025-01-10: reviewed after a game day; commands re-tested.
