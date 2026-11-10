---
title: 'Terraform module: aws-budget-alarm'
doc_type: terraform-module
owner_team: finops
classification: Internal
system: AWS Budgets
last_reviewed: 2025-11-20
access_groups:
- lm-eng-all
---

# aws-budget-alarm

Version **1.2.4**. A monthly cost budget with 50, 80 and 100 percent alerts and an anomaly monitor.

Source: `https://github.larkspur.internal/larkspur-platform/terraform-aws-budget-alarm`

## Requirements

| Name | Version |
|---|---|
| terraform | >= 1.9 |
| aws | ~> 6.0 |

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `account_name` | string | required | Account |
| `monthly_limit_usd` | number | required | Budget |
| `alert_emails` | list(string) | required | Recipients |

## Outputs

- `budget_id`

## Usage

```hcl
module "budget_alarm" {
  source            = "git::https://github.larkspur.internal/larkspur-platform/terraform-aws-budget-alarm.git?ref=v1.2.4"
  account_name      = "lm-claims-prod"
  monthly_limit_usd = 42000
  alert_emails      = ["finops@larkspur-mutual.com"]
}
```

## Changelog

- v1.2.4 (2025-11-20): tags are now merged with the provider `default_tags` instead of replacing them.
- v1.1.0: moved alarms to the shared alarm-set module.
