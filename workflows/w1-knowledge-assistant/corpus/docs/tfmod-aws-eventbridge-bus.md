---
title: 'Terraform module: aws-eventbridge-bus'
doc_type: terraform-module
owner_team: integration-engineering
classification: Internal
system: Amazon EventBridge
last_reviewed: 2025-11-18
access_groups:
- lm-eng-all
---

# aws-eventbridge-bus

Version **3.2.1**. A custom event bus with archive and cross-account rules for operational events.

Source: `https://github.larkspur.internal/larkspur-platform/terraform-aws-eventbridge-bus`

## Requirements

| Name | Version |
|---|---|
| terraform | >= 1.7 |
| aws | ~> 5.95 |

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `name` | string | required | Bus name |
| `archive_retention_days` | number | `30` | Archive retention |
| `allowed_account_ids` | list(string) | `[]` | Accounts allowed to put events |

## Outputs

- `bus_arn`

## Usage

```hcl
module "eventbridge_bus" {
  source = "git::https://github.larkspur.internal/larkspur-platform/terraform-aws-eventbridge-bus.git?ref=v3.2.1"
  name   = "ops-events-prod"
}
```

## Changelog

- v3.2.1 (2025-11-18): added validation for naming conventions.
- v3.1.0: moved alarms to the shared alarm-set module.
