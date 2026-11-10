---
title: 'Terraform module: azure-app-service-dotnet'
doc_type: terraform-module
owner_team: commercial-lines-dotnet
classification: Internal
system: Azure App Service
last_reviewed: 2026-04-16
access_groups:
- lm-eng-all
---

# azure-app-service-dotnet

Version **3.0.3**. A Linux App Service for .NET 8 with a staging slot, VNet integration and Application Insights.

Source: `https://github.larkspur.internal/larkspur-platform/terraform-azure-app-service-dotnet`

## Requirements

| Name | Version |
|---|---|
| terraform | >= 1.9 |
| azurerm | ~> 4.30 |

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `name` | string | required | App name |
| `resource_group_name` | string | required | Resource group |
| `sku_name` | string | `"P1v3"` | Plan SKU |
| `worker_count` | number | `3` | Instances |
| `subnet_id` | string | required | Integration subnet |

## Outputs

- `default_hostname`
- `principal_id`

## Usage

```hcl
module "app_service_dotnet" {
  source              = "git::https://github.larkspur.internal/larkspur-platform/terraform-azure-app-service-dotnet.git?ref=v3.0.3"
  name                = "app-cl-quotes-prod"
  resource_group_name = "rg-cl-quotes-prod"
  subnet_id           = module.cl_vnet.app_subnet_id
}
```

## Changelog

- v3.0.3 (2026-04-16): moved alarms to the shared alarm-set module.
- v3.0.0: added validation for naming conventions.
