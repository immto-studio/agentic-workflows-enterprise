---
title: 'Terraform module: aws-route53-zone'
doc_type: terraform-module
owner_team: network-engineering
classification: Internal
system: Amazon Route 53
last_reviewed: 2025-10-24
access_groups:
- lm-eng-all
---

# aws-route53-zone

Version **3.6.5**. A private or public hosted zone with DNSSEC for public zones and query logging.

Source: `https://github.larkspur.internal/larkspur-platform/terraform-aws-route53-zone`

## Requirements

| Name | Version |
|---|---|
| terraform | >= 1.8 |
| aws | ~> 5.80 |

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `zone_name` | string | required | Zone |
| `private` | bool | `true` | Private zone |
| `vpc_ids` | list(string) | `[]` | VPCs to associate for private zones |

## Outputs

- `zone_id`
- `name_servers`

## Usage

```hcl
module "route53_zone" {
  source    = "git::https://github.larkspur.internal/larkspur-platform/terraform-aws-route53-zone.git?ref=v3.6.5"
  zone_name = "claims.larkspur.internal"
}
```

## Changelog

- v3.6.5 (2025-10-24): tags are now merged with the provider `default_tags` instead of replacing them.
- v3.5.0: pinned the provider minor version after a breaking change upstream.
