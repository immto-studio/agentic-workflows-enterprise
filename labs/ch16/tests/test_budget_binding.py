"""The key must agree with the tags (ch05:164): the callback of this step's own, before chapter 5's.

The decision is a pure function; the callback is driven with a stand-in for LiteLLM's `UserAPIKeyAuth`, which
carries the key's metadata and alias. The drills run the same refusals through the real proxy.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import key_binding
import pytest
from fastapi import HTTPException

W2_KEY = {"workflow": "w2-ops-assistant", "owner": "sam.okafor@larkspur.example", "data_class_max": "internal"}


@pytest.mark.parametrize("key, tags, refused", [
    (W2_KEY, {"workflow": "w2-ops-assistant", "data_class": "internal"}, None),
    (W2_KEY, {"workflow": "w2-ops-assistant", "data_class": "public"}, None),
    (W2_KEY, {"workflow": "w3-incident", "data_class": "internal"}, "the request says it is 'w3-incident'"),
    (W2_KEY, {"workflow": "w2-ops-assistant", "data_class": "confidential"}, "above the key's maximum"),
    ({}, {"workflow": "w2-ops-assistant", "data_class": "internal"}, "names no workflow"),
    (None, {"workflow": "w2-ops-assistant", "data_class": "internal"}, "names no workflow"),
    # a missing or unknown tag is chapter 5's to refuse, with its own reason
    (W2_KEY, {"data_class": "internal"}, None),
    (W2_KEY, {"workflow": "w2-ops-assistant", "data_class": "secret"}, None),
])
def test_the_key_and_the_tags_must_agree(key, tags, refused):
    reason = key_binding.decide(key, tags)
    if refused is None:
        assert reason is None
    else:
        assert reason.startswith("request refused: ") and refused in reason


def test_the_callback_refuses_with_chapter_5s_status_and_logs_the_refusal(tmp_path, monkeypatch):
    log = tmp_path / "gateway.log"
    monkeypatch.setenv("GATEWAY_LOG_FILE", str(log))
    key = SimpleNamespace(metadata=W2_KEY, key_alias="w2-ops-assistant")
    data = {"model": "larkspur-chat", "metadata": {"tags": ["workflow:w3-incident", "data_class:internal"],
                                                   "trace_id": "0af7651916cd43dd8448eb211c80319c"}}
    with pytest.raises(HTTPException) as refused:
        asyncio.run(key_binding.hooks.async_pre_call_hook(key, None, data, "acompletion"))
    assert refused.value.status_code == 400
    line = json.loads(log.read_text(encoding="utf-8"))
    assert line["event"] == "refused" and line["key_alias"] == "w2-ops-assistant"
    assert line["trace_id"] == "0af7651916cd43dd8448eb211c80319c"
    # chapter 5's failure hook skips its own pre-call refusals by this phrase, so none is logged twice
    assert "request refused" in refused.value.detail


def test_an_agreeing_request_passes_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv("GATEWAY_LOG_FILE", str(tmp_path / "gateway.log"))
    key = SimpleNamespace(metadata=W2_KEY, key_alias="w2-ops-assistant")
    data = {"model": "larkspur-chat", "metadata": {"tags": ["workflow:w2-ops-assistant", "data_class:internal"]}}
    assert asyncio.run(key_binding.hooks.async_pre_call_hook(key, None, dict(data), "acompletion")) == data
    assert not (tmp_path / "gateway.log").exists()


def test_the_tags_are_read_as_chapter_5_reads_them():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ch05" / "gateway"))
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ch05" / "manifest"))
    from gateway_rules import parse_tags

    metadata = {"tags": ["workflow:w2-ops-assistant", "data_class:internal", "owner:platform-team", "loose", 7]}
    assert key_binding.parse_tags(metadata) == parse_tags(metadata)
