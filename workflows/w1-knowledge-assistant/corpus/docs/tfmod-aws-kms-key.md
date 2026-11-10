---
title: 'Terraform module: aws-kms-key'
doc_type: terraform-module
owner_team: security-engineering
classification: Internal
system: AWS KMS
last_reviewed: 2025-12-18
access_groups:
- lm-eng-all
---

# aws-kms-key

Version **4.6.4**. A customer-managed KMS key for one data domain with rotation enabled and a key policy built from role lists.

Source: `https://github.larkspur.internal/larkspur-platform/terraform-aws-kms-key`

## Requirements

| Name | Version |
|---|---|
| terraform | >= 1.7 |
| aws | ~> 5.95 |

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `alias` | string | required | Alias without the `alias/` prefix |
| `admin_role_arns` | list(string) | required | Key administrators |
| `user_role_arns` | list(string) | required | Roles allowed to encrypt and decrypt |
| `deletion_window_days` | number | `30` | Deletion window |

## Outputs

- `key_arn`
- `alias_arn`

## Usage

```hcl
module "kms_key" {
  source          = "git::https://github.larkspur.internal/larkspur-platform/terraform-aws-kms-key.git?ref=v4.6.4"
  alias           = "lm-claims-prod"
  admin_role_arns = [local.security_admin_role]
  user_role_arns  = [module.claims_api_role.arn]
}
```

## Changelog

- v4.6.4 (2025-12-18): added example for the DR region.
- v4.5.0: documented the required permissions for the apply role.
