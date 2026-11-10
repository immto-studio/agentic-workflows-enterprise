"""A fallback inside the jurisdiction for a request whose fallback chapter 5's rules turn off.

Chapter 16, step 5b (companion #14, O-D10). Chapter 5's callback checks every hop of an alias's fallback chain against
chapter 2's grid and the workflow's Regions, and when any hop fails it turns the request's fallback off altogether
(`gateway_rules.decide`). W3's Confidential calls ask for larkspur-chat, whose one hop is the same family in
us-east-2, outside W3's one Region, so in step 5's outage drill W3 got the primary's error and then the cooldown's
429. The grid lets a Confidential call reach the self-hosted model in Canada (`gateway_rules.may_receive`:
"confidential" needs the jurisdiction and a hosted deployment, managed or self-hosted).

So chapter 16's outage config names, per alias, a fallback inside the jurisdiction, in a section of its own that
LiteLLM doesn't read (`larkspur_fallbacks_in_jurisdiction`), and this callback, registered after chapter 5's, gives
a request that fallback when chapter 5 has turned the request's fallback off and the request may reach the named
alias by the same rules (`gateway_rules._blocked`: the grid for every deployment behind it, and every Region it
serves from inside the manifest's). The request then fails over to that alias and to nothing else, through
LiteLLM's per-request `fallbacks`. Any request chapter 5 left alone keeps the chain chapter 5 checked, so W2's
calls still fail over to us-east-2, and a Restricted call, whose alias has no chain, has none. Chapter 5's
`fallback_disabled` line stays as chapter 5 writes it; this callback writes a `fallback_in_jurisdiction` line after
it, to the same log, and marks the request's metadata, so the cost line no longer says its fallback was disabled.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from litellm.integrations.custom_logger import CustomLogger

HERE = Path(__file__).resolve().parent
CH05 = HERE.parents[1] / "ch05"
for folder in (CH05 / "gateway", CH05 / "manifest"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import gateway_rules as rules  # noqa: E402  (chapter 5's rules, unchanged)
import manifest as manifests  # noqa: E402

SECTION = "larkspur_fallbacks_in_jurisdiction"


def read_section(path: Path) -> dict[str, list[str]]:
    """alias -> the aliases a request that may not take the alias's own chain falls back to, in order."""
    config = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return {str(alias): [str(t) for t in targets] for alias, targets in (config.get(SECTION) or {}).items()}


def hops_for(alias: str, tags: Mapping[str, str], known: Mapping[str, Mapping[str, Any]],
             destinations: Mapping[str, list[rules.Destination]], inside: Mapping[str, list[str]]) -> list[str]:
    """The named fallbacks this request may take: those the grid and its manifest's Regions allow."""
    manifest = known.get(tags.get("workflow", ""))
    if manifest is None or tags.get("data_class") is None:
        return []
    return [hop for hop in inside.get(alias, []) if rules._blocked(hop, tags["data_class"], manifest, destinations) is None]


class InJurisdiction(CustomLogger):
    def __init__(self) -> None:
        super().__init__()
        config = Path(os.environ.get("GATEWAY_CONFIG") or HERE / "litellm.outage-canada.yaml")
        self.log = Path(os.environ.get("GATEWAY_LOG_FILE") or HERE / "_lab" / "gateway.log")
        self.known = manifests.load_manifests(Path(os.environ.get("MANIFEST_DIR") or CH05 / "manifest"))
        self.destinations, _ = rules.read_config(config)
        self.inside = read_section(config)

    def line(self, **fields: Any) -> None:
        record = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), **fields}
        with self.log.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record) + "\n")

    async def async_pre_call_hook(self, user_api_key_dict: Any, cache: Any, data: dict, call_type: Any) -> dict:
        if data.get("disable_fallbacks") is not True:
            return data  # chapter 5 left the request's chain on, or never got to decide
        metadata = data.get("metadata") or {}
        tags = rules.parse_tags(metadata)
        alias = data.get("model", "")
        hops = hops_for(alias, tags, self.known, self.destinations, self.inside)
        if not hops:
            return data
        data["fallbacks"] = [{alias: hops}]
        data["disable_fallbacks"] = False
        metadata["fallbacks_disabled"] = False
        metadata["fallback_in_jurisdiction"] = hops
        data["metadata"] = metadata
        self.line(event="fallback_in_jurisdiction", alias=alias, trace_id=metadata.get("trace_id"), tags=tags,
                  fallbacks=hops)
        return data


hooks = InJurisdiction()
