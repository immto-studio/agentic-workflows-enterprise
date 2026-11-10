---
title: 'Terraform module: aws-cloudwatch-alarm-set'
doc_type: terraform-module
owner_team: sre-core
classification: Internal
system: Amazon CloudWatch
last_reviewed: 2025-05-17
access_groups:
- lm-eng-all
---

# aws-cloudwatch-alarm-set

Version **2.6.5**. Standard CloudWatch alarms for a service, routed to the ServiceNow event bridge.

Source: `https://github.larkspur.internal/larkspur-platform/terraform-aws-cloudwatch-alarm-set`

## Requirements

| Name | Version |
|---|---|
| terraform | >= 1.8 |
| aws | ~> 5.95 |

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `service` | string | required | Service name |
| `tier` | number | `2` | Service tier (1 pages, 2 and 3 open tickets) |
| `alb_arn_suffix` | string | `null` | ALB for 5xx and latency alarms |
| `sqs_queue_names` | list(string) | `[]` | Queues for age-of-oldest alarms |

## Outputs

- `alarm_arns`

## Usage

```hcl
module "cloudwatch_alarm_set" {
  source  = "git::https://github.larkspur.internal/larkspur-platform/terraform-aws-cloudwatch-alarm-set.git?ref=v2.6.5"
  service = "claims-api"
}
```

## Changelog

- v2.6.5 (2025-05-17): added example for the DR region.
- v2.5.0: added validation for naming conventions.
