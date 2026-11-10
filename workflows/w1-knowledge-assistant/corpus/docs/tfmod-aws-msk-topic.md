---
title: 'Terraform module: aws-msk-topic'
doc_type: terraform-module
owner_team: integration-engineering
classification: Internal
system: Amazon MSK
last_reviewed: 2026-07-19
access_groups:
- lm-eng-all
---

# aws-msk-topic

Version **3.7.4**. A Kafka topic on the shared MSK cluster with ACLs for producer and consumer roles.

Source: `https://github.larkspur.internal/larkspur-platform/terraform-aws-msk-topic`

## Requirements

| Name | Version |
|---|---|
| terraform | >= 1.10 |
| aws | ~> 5.80 |

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `name` | string | required | Topic name, `<domain>.<entity>-events.v<n>` |
| `partitions` | number | `12` | Partition count |
| `retention_hours` | number | `168` | Retention |
| `producer_roles` | list(string) | required | IAM roles allowed to produce |
| `consumer_roles` | list(string) | `[]` | IAM roles allowed to consume |

## Outputs

- `topic_name`

## Usage

```hcl
module "msk_topic" {
  source         = "git::https://github.larkspur.internal/larkspur-platform/terraform-aws-msk-topic.git?ref=v3.7.4"
  name           = "claims.claim-events.v3"
  producer_roles = ["claims-api-prod"]
}
```

## Changelog

- v3.7.4 (2026-07-19): added example for the DR region.
- v3.6.0: documented the required permissions for the apply role.
