---
title: 'Terraform module: aws-sqs-queue'
doc_type: terraform-module
owner_team: platform-engineering
classification: Internal
system: Amazon SQS
last_reviewed: 2025-09-03
access_groups:
- lm-eng-all
---

# aws-sqs-queue

Version **2.5.2**. An SQS queue with a dead-letter queue, KMS encryption and CloudWatch alarms on age of oldest message.

Source: `https://github.larkspur.internal/larkspur-platform/terraform-aws-sqs-queue`

## Requirements

| Name | Version |
|---|---|
| terraform | >= 1.7 |
| aws | ~> 5.95 |

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `name` | string | required | Queue name |
| `visibility_timeout_seconds` | number | `60` | Visibility timeout |
| `max_receive_count` | number | `5` | Receives before DLQ |
| `fifo` | bool | `false` | FIFO queue |
| `oldest_message_alarm_seconds` | number | `300` | Alarm threshold |

## Outputs

- `queue_url`
- `queue_arn`
- `dlq_arn`

## Usage

```hcl
module "sqs_queue" {
  source = "git::https://github.larkspur.internal/larkspur-platform/terraform-aws-sqs-queue.git?ref=v2.5.2"
  name   = "doc-render-requests-prod"
}
```

## Changelog

- v2.5.2 (2025-09-03): moved alarms to the shared alarm-set module.
- v2.4.0: tags are now merged with the provider `default_tags` instead of replacing them.
