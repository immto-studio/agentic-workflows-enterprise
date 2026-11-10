---
title: 'Terraform module: gcp-pubsub-topic'
doc_type: terraform-module
owner_team: quill-data-platform
classification: Internal
system: Google Pub/Sub
last_reviewed: 2026-09-06
access_groups:
- lm-eng-all
---

# gcp-pubsub-topic

Version **1.7.2**. A Pub/Sub topic with schema, dead-letter topic and subscriptions.

Source: `https://github.larkspur.internal/larkspur-quill/terraform-gcp-pubsub-topic`

## Requirements

| Name | Version |
|---|---|
| terraform | >= 1.8 |
| google | ~> 6.20 |

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `name` | string | required | Topic |
| `project_id` | string | required | Project |
| `message_retention_duration` | string | `"604800s"` | Retention |
| `subscriptions` | map(object) | `{}` | Subscriptions and their push or pull settings |

## Outputs

- `topic_id`

## Usage

```hcl
module "pubsub_topic" {
  source     = "git::https://github.larkspur.internal/larkspur-quill/terraform-gcp-pubsub-topic.git?ref=v1.7.2"
  name       = "trips-raw"
  project_id = "quill-prod-4821"
}
```

## Changelog

- v1.7.2 (2026-09-06): pinned the provider minor version after a breaking change upstream.
- v1.6.0: tags are now merged with the provider `default_tags` instead of replacing them.
