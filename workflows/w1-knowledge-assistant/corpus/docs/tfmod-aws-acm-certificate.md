---
title: 'Terraform module: aws-acm-certificate'
doc_type: terraform-module
owner_team: network-engineering
classification: Internal
system: AWS Certificate Manager
last_reviewed: 2025-06-20
access_groups:
- lm-eng-all
---

# aws-acm-certificate

Version **1.3.4**. A public ACM certificate validated through Route 53.

Source: `https://github.larkspur.internal/larkspur-platform/terraform-aws-acm-certificate`

## Requirements

| Name | Version |
|---|---|
| terraform | >= 1.9 |
| aws | ~> 6.0 |

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `domain_name` | string | required | Primary name |
| `subject_alternative_names` | list(string) | `[]` | SANs |
| `zone_id` | string | required | Validation zone |

## Outputs

- `certificate_arn`

## Usage

```hcl
module "acm_certificate" {
  source      = "git::https://github.larkspur.internal/larkspur-platform/terraform-aws-acm-certificate.git?ref=v1.3.4"
  domain_name = "api.larkspur-mutual.com"
  zone_id     = module.public_zone.zone_id
}
```

## Changelog

- v1.3.4 (2025-06-20): added example for the DR region.
- v1.2.0: outputs are marked sensitive where they contain ARNs of key material.
