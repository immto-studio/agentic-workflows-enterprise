---
title: 'Terraform module: gcp-gke-autopilot'
doc_type: terraform-module
owner_team: quill-data-platform
classification: Internal
system: Google Kubernetes Engine
last_reviewed: 2025-07-27
access_groups:
- lm-eng-all
---

# gcp-gke-autopilot

Version **3.3.1**. A private GKE Autopilot cluster with Workload Identity and Binary Authorization.

Source: `https://github.larkspur.internal/larkspur-quill/terraform-gcp-gke-autopilot`

## Requirements

| Name | Version |
|---|---|
| terraform | >= 1.10 |
| google | ~> 6.40 |

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `name` | string | required | Cluster name |
| `project_id` | string | required | Project |
| `region` | string | `"us-central1"` | Region |
| `master_ipv4_cidr_block` | string | required | Control plane range |
| `release_channel` | string | `"REGULAR"` | Release channel |

## Outputs

- `cluster_endpoint`
- `workload_pool`

## Usage

```hcl
module "gke_autopilot" {
  source                 = "git::https://github.larkspur.internal/larkspur-quill/terraform-gcp-gke-autopilot.git?ref=v3.3.1"
  name                   = "quill-stg-usc1"
  project_id             = "quill-stg-3307"
  master_ipv4_cidr_block = "172.16.8.0/28"
}
```

## Changelog

- v3.3.1 (2025-07-27): tags are now merged with the provider `default_tags` instead of replacing them.
- v3.2.0: moved alarms to the shared alarm-set module.
