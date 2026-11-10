"""The model register and the cost sheet: pinned models stay processed in Canada and away from retirement.

Chapter 7. The retirement test reads today's date on purpose: it starts failing 90 days before a
pinned model retires, which is when the platform's register says to move.
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path

import yaml

LAB = Path(__file__).resolve().parent.parent
REGISTER = yaml.safe_load((LAB / "models.yaml").read_text(encoding="utf-8"))
SHEET = yaml.safe_load((LAB / "cost" / "cost-sheet.yaml").read_text(encoding="utf-8"))


def pinned_models() -> set[str]:
    text = (LAB / "terraform" / "runtime.tf").read_text(encoding="utf-8")
    return set(re.findall(r'"\$\{local\.models\}/([a-z0-9.\-]+)"', text))


def test_every_pinned_model_is_in_the_register_and_processed_in_canada() -> None:
    models = pinned_models()
    assert models == {"gemini-3.5-flash", "text-multilingual-embedding-002"}
    for model in models:
        assert REGISTER[model]["processed_in_canada"] is True, model


def test_no_pinned_model_retires_within_90_days() -> None:
    today = datetime.date.today()
    for model in pinned_models():
        entry = REGISTER[model]
        retires = entry.get("retires") or entry["retires_no_earlier_than"]
        assert (retires - today).days > 90, f"{model} retires on {retires}: move it before pinning again"


def test_the_cost_sheet_is_dated_and_names_what_is_billed() -> None:
    assert SHEET["fetched"] == datetime.date(2026, 10, 29)
    assert "idle time" in SHEET["agent_runtime"]["billing"]
    assert "15,000" in SHEET["agent_gateway_agent_to_anywhere"]["unit"]
    assert SHEET["memory_bank"]["storage_includes"] == "revisions"
