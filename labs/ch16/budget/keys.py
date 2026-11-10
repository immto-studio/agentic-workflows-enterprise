"""A virtual key per workflow, made from its manifest, and the slice of LiteLLM's admin API the lab uses.

Chapter 16, step 4 (companion #14, O-D7). The monthly budget lives on the workflow's key in LiteLLM's
database, all of it in the MIT core (fact sheet 8.1):

- `key_alias` is the workflow's name, and `metadata` names the workflow, its owner and sponsor, and its
  maximum data class. Key tags would be the natural place, and they need the enterprise license.
- `max_budget` is the manifest's `per_month_usd`, and `soft_budget` 80 percent of it: LiteLLM sends the
  webhook alert `soft_budget_crossed` once the key's spend reaches it, and answers 422 once the spend
  reaches `max_budget`.
- `budget_duration` is `1mo`, which LiteLLM resets at midnight on the 1st in `litellm_settings.timezone`,
  America/Toronto in this step's config. Without it the reset comes at midnight UTC, five hours early in
  Toronto's winter and four in its summer.
- `models` is the manifest's aliases, so the key can't reach another model even before chapter 5's
  callback looks at it.

The admin calls take the master key and the key's hashed token, which `/key/list` gives by alias, so the
on-call lead never needs the workflow's key itself, which stays in the vault.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

SOFT_SHARE = 0.8
DURATION = "1mo"
ZONE = "America/Toronto"


def key_request(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """The body of `/key/generate` for one workflow."""
    budget = manifest["budget"]
    return {
        "key_alias": manifest["workflow"],
        "models": list(manifest["models"]),
        "max_budget": float(budget["per_month_usd"]),
        "soft_budget": round(float(budget["per_month_usd"]) * SOFT_SHARE, 6),
        "budget_duration": DURATION,
        "metadata": {"workflow": manifest["workflow"], "owner": manifest["owner"],
                     "sponsor": manifest["sponsor"], "data_class_max": manifest["data_class_max"]},
    }


def next_reset(now: datetime, zone: str = ZONE) -> datetime:
    """Midnight on the 1st of the next month in `zone`, in UTC: when a 1mo budget should next reset."""
    local = now.astimezone(ZoneInfo(zone))
    year, month = (local.year + 1, 1) if local.month == 12 else (local.year, local.month + 1)
    return datetime(year, month, 1, tzinfo=ZoneInfo(zone)).astimezone(timezone.utc)


def month_of(now: datetime, zone: str = ZONE) -> str:
    """The budget month a moment falls in, by the zone's calendar."""
    return now.astimezone(ZoneInfo(zone)).strftime("%Y-%m")


class AdminError(RuntimeError):
    def __init__(self, path: str, status: int, text: str) -> None:
        super().__init__(f"{path} answered {status}: {text[:300]}")
        self.path, self.status, self.text = path, status, text


@dataclass
class Admin:
    """LiteLLM's management endpoints, called with the master key."""

    url: str
    master_key: str
    client: httpx.Client = field(default_factory=lambda: httpx.Client(timeout=30))

    def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        r = self.client.request(method, f"{self.url}{path}", headers={"Authorization": f"Bearer {self.master_key}"},
                                **kwargs)
        if r.status_code != 200:
            raise AdminError(path, r.status_code, r.text)
        return r.json()

    def generate(self, manifest: Mapping[str, Any]) -> dict[str, Any]:
        return self._call("POST", "/key/generate", json=key_request(manifest))

    def token_for(self, alias: str) -> str:
        """The hashed token of the key whose alias is exactly `alias`."""
        body = self._call("GET", "/key/list", params={"key_alias": alias, "return_full_object": "true"})
        keys = [k for k in body.get("keys", []) if isinstance(k, dict) and k.get("key_alias") == alias]
        if len(keys) != 1:
            raise LookupError(f"{len(keys)} keys have the alias {alias!r}")
        return keys[0]["token"]

    def info(self, token: str) -> dict[str, Any]:
        return self._call("GET", "/key/info", params={"key": token})["info"]

    def update(self, token: str, **fields: Any) -> dict[str, Any]:
        return self._call("POST", "/key/update", json={"key": token, **fields})

    def block(self, token: str) -> dict[str, Any]:
        return self._call("POST", "/key/block", json={"key": token})

    def unblock(self, token: str) -> dict[str, Any]:
        return self._call("POST", "/key/unblock", json={"key": token})


def provision(admin: Admin, manifests: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """One key per workflow; returns workflow -> {key, token}. The key goes to the workflow's vault."""
    made = {}
    for workflow, manifest in manifests.items():
        body = admin.generate(manifest)
        made[workflow] = {"key": body["key"], "token": body.get("token") or admin.token_for(workflow)}
    return made
