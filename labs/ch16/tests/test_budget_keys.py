"""The monthly budget as LiteLLM's key settings: one key per workflow from its manifest, a reset at midnight on the
1st in Toronto, and the config the drills ran.

The reset times are checked against LiteLLM 1.106.6's own `get_next_standardized_reset_time`, the function its
reset job and its key endpoints call, so the expectation in `keys.next_reset` is LiteLLM's and not only ours.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import keys
import pytest
import yaml

LAB = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((LAB / "budget" / "litellm.config.yaml").read_text(encoding="utf-8"))
CH05_CONFIG = yaml.safe_load((LAB.parent / "ch05" / "gateway" / "litellm.config.yaml").read_text(encoding="utf-8"))
MANIFESTS = sorted([*(LAB.parent / "ch05" / "manifest").glob("*.yaml"),
                    *(LAB.parent.parent / "workflows").glob("*/manifest/*.yaml")])
TORONTO = keys.ZoneInfo("America/Toronto")


@pytest.mark.parametrize("path", MANIFESTS, ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_each_manifest_gives_its_key(path):
    manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
    body = keys.key_request(manifest)
    budget = manifest["budget"]
    assert body["key_alias"] == manifest["workflow"]
    assert body["models"] == manifest["models"]
    assert body["max_budget"] == budget["per_month_usd"]
    assert body["soft_budget"] == pytest.approx(0.8 * budget["per_month_usd"])
    assert body["budget_duration"] == "1mo"
    assert body["metadata"] == {"workflow": manifest["workflow"], "owner": manifest["owner"],
                                "sponsor": manifest["sponsor"], "data_class_max": manifest["data_class_max"]}
    assert "tags" not in body  # key tags need the enterprise license (fact sheet 8.1)


CASES = [
    (datetime(2026, 11, 3, 23, 0, tzinfo=timezone.utc), datetime(2026, 12, 1, 5, 0, tzinfo=timezone.utc)),
    # 23:30 on 30 November in Toronto is already 1 December in UTC; the month is still November here
    (datetime(2026, 11, 30, 23, 30, tzinfo=TORONTO), datetime(2026, 12, 1, 5, 0, tzinfo=timezone.utc)),
    (datetime(2026, 12, 1, 0, 0, tzinfo=TORONTO), datetime(2027, 1, 1, 5, 0, tzinfo=timezone.utc)),
    (datetime(2026, 12, 31, 23, 59, tzinfo=TORONTO), datetime(2027, 1, 1, 5, 0, tzinfo=timezone.utc)),
    # daylight saving time: April starts at 04:00 UTC, November at 04:00 UTC too (EDT until 1 November 2026)
    (datetime(2027, 3, 15, 12, 0, tzinfo=timezone.utc), datetime(2027, 4, 1, 4, 0, tzinfo=timezone.utc)),
    (datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc), datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc)),
]


@pytest.mark.parametrize("now, expected", CASES)
def test_the_month_resets_at_midnight_on_the_first_in_toronto(now, expected):
    assert keys.next_reset(now) == expected
    local = keys.next_reset(now).astimezone(TORONTO)
    assert (local.day, local.hour, local.minute, local.second) == (1, 0, 0, 0)


@pytest.mark.parametrize("now, expected", CASES)
def test_litellm_resets_at_the_same_instant(now, expected):
    from litellm.litellm_core_utils.duration_parser import get_next_standardized_reset_time

    got = get_next_standardized_reset_time(duration="1mo", current_time=now.astimezone(timezone.utc),
                                           timezone_str="America/Toronto")
    assert got.astimezone(timezone.utc) == expected


def test_without_the_timezone_the_reset_comes_five_hours_early_in_toronto():
    from litellm.litellm_core_utils.duration_parser import get_next_standardized_reset_time

    now = datetime(2026, 11, 3, 23, 0, tzinfo=timezone.utc)
    utc = get_next_standardized_reset_time(duration="1mo", current_time=now, timezone_str="UTC")
    assert utc.astimezone(timezone.utc) == datetime(2026, 12, 1, 0, 0, tzinfo=timezone.utc)
    assert keys.next_reset(now) - utc.astimezone(timezone.utc) == timedelta(hours=5)


def test_the_config_holds_what_the_drills_rely_on():
    settings, general = CONFIG["litellm_settings"], CONFIG["general_settings"]
    assert settings["timezone"] == "America/Toronto"
    assert settings["budget_exceeded_status_code"] == 422
    assert settings["callbacks"] == ["key_binding.hooks", "ch05_callback.hooks"]  # the key first, then chapter 5
    assert general["alerting"] == ["webhook"] and general["alert_types"] == ["budget_alerts"]
    assert general["master_key"] == "os.environ/LITELLM_MASTER_KEY"
    assert general["database_url"] == "os.environ/DATABASE_URL"
    for entry in CONFIG["model_list"]:
        assert entry["litellm_params"]["api_base"].startswith("os.environ/")


def test_the_aliases_serve_where_chapter_5s_do_at_its_stand_in_prices():
    ours = {e["model_name"]: e for e in CONFIG["model_list"]}
    theirs = {e["model_name"]: e for e in CH05_CONFIG["model_list"]}
    for alias, entry in ours.items():
        assert entry["model_info"] == theirs[alias]["model_info"]
        for price in ("input_cost_per_token", "output_cost_per_token"):
            assert entry["litellm_params"][price] == theirs[alias]["litellm_params"][price]


def test_the_month_is_torontos_calendar():
    assert keys.month_of(datetime(2026, 12, 1, 4, 30, tzinfo=timezone.utc)) == "2026-11"
    assert keys.month_of(datetime(2026, 12, 1, 5, 0, tzinfo=timezone.utc)) == "2026-12"
