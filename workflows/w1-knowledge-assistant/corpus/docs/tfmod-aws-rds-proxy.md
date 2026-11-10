---
title: 'Terraform module: aws-rds-proxy'
doc_type: terraform-module
owner_team: platform-engineering
classification: Internal
system: Amazon RDS Proxy
last_reviewed: 2026-09-12
access_groups:
- lm-eng-all
---

# aws-rds-proxy

Version **4.5.1**. RDS Proxy in front of an Aurora cluster, with credentials synced from Vault.

Source: `https://github.larkspur.internal/larkspur-platform/terraform-aws-rds-proxy`

## Requirements

| Name | Version |
|---|---|
| terraform | >= 1.7 |
| aws | ~> 5.95 |

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `name` | string | required | Proxy name |
| `db_cluster_identifier` | string | required | Target cluster |
| `max_connections_percent` | number | `75` | Share of max_connections the proxy may use |
| `idle_client_timeout` | number | `1800` | Seconds |

## Outputs

- `proxy_endpoint`
- `proxy_arn`

## Usage

```hcl
module "rds_proxy" {
  source                = "git::https://github.larkspur.internal/larkspur-platform/terraform-aws-rds-proxy.git?ref=v4.5.1"
  name                  = "claims-proxy-prod"
  db_cluster_identifier = module.claims_db.cluster_identifier
}
```

## Changelog

- v4.5.1 (2026-09-12): documented the required permissions for the apply role.
- v4.4.0: pinned the provider minor version after a breaking change upstream.
