---
title: 'Terraform module: vault-database-secrets'
doc_type: terraform-module
owner_team: security-engineering
classification: Internal
system: HashiCorp Vault
last_reviewed: 2025-11-10
access_groups:
- lm-eng-all
---

# vault-database-secrets

Version **3.7.2**. A Vault database secrets engine connection and roles for dynamic PostgreSQL credentials.

Source: `https://github.larkspur.internal/larkspur-platform/terraform-vault-database-secrets`

## Requirements

| Name | Version |
|---|---|
| terraform | >= 1.10 |
| vault | ~> 4.5 |

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `connection_name` | string | required | Connection |
| `connection_url` | string | required | PostgreSQL URL template |
| `roles` | map(object) | required | Roles with SQL and TTLs |
| `default_ttl` | string | `"1h"` | Default lease TTL |

## Outputs

- `role_paths`

## Usage

```hcl
module "database_secrets" {
  source          = "git::https://github.larkspur.internal/larkspur-platform/terraform-vault-database-secrets.git?ref=v3.7.2"
  connection_name = "claims-aurora-prod-v2"
  connection_url  = "postgresql://{{username}}:{{password}}@claims-proxy-prod:5432/claims"
  roles           = local.claims_db_roles
}
```

## Changelog

- v3.7.2 (2025-11-10): outputs are marked sensitive where they contain ARNs of key material.
- v3.6.0: documented the required permissions for the apply role.
