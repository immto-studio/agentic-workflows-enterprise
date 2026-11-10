# Billing alarms: Google Cloud

## What it creates

- `google_project_service` for `billingbudgets.googleapis.com` and `monitoring.googleapis.com` in the lab project (left enabled on destroy).
- `google_monitoring_notification_channel` `lab-billing-email` of type `email` to `alert_email`, in the lab project.
- `google_billing_budget` `lab-billing-monthly` on `billing_account`, filtered to the lab project, with an amount of `monthly_limit_usd` (default 150) and threshold rules at 50, 80 and 100 percent of current spend and 100 percent of forecasted spend. Alerts go to the notification channel and, by default, to the billing account's admins and users.

The notification channel carries the labels `project = "agentic-workflows-enterprise"` and `owner = var.owner`. Billing budgets have no labels.

## Cost

Free. Cloud Billing budgets and Cloud Monitoring email notification channels are not billed. Expected cost: 0 USD per month.

## Before you apply

1. Use the dedicated lab (trial) project, never a production one.
2. The billing account must be billed in USD: the budget amount is in USD and Google rejects a currency that differs from the billing account's.
3. The identity needs `roles/billing.costsManager` (or Billing Account Administrator) on the billing account, and `roles/monitoring.notificationChannelEditor` and `roles/serviceusage.serviceUsageAdmin` on the project.

## Credentials

The Google provider reads Application Default Credentials. Point it at a service account key kept outside the repository, or use your user credentials:

```
export GOOGLE_APPLICATION_CREDENTIALS="$HOME/.larkspur/gcp-lab-sa.json"
# or: gcloud auth application-default login
```

The provider sets `user_project_override` and `billing_project` to the lab project so the Billing Budgets API accepts user credentials.

## Apply

```
cd terraform/billing-alarms/gcp
cp terraform.tfvars.example ~/.larkspur/gcp.tfvars    # then edit it
terraform init && terraform plan -var-file="$HOME/.larkspur/gcp.tfvars" -out=billing.tfplan
terraform apply billing.tfplan
```

## Destroy

```
terraform destroy -var-file="$HOME/.larkspur/gcp.tfvars"
```

Only destroy when the project itself is being closed. Confirm nothing is left with `gcloud billing budgets list --billing-account=<BILLING_ACCOUNT>` and `gcloud beta monitoring channels list --project=<PROJECT_ID>`.

## Status

Validated (`terraform validate`) with Terraform 1.17.1 and `hashicorp/google` 7.46.2 on 2026-10-28. Not yet applied to a real project.
