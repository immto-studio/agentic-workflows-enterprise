---
title: 'Terraform module: aws-cloudfront-waf'
doc_type: terraform-module
owner_team: digital-channels
classification: Internal
system: Amazon CloudFront
last_reviewed: 2026-05-16
access_groups:
- lm-eng-all
---

# aws-cloudfront-waf

Version **2.0.0**. A CloudFront distribution with origin access control, an AWS WAF web ACL with managed rules, and access logs.

Source: `https://github.larkspur.internal/larkspur-platform/terraform-aws-cloudfront-waf`

## Requirements

| Name | Version |
|---|---|
| terraform | >= 1.9 |
| aws | ~> 5.95 |

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `domain_names` | list(string) | required | Aliases |
| `origin_domain` | string | required | Origin |
| `acm_certificate_arn` | string | required | Certificate in us-east-1 |
| `price_class` | string | `"PriceClass_100"` | Price class |

## Outputs

- `distribution_id`
- `distribution_domain_name`

## Usage

```hcl
module "cloudfront_waf" {
  source              = "git::https://github.larkspur.internal/larkspur-platform/terraform-aws-cloudfront-waf.git?ref=v2.0.0"
  domain_names        = ["www.larkspur-mutual.com"]
  origin_domain       = module.site_bucket.bucket_regional_domain_name
  acm_certificate_arn = module.cert.arn
}
```

## Changelog

- v2.0.0 (2026-05-16): added example for the DR region.
- v1.9.0: tags are now merged with the provider `default_tags` instead of replacing them.
