"""The gateway puts the trace id and the workflow into Bedrock's requestMetadata (O-D2, amended).

Chapter 2 makes the trace id the center of the observability design, and O-D2 gives the gateway the job of
passing `trace_id` and `workflow` in Bedrock's `requestMetadata`, which the model invocation log records and the
bill never shows (fact sheet 8.2). This is that change, as a LiteLLM callback of this step's own, registered ahead
of chapter 5's, which stays unchanged. It reads the request's `metadata.trace_id` and its `workflow:` tag the way
chapter 5 reads them and writes the two pairs as the request's `requestMetadata`, in place of whatever the caller
sent under that key, so the gateway owns the two names (AWS: "set request metadata in a shared client or LLM
gateway"). LiteLLM 1.106.6 checks the pairs against Bedrock's limits and writes them into the Converse body; on a
deployment that isn't Bedrock, `drop_params` drops the key. tests/test_cloud_scripts.py drives both offline.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from litellm.integrations.custom_logger import CustomLogger

TRACE_ID = re.compile(r"^[0-9a-f]{32}$")
VALUE = re.compile(r"^[a-zA-Z0-9\s:_@$#=/+,.-]{1,256}$")  # Bedrock's pattern for a requestMetadata value
KEYS = ("trace_id", "workflow")


def parse_tags(metadata: Mapping[str, Any]) -> dict[str, str]:
    """Chapter 5's reading of `tags: ["workflow:w2", ...]`."""
    out: dict[str, str] = {}
    for tag in metadata.get("tags") or []:
        if isinstance(tag, str) and ":" in tag:
            key, value = tag.split(":", 1)
            out[key] = value
    return out


def request_metadata(data: Mapping[str, Any]) -> dict[str, str] | None:
    """The pairs the gateway sends, or None when the request names neither a trace id nor a workflow."""
    metadata = data.get("metadata") or {}
    pairs: dict[str, str] = {}
    trace_id = metadata.get("trace_id")
    if isinstance(trace_id, str) and TRACE_ID.match(trace_id):
        pairs["trace_id"] = trace_id
    workflow = parse_tags(metadata).get("workflow")
    if isinstance(workflow, str) and VALUE.match(workflow):
        pairs["workflow"] = workflow
    return pairs or None


class RequestMetadataHooks(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict: Any, cache: Any, data: dict,
                                  call_type: str) -> dict | None:
        data.pop("requestMetadata", None)  # the gateway owns the field; a caller's own pairs don't reach Bedrock
        pairs = request_metadata(data)
        if pairs:
            data["requestMetadata"] = pairs
        return data


hooks = RequestMetadataHooks()
