---
title: 'Terraform module: eks-cluster'
doc_type: terraform-module
owner_team: platform-engineering
classification: Internal
system: Amazon EKS
last_reviewed: 2025-04-02
access_groups:
- lm-eng-all
---

# eks-cluster

Version **3.4.1**. Creates an EKS cluster with managed node groups.

## Requirements

| Name | Version |
|---|---|
| terraform | >= 1.5 |
| aws | ~> 5.40 |

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `cluster_name` | string | required | Cluster name |
| `kubernetes_version` | string | `"1.29"` | EKS version |
| `node_instance_types` | list(string) | `["m5.xlarge"]` | Managed node group instance types |
| `node_min_size` | number | `3` | Minimum nodes |
| `enable_cluster_autoscaler` | bool | `true` | Install Cluster Autoscaler |

## Usage

```hcl
module "eks" {
  source             = "git::https://github.larkspur.internal/larkspur-platform/terraform-aws-eks-cluster.git?ref=v3.4.1"
  cluster_name       = "lm-prod-use1-01"
  kubernetes_version = "1.29"
}
```
