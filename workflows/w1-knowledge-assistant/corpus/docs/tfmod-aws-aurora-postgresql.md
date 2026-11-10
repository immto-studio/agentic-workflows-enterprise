---
title: 'Terraform module: aws-aurora-postgresql'
doc_type: terraform-module
owner_team: platform-engineering
classification: Internal
system: Amazon Aurora PostgreSQL
last_reviewed: 2026-03-28
access_groups:
- lm-eng-all
---

# aws-aurora-postgresql

Version **2.1.1**. An Aurora PostgreSQL cluster with IAM authentication, Performance Insights, and backups copied to the DR region.

Source: `https://github.larkspur.internal/larkspur-platform/terraform-aws-aurora-postgresql`

## Requirements

| Name | Version |
|---|---|
| terraform | >= 1.9 |
| aws | ~> 6.0 |

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `cluster_identifier` | string | required | Cluster name |
| `engine_version` | string | `"16.4"` | Aurora PostgreSQL version |
| `instance_class` | string | `"db.r7g.xlarge"` | Instance class |
| `reader_count` | number | `2` | Number of readers |
| `backup_retention_days` | number | `14` | Automated backup retention |
| `kms_key_arn` | string | required | Customer-managed key |

## Outputs

- `cluster_endpoint`
- `reader_endpoint`
- `cluster_resource_id`

## Usage

```hcl
module "aurora_postgresql" {
  source             = "git::https://github.larkspur.internal/larkspur-platform/terraform-aws-aurora-postgresql.git?ref=v2.1.1"
  cluster_identifier = "policy-aurora-prod"
  kms_key_arn        = module.policy_kms.key_arn
}
```

## Changelog

- v2.1.1 (2026-03-28): documented the required permissions for the apply role.
- v2.0.0: tags are now merged with the provider `default_tags` instead of replacing them.
