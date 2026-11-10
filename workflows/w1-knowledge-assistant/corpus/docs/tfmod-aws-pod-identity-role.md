---
title: 'Terraform module: aws-pod-identity-role'
doc_type: terraform-module
owner_team: platform-engineering
classification: Internal
system: Amazon EKS
last_reviewed: 2026-07-21
access_groups:
- lm-eng-all
---

# aws-pod-identity-role

Version **2.2.4**. An IAM role with an EKS Pod Identity association for one service account.

Source: `https://github.larkspur.internal/larkspur-platform/terraform-aws-pod-identity-role`

## Requirements

| Name | Version |
|---|---|
| terraform | >= 1.7 |
| aws | ~> 5.80 |

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `cluster_name` | string | required | EKS cluster |
| `namespace` | string | required | Namespace |
| `service_account` | string | required | Service account |
| `policy_json` | string | required | Inline policy |

## Outputs

- `role_arn`
- `association_id`

## Usage

```hcl
module "pod_identity_role" {
  source          = "git::https://github.larkspur.internal/larkspur-platform/terraform-aws-pod-identity-role.git?ref=v2.2.4"
  cluster_name    = "lm-prod-use1-02"
  namespace       = "claims-prod"
  service_account = "claims-api"
  policy_json     = data.aws_iam_policy_document.claims_api.json
}
```

## Changelog

- v2.2.4 (2026-07-21): moved alarms to the shared alarm-set module.
- v2.1.0: documented the required permissions for the apply role.
