# Billing alarms: AWS

## What it creates

- `aws_budgets_budget` `lab-billing-monthly`: monthly COST budget of `monthly_limit_usd` (default 150 USD), emailing `alert_email` at 50, 80 and 100 percent of actual spend and at 100 percent of forecasted spend.
- `aws_sns_topic` `lab-billing-alarm` and an email `aws_sns_topic_subscription` to `alert_email`.
- `aws_cloudwatch_metric_alarm` `lab-billing-estimated-charges` on `AWS/Billing` `EstimatedCharges` (Currency `USD`, maximum over 6 hours) at the same limit, publishing to the topic.

The provider is fixed to `us-east-1`: billing metrics exist only there. AWS Budgets is global. Every resource is tagged `project = "agentic-workflows-enterprise"` and `owner = var.owner` through `default_tags`.

## Cost

Free or near-free. Budgets without budget actions are free, the first 10 CloudWatch alarms are in the free tier, and SNS email deliveries are free for the first 1,000 per month. Expected cost: 0 USD per month.

## Before you apply

1. Use the dedicated lab account, never a production one.
2. Enable billing alerts once: Billing and Cost Management, Billing preferences, "Receive CloudWatch billing alerts". Without it the `EstimatedCharges` metric has no data and the alarm stays in `OK`/`INSUFFICIENT_DATA`. The budget works regardless.
3. After apply, open the "AWS Notification - Subscription Confirmation" email and confirm; until then the SNS subscription is pending and the alarm emails nobody.

## Credentials

The AWS provider reads the standard environment variables. Keep the credentials file outside the repository:

```
export AWS_SHARED_CREDENTIALS_FILE="$HOME/.aws/credentials"   # or a path from your .env
export AWS_PROFILE=larkspur-lab
```

The identity needs `budgets:*` on the budget, `sns:CreateTopic`, `sns:Subscribe`, `sns:GetTopicAttributes`, `sns:DeleteTopic`, `cloudwatch:PutMetricAlarm`, `cloudwatch:DescribeAlarms`, `cloudwatch:DeleteAlarms` and the matching tag permissions.

## Apply

```
cd terraform/billing-alarms/aws
cp terraform.tfvars.example ~/.larkspur/aws.tfvars    # then edit it
terraform init && terraform plan -var-file="$HOME/.larkspur/aws.tfvars" -out=billing.tfplan
terraform apply billing.tfplan
```

## Destroy

```
terraform destroy -var-file="$HOME/.larkspur/aws.tfvars"
```

Only destroy when the account itself is being closed: this module is the safety net for every other lab. Confirm nothing is left with `aws budgets describe-budgets --account-id "$(aws sts get-caller-identity --query Account --output text)"` and `aws cloudwatch describe-alarms --region us-east-1 --alarm-name-prefix lab-billing`. An SNS email subscription that was never confirmed cannot be deleted through the API; AWS removes it automatically after a few days.

## Status

Validated (`terraform validate`) with Terraform 1.17.1 and `hashicorp/aws` 6.71.0 on 2026-10-28. Not yet applied to a real account.
