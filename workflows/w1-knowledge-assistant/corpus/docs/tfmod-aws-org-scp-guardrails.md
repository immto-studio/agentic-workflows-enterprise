---
title: 'Terraform module: aws-org-scp-guardrails'
doc_type: terraform-module
owner_team: cloud-governance
classification: Confidential
system: AWS Organizations
last_reviewed: 2026-07-01
access_groups:
- lm-cloud-governance
---

# aws-org-scp-guardrails

Service control policies attached at the Larkspur AWS organization root and OUs.
Source: `https://github.larkspur.internal/larkspur-platform/terraform-aws-org-scp-guardrails`

## Policies

| Policy | Attached to | Effect |
|---|---|---|
| `deny-leave-org` | root | accounts cannot leave the organization |
| `deny-non-approved-regions` | Workloads OU | only us-east-1, us-east-2 and us-west-2 |
| `deny-iam-user-keys` | Workloads OU | no `iam:CreateAccessKey` |
| `deny-disable-guardduty` | root | GuardDuty and CloudTrail cannot be stopped |

## Standing exceptions

These accounts are excluded from `deny-iam-user-keys` and are reviewed quarterly:

- `418302557190` (`lm-legacy-ftp-prod`): partner SFTP integration, exception SEC-EXC-0112, expires 2026-12-31
- `730114962285` (`lm-jenkins-legacy`): Jenkins agents pending OIDC migration, SEC-EXC-0131

## Inputs

| Name | Type | Default |
|---|---|---|
| `workloads_ou_id` | string | required |
| `allowed_regions` | list(string) | `["us-east-1", "us-east-2", "us-west-2"]` |
| `exception_account_ids` | list(string) | `[]` |
