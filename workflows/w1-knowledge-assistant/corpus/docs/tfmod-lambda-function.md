---
title: 'Terraform module: lambda-function'
doc_type: terraform-module
owner_team: platform-engineering
classification: Internal
system: AWS Lambda
last_reviewed: 2026-06-10
access_groups:
- lm-eng-all
---

# lambda-function

Version **4.1.3**. Packages and deploys a Lambda function with a `live` alias, log group, and
least-privilege execution role.

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `function_name` | string | required | Name, suffixed with the environment |
| `runtime` | string | `"python3.12"` | Lambda runtime |
| `architecture` | string | `"arm64"` | `arm64` or `x86_64` |
| `timeout_seconds` | number | `30` | Function timeout |
| `memory_mb` | number | `512` | Memory size |
| `reserved_concurrency` | number | `null` | Reserved concurrency; null means unreserved |
| `log_retention_days` | number | `30` | CloudWatch log retention |

## Usage

```hcl
module "attachment_scan" {
  source        = "git::https://github.larkspur.internal/larkspur-platform/terraform-aws-lambda-function.git?ref=v4.1.3"
  function_name = "claims-attachments-scan"
  source_dir    = "${path.module}/src"
}
```
