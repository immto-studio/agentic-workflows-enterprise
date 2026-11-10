---
title: 'Terraform module: aws-ecr-repository'
doc_type: terraform-module
owner_team: developer-platform
classification: Internal
system: Amazon ECR
last_reviewed: 2025-08-10
access_groups:
- lm-eng-all
---

# aws-ecr-repository

Version **3.9.0**. An ECR repository with immutable tags, scan on push, and a lifecycle policy.

Source: `https://github.larkspur.internal/larkspur-platform/terraform-aws-ecr-repository`

## Requirements

| Name | Version |
|---|---|
| terraform | >= 1.10 |
| aws | ~> 5.80 |

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `name` | string | required | Repository name |
| `keep_last_images` | number | `50` | Images kept by lifecycle policy |
| `pull_principal_arns` | list(string) | `[]` | Extra principals allowed to pull |

## Outputs

- `repository_url`

## Usage

```hcl
module "ecr_repository" {
  source = "git::https://github.larkspur.internal/larkspur-platform/terraform-aws-ecr-repository.git?ref=v3.9.0"
  name   = "claims/claims-api"
}
```

## Changelog

- v3.9.0 (2025-08-10): outputs are marked sensitive where they contain ARNs of key material.
- v3.8.0: tags are now merged with the provider `default_tags` instead of replacing them.
