---
title: 'Terraform module: aws-sns-topic'
doc_type: terraform-module
owner_team: platform-engineering
classification: Internal
system: Amazon SNS
last_reviewed: 2025-02-08
access_groups:
- lm-eng-all
---

# aws-sns-topic

Version **1.2.5**. An SNS topic with KMS encryption and a policy limited to named publishers.

Source: `https://github.larkspur.internal/larkspur-platform/terraform-aws-sns-topic`

## Requirements

| Name | Version |
|---|---|
| terraform | >= 1.9 |
| aws | ~> 5.80 |

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `name` | string | required | Topic name |
| `publisher_role_arns` | list(string) | required | Roles allowed to publish |
| `fifo` | bool | `false` | FIFO topic |

## Outputs

- `topic_arn`

## Usage

```hcl
module "sns_topic" {
  source              = "git::https://github.larkspur.internal/larkspur-platform/terraform-aws-sns-topic.git?ref=v1.2.5"
  name                = "policy-renewals-prod"
  publisher_role_arns = [module.renewals_role.arn]
}
```

## Changelog

- v1.2.5 (2025-02-08): outputs are marked sensitive where they contain ARNs of key material.
- v1.1.0: added example for the DR region.
