"""The key must agree with the tags: a LiteLLM callback that binds each request to its workflow's key.

Chapter 16, step 4. Chapter 5's callback decides on what a request says about itself, and behind one master
key any caller can write any `workflow:` tag. Chapter 5 says how Larkspur closes it: "Each workflow gets its
own LiteLLM virtual key, which needs the database but no enterprise license, and the key's metadata names
the workflow and its maximum data class; the callback refuses tags that disagree with the key" (ch05:164).
With the database running, this is that check, in a callback of this step's own, registered before chapter
5's, which stays unchanged. It refuses a model call, with chapter 5's 400 and wording,

- through a key whose metadata names no workflow, the master key among them, so a call is always charged to
  some workflow's budget;
- whose `workflow:` tag names another workflow than the key, so a workflow can't spend another's budget, and
  a workflow whose key is blocked can't borrow another's tag;
- whose `data_class:` tag is above the key's `data_class_max`.

A missing tag is chapter 5's to refuse. Refusals go to the gateway's log beside chapter 5's lines.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from litellm.integrations.custom_logger import CustomLogger

HERE = Path(__file__).resolve().parent
DATA_CLASSES = ("public", "internal", "confidential", "restricted")  # chapter 5's order, least to most


def parse_tags(metadata: Mapping[str, Any]) -> dict[str, str]:
    """Chapter 5's reading of `tags: ["workflow:w2", ...]`."""
    out: dict[str, str] = {}
    for tag in metadata.get("tags") or []:
        if isinstance(tag, str) and ":" in tag:
            key, value = tag.split(":", 1)
            out[key] = value
    return out


def decide(key_metadata: Mapping[str, Any] | None, tags: Mapping[str, str]) -> str | None:
    """Why the request may not use this key, or None."""
    workflow = (key_metadata or {}).get("workflow")
    if not workflow:
        return "request refused: the key names no workflow; model calls go through a workflow's own key"
    asked = tags.get("workflow")
    if asked is not None and asked != workflow:
        return f"request refused: the key is {workflow!r}'s, and the request says it is {asked!r}"
    ceiling = (key_metadata or {}).get("data_class_max")
    data_class = tags.get("data_class")
    if ceiling in DATA_CLASSES and data_class in DATA_CLASSES and \
            DATA_CLASSES.index(data_class) > DATA_CLASSES.index(ceiling):
        return f"request refused: data class {data_class!r} is above the key's maximum ({ceiling!r})"
    return None


def _log(**fields: Any) -> None:
    path = Path(os.environ.get("GATEWAY_LOG_FILE") or HERE / "_lab" / "gateway.log")
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), **fields}
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(line) + "\n")


class KeyBinding(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict: Any, cache: Any, data: dict,
                                  call_type: str) -> dict | None:
        metadata = data.get("metadata") or {}
        tags = parse_tags(metadata)
        refused = decide(getattr(user_api_key_dict, "metadata", None), tags)
        if refused:
            _log(event="refused", alias=data.get("model"), trace_id=metadata.get("trace_id"), tags=tags,
                 key_alias=getattr(user_api_key_dict, "key_alias", None), reason=refused)
            raise HTTPException(status_code=400, detail=refused)
        return data


hooks = KeyBinding()
