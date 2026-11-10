---
title: 'Terraform module: aws-vpc'
doc_type: terraform-module
owner_team: network-engineering
classification: Internal
system: Amazon VPC
last_reviewed: 2026-10-12
access_groups:
- lm-eng-all
---

# aws-vpc

Version **3.6.3**. A three-tier VPC with Transit Gateway attachment, flow logs to S3, and gateway endpoints for S3 and DynamoDB.

Source: `https://github.larkspur.internal/larkspur-platform/terraform-aws-vpc`

## Requirements

| Name | Version |
|---|---|
| terraform | >= 1.10 |
| aws | ~> 6.0 |

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `name` | string | required | VPC name |
| `cidr_block` | string | required | Allocated from the IPAM pool |
| `az_count` | number | `3` | Availability zones |
| `transit_gateway_id` | string | required | Shared TGW |
| `flow_log_retention_days` | number | `90` | Flow log retention |

## Outputs

- `vpc_id`
- `private_subnet_ids`
- `intra_subnet_ids`

## Usage

```hcl
module "vpc" {
  source             = "git::https://github.larkspur.internal/larkspur-platform/terraform-aws-vpc.git?ref=v3.6.3"
  name               = "lm-claims-prod-use1"
  cidr_block         = "10.42.0.0/16"
  transit_gateway_id = data.aws_ec2_transit_gateway.shared.id
}
```

## Changelog

- v3.6.3 (2026-10-12): tags are now merged with the provider `default_tags` instead of replacing them.
- v3.5.0: pinned the provider minor version after a breaking change upstream.
