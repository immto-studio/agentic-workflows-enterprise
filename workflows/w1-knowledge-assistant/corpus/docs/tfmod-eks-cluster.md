---
title: 'Terraform module: eks-cluster'
doc_type: terraform-module
owner_team: platform-engineering
classification: Internal
system: Amazon EKS
last_reviewed: 2026-07-14
access_groups:
- lm-eng-all
---

# eks-cluster

Version **5.2.0**. Creates an EKS cluster with a small system node group and Karpenter for
everything else. Managed node groups for workloads and Cluster Autoscaler were removed in 5.0.0.

## Requirements

| Name | Version |
|---|---|
| terraform | >= 1.9 |
| aws | ~> 6.2 |
| helm | ~> 2.17 |

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `cluster_name` | string | required | Cluster name |
| `kubernetes_version` | string | `"1.33"` | EKS version |
| `system_node_instance_type` | string | `"m7g.large"` | Graviton instances for the system node group |
| `karpenter_nodepools` | map(object) | see `variables.tf` | Karpenter NodePools; default pool allows m7g, c7g, r7g |
| `enable_pod_identity` | bool | `true` | EKS Pod Identity agent (replaces IRSA for new workloads) |

## Usage

```hcl
module "eks" {
  source       = "git::https://github.larkspur.internal/larkspur-platform/terraform-aws-eks-cluster.git?ref=v5.2.0"
  cluster_name = "lm-prod-use1-02"
}
```

## Upgrading from 3.x

Run `terraform state mv` for the node groups as described in `UPGRADE-5.0.md`, then drain the old
managed node groups; Karpenter takes over scheduling.
