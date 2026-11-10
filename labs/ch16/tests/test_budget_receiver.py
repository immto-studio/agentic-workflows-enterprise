"""The webhook receiver: LiteLLM's budget event in, a line naming the owner and FinOps out.

The event is built with LiteLLM 1.106.6's own `WebhookEvent`, serialized as its sender serializes it
(`model_dump_json`), so the receiver is tested on the shape the gateway sends.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import receiver
from starlette.testclient import TestClient

LAB = Path(__file__).resolve().parents[1]


def litellm_event(alias: str, event: str = "soft_budget_crossed") -> str:
    from litellm.proxy._types import Litellm_EntityType, WebhookEvent

    return WebhookEvent(event=event, event_message="Key Budget: Total Soft Budget:`160.0`", spend=160.0003,
                        max_budget=200.0, soft_budget=160.0, token="hashed", key_alias=alias,
                        event_group=Litellm_EntityType.KEY).model_dump_json()


def projection_event(alias: str) -> dict:
    """LiteLLM's projection alert as the drills recorded it: the soft budget in max_budget, relabeled by its event."""
    from litellm.proxy._types import Litellm_EntityType, WebhookEvent

    return json.loads(WebhookEvent(
        event="threshold_crossed", event_message="Key Budget: Projected Limit Exceeded5% or less of budget remaining",
        spend=159.751012, max_budget=160.0, soft_budget=None, token="hashed", key_alias=alias,
        projected_spend=1726.16, projected_exceeded_date="2026-11-03",
        event_group=Litellm_EntityType.KEY).model_dump_json())


def test_each_alert_is_named_for_what_it_is():
    assert receiver.kind_of(json.loads(litellm_event("w2-ops-assistant"))) == "the soft budget reached"
    assert receiver.kind_of(json.loads(litellm_event("w2-ops-assistant", "budget_crossed"))) == "the budget reached"
    assert receiver.kind_of(projection_event("w2-ops-assistant")) == "the month's pace projected past the soft budget"


def test_the_owners_come_from_the_manifests():
    owners = receiver.load_owners(LAB.parent / "ch05" / "manifest")
    assert owners == {"w2-ops-assistant": "sam.okafor@larkspur.example", "w3-incident": "tomasz.nowak@larkspur.example"}


def test_an_alert_goes_to_the_owner_and_finops_and_one_for_an_unknown_key_to_finops_alone():
    owners = {"w2-ops-assistant": "sam.okafor@larkspur.example"}
    at = datetime(2026, 11, 3, 23, 26, tzinfo=timezone.utc)
    known = receiver.forward(json.loads(litellm_event("w2-ops-assistant")), owners, at)
    assert known["forwarded_to"] == ["sam.okafor@larkspur.example", "finops@larkspur.example"]
    assert (known["event"], known["spend"], known["soft_budget"], known["max_budget"]) == \
        ("soft_budget_crossed", 160.0003, 160.0, 200.0)
    assert receiver.forward(json.loads(litellm_event("someone-else")), owners, at)["forwarded_to"] == \
        ["finops@larkspur.example"]


def test_the_app_records_what_litellm_posts(tmp_path):
    outbox = tmp_path / "alerts.jsonl"
    app = receiver.build_app(outbox, {"w2-ops-assistant": "sam.okafor@larkspur.example"})
    with TestClient(app) as client:
        answer = client.post("/budget-alert", content=litellm_event("w2-ops-assistant"),
                             headers={"Content-type": "application/json"})
        assert answer.status_code == 200  # LiteLLM counts the alert as sent only on a 200
        assert client.post("/budget-alert", content="not json").status_code == 400
        listed = client.get("/alerts").json()
    assert [a["event"] for a in listed] == ["soft_budget_crossed"]
    assert listed[0]["sent"]["key_alias"] == "w2-ops-assistant"
    assert len(outbox.read_text(encoding="utf-8").splitlines()) == 1
