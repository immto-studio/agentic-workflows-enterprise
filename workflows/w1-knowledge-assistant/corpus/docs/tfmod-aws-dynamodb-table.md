---
title: 'Terraform module: aws-dynamodb-table'
doc_type: terraform-module
owner_team: platform-engineering
classification: Internal
system: Amazon DynamoDB
last_reviewed: 2026-03-13
access_groups:
- lm-eng-all
---

# aws-dynamodb-table

Version **1.8.4**. A DynamoDB table with on-demand capacity, point-in-time recovery and a customer-managed key.

Source: `https://github.larkspur.internal/larkspur-platform/terraform-aws-dynamodb-table`

## Requirements

| Name | Version |
|---|---|
| terraform | >= 1.8 |
| aws | ~> 5.95 |

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `name` | string | required | Table name |
| `hash_key` | string | required | Partition key |
| `range_key` | string | `null` | Sort key |
| `ttl_attribute` | string | `null` | TTL attribute |
| `kms_key_arn` | string | required | Key |

## Outputs

- `table_arn`
- `stream_arn`

## Usage

```hcl
module "dynamodb_table" {
  source      = "git::https://github.larkspur.internal/larkspur-platform/terraform-aws-dynamodb-table.git?ref=v1.8.4"
  name        = "quote-sessions-prod"
  hash_key    = "session_id"
  kms_key_arn = module.policy_kms.key_arn
}
```

## Changelog

- v1.8.4 (2026-03-13): tags are now merged with the provider `default_tags` instead of replacing them.
- v1.7.0: pinned the provider minor version after a breaking change upstream.
