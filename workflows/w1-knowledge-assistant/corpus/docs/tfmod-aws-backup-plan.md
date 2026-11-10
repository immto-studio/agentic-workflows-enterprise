---
title: 'Terraform module: aws-backup-plan'
doc_type: terraform-module
owner_team: sre-core
classification: Internal
system: AWS Backup
last_reviewed: 2025-05-06
access_groups:
- lm-eng-all
---

# aws-backup-plan

Version **3.6.2**. An AWS Backup plan selecting resources by tag, with cross-region copy and vault lock.

Source: `https://github.larkspur.internal/larkspur-platform/terraform-aws-backup-plan`

## Requirements

| Name | Version |
|---|---|
| terraform | >= 1.9 |
| aws | ~> 5.80 |

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `plan_name` | string | required | Plan name |
| `selection_tag` | map(string) | `{ backup = "tier1" }` | Resources to include |
| `retention_days` | number | `35` | Retention |
| `copy_to_region` | string | `"us-west-2"` | DR region |

## Outputs

- `plan_id`
- `vault_arn`

## Usage

```hcl
module "backup_plan" {
  source    = "git::https://github.larkspur.internal/larkspur-platform/terraform-aws-backup-plan.git?ref=v3.6.2"
  plan_name = "tier1-daily"
}
```

## Changelog

- v3.6.2 (2025-05-06): pinned the provider minor version after a breaking change upstream.
- v3.5.0: documented the required permissions for the apply role.
