---
title: 'Terraform module: grafana-folder-alerts'
doc_type: terraform-module
owner_team: observability
classification: Internal
system: Grafana
last_reviewed: 2025-11-23
access_groups:
- lm-eng-all
---

# grafana-folder-alerts

Version **1.7.5**. A Grafana folder with team permissions, contact points and alert rules from YAML files.

Source: `https://github.larkspur.internal/larkspur-platform/terraform-grafana-folder-alerts`

## Requirements

| Name | Version |
|---|---|
| terraform | >= 1.8 |
| grafana | ~> 4.2 |

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `folder` | string | required | Folder name |
| `team` | string | required | Grafana team with edit rights |
| `rules_dir` | string | required | Directory with rule YAML |
| `servicenow_contact_point` | string | `"servicenow-default"` | Contact point |

## Outputs

- `folder_uid`

## Usage

```hcl
module "folder_alerts" {
  source    = "git::https://github.larkspur.internal/larkspur-platform/terraform-grafana-folder-alerts.git?ref=v1.7.5"
  folder    = "Claims"
  team      = "claims-engineering"
  rules_dir = "${path.module}/alerts"
}
```

## Changelog

- v1.7.5 (2025-11-23): tags are now merged with the provider `default_tags` instead of replacing them.
- v1.6.0: moved alarms to the shared alarm-set module.
