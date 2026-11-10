---
title: 'Terraform module: vault-kubernetes-auth-role'
doc_type: terraform-module
owner_team: security-engineering
classification: Internal
system: HashiCorp Vault
last_reviewed: 2025-03-31
access_groups:
- lm-eng-all
---

# vault-kubernetes-auth-role

Version **4.2.5**. A Vault Kubernetes auth role bound to one namespace and service account, with policies generated from paths.

Source: `https://github.larkspur.internal/larkspur-platform/terraform-vault-kubernetes-auth-role`

## Requirements

| Name | Version |
|---|---|
| terraform | >= 1.9 |
| vault | ~> 4.5 |

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `cluster` | string | required | Auth mount suffix |
| `namespace` | string | required | Namespace |
| `service_account` | string | required | Service account |
| `read_paths` | list(string) | `[]` | KV paths readable |
| `token_ttl` | string | `"1h"` | Token TTL |

## Outputs

- `role_name`
- `policy_name`

## Usage

```hcl
module "kubernetes_auth_role" {
  source          = "git::https://github.larkspur.internal/larkspur-platform/terraform-vault-kubernetes-auth-role.git?ref=v4.2.5"
  cluster         = "lm-prod-use1-02"
  namespace       = "claims-prod"
  service_account = "claims-api"
}
```

## Changelog

- v4.2.5 (2025-03-31): pinned the provider minor version after a breaking change upstream.
- v4.1.0: added validation for naming conventions.
