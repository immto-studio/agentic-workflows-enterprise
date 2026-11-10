# Billing alarms

The first Terraform applied in every lab account, project and subscription (decision D-018, [Lab safety](../../docs/lab-safety.md)).

Agent labs create resources that keep billing when nobody is looking: an idle OpenSearch Serverless collection behind a knowledge base, a GPU node with no model loaded, a forgotten endpoint. A budget with email alerts is the cheapest insurance against that, so it goes in before anything else and stays until the account is closed. The cap is 150 USD per month per cloud.

Every module alerts at the same points:

| Alert | Basis |
|---|---|
| 50 percent of the monthly limit | actual spend |
| 80 percent | actual spend |
| 100 percent | actual spend |
| 100 percent | forecasted spend for the month |

Alerts notify; they do not stop anything. When one arrives, run the teardown of whatever lab is up.

| Module | Creates | Provider |
|---|---|---|
| [`aws/`](aws/README.md) | AWS Budgets cost budget, CloudWatch alarm on `AWS/Billing` `EstimatedCharges`, SNS topic with email subscription | `hashicorp/aws` 6.71.0 |
| [`gcp/`](gcp/README.md) | Cloud Billing budget scoped to the lab project, Cloud Monitoring email notification channel | `hashicorp/google` 7.46.2 |
| [`azure/`](azure/README.md) | Subscription consumption budget, resource group with an action group that emails | `hashicorp/azurerm` 4.67.0 |

The three modules are independent root modules with local state. Apply only the ones for the clouds you use. Terraform `>= 1.10`; validated with Terraform 1.17.1.

## Variables shared by all three

| Variable | Default | Meaning |
|---|---|---|
| `monthly_limit_usd` | `150` | Monthly limit; must be positive |
| `alert_email` | none | Who receives the alerts |
| `owner` | none | Written to the `owner` tag or label, next to `project = "agentic-workflows-enterprise"` |

Each module has a `terraform.tfvars.example`. Copy it outside the repository (for example `~/.larkspur/aws.tfvars`) and pass it with `-var-file`; `.gitignore` refuses `*.tfvars`. You can also set any variable as `TF_VAR_<name>`, for example `export TF_VAR_alert_email="$BUDGET_ALERT_EMAIL"`.
