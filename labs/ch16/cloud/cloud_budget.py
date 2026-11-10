"""The budget, read back through the API at the session's start and at its end (step 7, item 1).

The budget is the first resource the session makes (terraform/budget.tf): a monthly cost budget with an SNS topic
in us-east-2 as its subscriber and no address anywhere. This reads it back the way an operator would check it:
the limit, the calculated spend, each notification with the kind of its subscribers, and beside it the free
plan's state, whose credits are the account's cap (book D-029).

Run (from labs/ch16, with the session's environment):
    python cloud/cloud_budget.py start --out results/<date>/cloud
    python cloud/cloud_budget.py end --out results/<date>/cloud
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import cloud_session  # noqa: E402


def subscriber_kind(address: str) -> str:
    return "sns-topic" if address.startswith("arn:aws:sns:") else "other"


def read_back(budgets: Any, account_id: str, name: str) -> dict[str, Any]:
    """The budget as AWS Budgets reports it, with its notifications and the kind of each subscriber."""
    budget = budgets.describe_budget(AccountId=account_id, BudgetName=name)["Budget"]
    out: dict[str, Any] = {
        "name": budget["BudgetName"], "type": budget["BudgetType"], "time_unit": budget["TimeUnit"],
        "limit": budget["BudgetLimit"], "calculated_spend": budget.get("CalculatedSpend"),
        "time_period": budget.get("TimePeriod"), "last_updated": budget.get("LastUpdatedTime"),
        "notifications": [],
    }
    notifications = budgets.describe_notifications_for_budget(AccountId=account_id, BudgetName=name)["Notifications"]
    for notification in notifications:
        subscribers = budgets.describe_subscribers_for_notification(
            AccountId=account_id, BudgetName=name, Notification=notification)["Subscribers"]
        out["notifications"].append({
            "threshold": notification["Threshold"], "threshold_type": notification.get("ThresholdType"),
            "type": notification["NotificationType"], "operator": notification["ComparisonOperator"],
            "state": notification.get("NotificationState"),
            "subscribers": [{"type": s["SubscriptionType"], "address_kind": subscriber_kind(s["Address"])}
                            for s in subscribers],
        })
    return out


def plan_state(freetier: Any) -> dict[str, Any]:
    state = freetier.get_account_plan_state()
    return {"plan": state.get("accountPlanType"), "status": state.get("accountPlanStatus"),
            "remaining_credits": state.get("accountPlanRemainingCredits"),
            "expires": str(state.get("accountPlanExpirationDate"))[:10]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("moment", choices=("start", "end"))
    parser.add_argument("--name", help="the budget's name (default: the Terraform output budget_name)")
    parser.add_argument("--out", type=Path, default=cloud_session.results_dir())
    args = parser.parse_args(argv)
    cloud_session.require_environment()
    s = cloud_session.session()
    name = args.name or cloud_session.terraform_outputs()["budget_name"]
    account_id = s.client("sts").get_caller_identity()["Account"]
    record = {"at": cloud_session.utc(),
              "budget": read_back(s.client("budgets", region_name="us-east-1"), account_id, name),
              "plan": plan_state(s.client("freetier", region_name="us-east-1"))}
    cloud_session.merge_json(args.out / "budget.json", args.moment, record)
    print(f"budget {name}: limit {record['budget']['limit']}, spend {record['budget']['calculated_spend']}, "
          f"credits {record['plan']['remaining_credits']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
