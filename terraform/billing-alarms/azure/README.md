# Billing alarms: Azure

## What it creates

- `azurerm_resource_group` `lab-billing-rg` in `location` (default `westeurope`), holding the action group.
- `azurerm_monitor_action_group` `lab-billing-ag` with one email receiver, `alert_email`.
- `azurerm_consumption_budget_subscription` `lab-billing-monthly` on `subscription_id`, monthly, with an amount of `monthly_limit_usd` (default 150) and notifications to the action group at 50, 80 and 100 percent of actual cost and 100 percent of forecasted cost.

The budget starts on the first day of the month in which you apply (override with `budget_start_date`). The resource group and action group are tagged `project = "agentic-workflows-enterprise"` and `owner = var.owner`; budgets have no tags.

## Cost

Free. Cost Management budgets, resource groups and action group email notifications (first 1,000 per month) are not billed. Expected cost: 0 USD per month.

## Before you apply

1. Use the dedicated lab (trial) subscription, never a production one.
2. The amount is in the subscription's billing currency; it means USD only on a USD-billed subscription.
3. The identity needs Contributor (or Cost Management Contributor plus Monitoring Contributor) on the subscription.
4. Cost Management budgets are not available on every offer type; if apply fails with an offer-type error, check the subscription's offer in Cost Management.

## Credentials

The azurerm provider reads the `ARM_*` environment variables. For a service principal with a client secret:

```
export ARM_TENANT_ID=...
export ARM_SUBSCRIPTION_ID=...
export ARM_CLIENT_ID=...
export ARM_CLIENT_SECRET=...      # from your .env, never the repository
```

Without `ARM_CLIENT_ID`/`ARM_CLIENT_SECRET` the provider falls back to the Azure CLI login (`az login`). `subscription_id` is still passed as a variable because the budget is scoped to it.

## Apply

```
cd terraform/billing-alarms/azure
cp terraform.tfvars.example ~/.larkspur/azure.tfvars    # then edit it
terraform init && terraform plan -var-file="$HOME/.larkspur/azure.tfvars" -out=billing.tfplan
terraform apply billing.tfplan
```

## Destroy

```
terraform destroy -var-file="$HOME/.larkspur/azure.tfvars"
```

Only destroy when the subscription itself is being closed. Confirm nothing is left with `az consumption budget list --subscription <SUBSCRIPTION_ID>` and `az group show --name lab-billing-rg` (should report that the group was not found).

## Status

Validated (`terraform validate`) with Terraform 1.17.1 and `hashicorp/azurerm` 4.67.0 on 2026-10-28. Not yet applied to a real subscription.
