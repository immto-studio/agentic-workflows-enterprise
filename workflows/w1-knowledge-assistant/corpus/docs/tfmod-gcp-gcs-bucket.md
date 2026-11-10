---
title: 'Terraform module: gcp-gcs-bucket'
doc_type: terraform-module
owner_team: quill-data-platform
classification: Internal
system: Google Cloud Storage
last_reviewed: 2026-09-29
access_groups:
- lm-eng-all
---

# gcp-gcs-bucket

Version **4.7.4**. A GCS bucket with uniform access, public access prevention and lifecycle rules.

Source: `https://github.larkspur.internal/larkspur-quill/terraform-gcp-gcs-bucket`

## Requirements

| Name | Version |
|---|---|
| terraform | >= 1.9 |
| google | ~> 6.20 |

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `name` | string | required | Bucket name |
| `location` | string | `"US"` | Location |
| `storage_class` | string | `"STANDARD"` | Class |
| `archive_after_days` | number | `180` | Move to ARCHIVE after |

## Outputs

- `bucket_url`

## Usage

```hcl
module "gcs_bucket" {
  source = "git::https://github.larkspur.internal/larkspur-quill/terraform-gcp-gcs-bucket.git?ref=v4.7.4"
  name   = "quill-trips-archive-prod"
}
```

## Changelog

- v4.7.4 (2026-09-29): outputs are marked sensitive where they contain ARNs of key material.
- v4.6.0: pinned the provider minor version after a breaking change upstream.
