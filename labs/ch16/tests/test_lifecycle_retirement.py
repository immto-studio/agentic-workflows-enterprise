"""Step 8's retirement alert: the rules of lifecycle/alerts.yaml fired from the register on a date before, inside and
past the 90-day window, the review window of 180 days, the Legacy notice, the window's edges on a synthetic register,
and nothing for a model with no date published."""

from __future__ import annotations

import datetime as dt

import register as reg
import retirement

REGISTER = reg.load()
RULES = retirement.load_rules()
BEFORE, INSIDE, PAST = dt.date(2026, 11, 9), dt.date(2027, 2, 1), dt.date(2027, 5, 1)


def by_rule(result: dict, rule: str, model: str) -> list[dict]:
    return [a for a in result["alerts"] if a["rule"] == rule and a["model"] == model]


def row(result: dict, model: str) -> dict:
    return next(r for r in result["rows"] if r["model"] == model)


def test_the_rules_the_code_fires_are_the_ones_the_file_names():
    named = {r["name"]: r["action"] for r in RULES["rules"]}
    assert named == {"retired-still-pinned": "page", "retirement-90d": "ticket", "retirement-180d-review": "review",
                     "legacy-notice": "ticket", "unscheduled": "none"}
    assert RULES["windows"] == {"alert_days": 90, "review_days": 180}
    fired = {a["rule"] for day in (BEFORE, INSIDE, PAST) for a in retirement.evaluate(day, REGISTER, RULES)["alerts"]}
    assert fired == {"retired-still-pinned", "retirement-90d", "retirement-180d-review", "legacy-notice"}


def test_before_the_window_a_pinned_model_is_reviewed_and_no_ticket_asks_for_a_move():
    result = retirement.evaluate(BEFORE, REGISTER, RULES)
    gpt4o = row(result, "azure-gpt-4o")
    assert gpt4o["state"] == "review" and gpt4o["days_left"] == 156
    assert by_rule(result, "retirement-90d", "azure-gpt-4o") == []
    assert len(by_rule(result, "retirement-180d-review", "azure-gpt-4o")) == 1
    assert result["pages"] == 0 and result["tickets"] == 1  # gpt-4o's Legacy notice alone
    # Claude 3 Haiku retires in four days, and Larkspur doesn't run on it: a review row, no ticket, no page.
    haiku = row(result, "aws-claude-3-haiku")
    assert haiku["state"] == "alert" and not haiku["pinned"]
    assert by_rule(result, "retirement-90d", "aws-claude-3-haiku") == []
    assert len(by_rule(result, "retirement-180d-review", "aws-claude-3-haiku")) == 1


def test_inside_the_window_the_pinned_models_get_their_tickets():
    result = retirement.evaluate(INSIDE, REGISTER, RULES)
    assert row(result, "azure-gpt-4o")["days_left"] == 72
    ticket = by_rule(result, "retirement-90d", "azure-gpt-4o")
    assert len(ticket) == 1 and "gpt-5.1" in ticket[0]["detail"]
    embedding = by_rule(result, "retirement-90d", "google-text-multilingual-embedding-002")
    assert len(embedding) == 1 and embedding[0]["days_left"] == 59 and "none processed in Canada" in embedding[0]["detail"]
    assert by_rule(result, "retirement-90d", "aws-llama3-70b") == []  # 57 days away, and not pinned
    assert row(result, "aws-llama3-70b")["state"] == "alert"
    assert row(result, "aws-claude-3-haiku")["state"] == "retired" and by_rule(result, "retirement-180d-review", "aws-claude-3-haiku") == []
    assert result["pages"] == 0 and result["tickets"] == 3


def test_past_the_window_a_pinned_model_still_pinned_pages():
    result = retirement.evaluate(PAST, REGISTER, RULES)
    assert row(result, "azure-gpt-4o")["state"] == "retired" and row(result, "azure-gpt-4o")["days_left"] == -17
    assert len(by_rule(result, "retired-still-pinned", "azure-gpt-4o")) == 1
    assert len(by_rule(result, "retired-still-pinned", "google-text-multilingual-embedding-002")) == 1
    assert by_rule(result, "retired-still-pinned", "azure-gpt-4-1-mini") == []  # retired too, not pinned
    assert result["pages"] == 2
    assert row(result, "google-gemini-3-5-flash")["state"] == "unscheduled"  # no date, only an earliest one


def test_a_model_with_no_published_date_gets_no_alert_and_shows_its_earliest_date():
    result = retirement.evaluate(BEFORE, REGISTER, RULES)
    nova = row(result, "aws-nova-lite")
    assert nova["state"] == "unscheduled" and nova["earliest"] == "2025-12-05" and nova["earliest_passed"] is True
    assert not [a for a in result["alerts"] if a["model"] == "aws-nova-lite"]
    local = row(result, "local-gpt-oss-20b")
    assert local["state"] == "unscheduled" and local["earliest"] is None


def test_the_legacy_notice_fires_for_a_pinned_model_in_a_notice_stage_and_not_otherwise():
    for day in (BEFORE, INSIDE, PAST):
        result = retirement.evaluate(day, REGISTER, RULES)
        assert len(by_rule(result, "legacy-notice", "azure-gpt-4o")) == 1
        assert by_rule(result, "legacy-notice", "aws-claude-3-haiku") == []  # Legacy, not pinned
        assert by_rule(result, "legacy-notice", "aws-nova-lite") == []  # pinned, Active


def _synthetic(retires: dt.date | None, pinned: bool = True, stage: str = "Active", earliest: dt.date | None = None) -> dict:
    return {"models": [{"id": "m", "name": "m", "cloud": "aws", "pinned": pinned, "stage": stage, "retires": retires,
                        "retires_no_earlier_than": earliest, "replacement": "r", "legacy_from": None}]}


def test_the_windows_edges():
    on = dt.date(2027, 1, 1)
    for days, state in ((-1, "retired"), (0, "alert"), (90, "alert"), (91, "review"), (180, "review"), (181, "clear")):
        result = retirement.evaluate(on, _synthetic(on + dt.timedelta(days=days)), RULES)
        assert result["rows"][0]["state"] == state, days
        assert result["rows"][0]["days_left"] == days
    page = retirement.evaluate(on, _synthetic(on - dt.timedelta(days=1)), RULES)
    assert [a["action"] for a in page["alerts"]] == ["page"]
    ticket = retirement.evaluate(on, _synthetic(on + dt.timedelta(days=90)), RULES)
    assert sorted(a["action"] for a in ticket["alerts"]) == ["review", "ticket"]
    quiet = retirement.evaluate(on, _synthetic(on + dt.timedelta(days=90), pinned=False), RULES)
    assert [a["action"] for a in quiet["alerts"]] == ["review"]
    legacy = retirement.evaluate(on, _synthetic(None, stage="Legacy", earliest=on), RULES)
    assert [a["rule"] for a in legacy["alerts"]] == ["legacy-notice"] and legacy["rows"][0]["earliest_passed"] is True


def test_the_render_names_every_row_and_alert():
    result = retirement.evaluate(INSIDE, REGISTER, RULES)
    text = retirement.render(result)
    assert text.count("\n|") == len(result["rows"]) + 2
    assert text.count("\n- ") == len(result["alerts"])
    assert "Retirement on 2027-02-01" in text
