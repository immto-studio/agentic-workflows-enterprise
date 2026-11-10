---
title: Container image builds failing to push to ECR
doc_type: runbook
owner_team: developer-platform
classification: Internal
system: GitHub Actions
last_reviewed: 2026-05-30
access_groups:
- lm-eng-all
---

# Container image builds failing to push to ECR

**Service:** `container-image-build` · **Platform:** GitHub Actions · **Owner:** developer-platform · **Alert:** `ImagePushFailures`

## When to use this runbook

The alert fires when image push failures to ECR exceed 5 in 15 minutes. Impact is usually internal at first and can become customer-facing after about 30 minutes.

## Before you start

- Acknowledge the page in ServiceNow On-Call and join the incident bridge from the incident record.
- `export GH_HOST=github.larkspur.internal && gh auth status`

## Diagnose

1. `gh run view <run-id> --log-failed | grep -i denied`
2. Check ECR pull-through cache and repository policy: `aws ecr describe-repositories --repository-names <repo>`
3. Image scanning on push can reject images with critical findings when the repository uses `scanOnPush` with the block policy.

## Mitigate

1. If the repository does not exist, create it through `ecr-repository` in Terraform; the pipeline does not create repositories.
2. For critical CVEs, rebuild on the latest golden base image `lm-base/python:3.12` or `lm-base/dotnet:8.0`.

## Verify

- `ImagePushFailures` resolves in Grafana and stays clear for 30 minutes.
- Post a short summary in the incident: what you saw, what you changed, the time it recovered.

## Escalate

If the alert is not mitigated within 45 minutes, declare a Sev2 incident if none is open and page the owning team's secondary through assignment group `LM-DevPlatform`.

## History

- 2025-08-02: first version.
- 2026-05-30: reviewed after a game day; commands re-tested.
