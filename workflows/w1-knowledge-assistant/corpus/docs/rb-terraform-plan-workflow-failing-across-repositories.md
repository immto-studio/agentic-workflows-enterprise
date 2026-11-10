---
title: Terraform plan workflow failing across repositories
doc_type: runbook
owner_team: platform-engineering
classification: Internal
system: GitHub Actions
last_reviewed: 2026-01-27
access_groups:
- lm-eng-all
---

# Terraform plan workflow failing across repositories

**Service:** `terraform-plan-pipeline` · **Platform:** GitHub Actions · **Owner:** platform-engineering · **Alert:** `TerraformPlanFailures`

## When to use this runbook

The alert fires when more than 10 `terraform-plan` workflow runs fail in 30 minutes across the organization. In most cases no data is lost, but downstream work falls behind the longer it lasts.

## Before you start

- Acknowledge the page in ServiceNow On-Call and join the incident bridge from the incident record.
- `export GH_HOST=github.larkspur.internal && gh auth status`

## Diagnose

1. `gh run list -R larkspur-platform/terraform-live --workflow terraform-plan.yml --limit 10`
2. `gh run view <run-id> -R larkspur-platform/terraform-live --log-failed | tail -60`
3. `Error: No valid credential sources found` means the GitHub OIDC trust for role `gha-terraform-plan` changed.

## Mitigate

1. Revert the last change to `iam-github-oidc` in `terraform-live/accounts/shared`.
2. Re-run failed jobs once fixed: `gh run rerun <run-id> -R larkspur-platform/terraform-live --failed`

## Verify

- `TerraformPlanFailures` resolves in Grafana and stays clear for 15 minutes.
- Post a short summary in the incident: what you saw, what you changed, the time it recovered.

## Escalate

If the alert is not mitigated within 30 minutes, declare a Sev3 incident if none is open and page the owning team's secondary through assignment group `LM-Platform`.

## History

- 2025-02-26: first version.
- 2026-01-27: reviewed after a game day; commands re-tested.
