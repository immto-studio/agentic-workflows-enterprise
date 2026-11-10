---
title: 'Terraform module: gcp-bigquery-dataset'
doc_type: terraform-module
owner_team: quill-data-platform
classification: Internal
system: Google BigQuery
last_reviewed: 2026-03-21
access_groups:
- lm-eng-all
---

# gcp-bigquery-dataset

Version **4.5.4**. A BigQuery dataset with CMEK, default table expiration and IAM by group.

Source: `https://github.larkspur.internal/larkspur-quill/terraform-gcp-bigquery-dataset`

## Requirements

| Name | Version |
|---|---|
| terraform | >= 1.9 |
| google | ~> 6.40 |

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `dataset_id` | string | required | Dataset |
| `project_id` | string | required | Project |
| `location` | string | `"US"` | Location |
| `reader_groups` | list(string) | `[]` | Groups granted dataViewer |
| `default_table_expiration_days` | number | `null` | Expiration |

## Outputs

- `dataset_id`

## Usage

```hcl
module "bigquery_dataset" {
  source     = "git::https://github.larkspur.internal/larkspur-quill/terraform-gcp-bigquery-dataset.git?ref=v4.5.4"
  dataset_id = "quill_claims_curated"
  project_id = "quill-analytics-prod"
}
```

## Changelog

- v4.5.4 (2026-03-21): added validation for naming conventions.
- v4.4.0: documented the required permissions for the apply role.
