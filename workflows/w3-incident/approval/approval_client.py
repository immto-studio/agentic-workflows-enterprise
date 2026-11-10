"""The approval service's client: what the harness (triage.py's `Approvals`) and the write tools call.

The harness files a request and asks for the decision; a write tool asks whether a recorded yes covers
exactly its call in this run and marks the approval applied. Both carry the service's key; a person's
decision never goes through this client, it arrives from the bot with the person's own token.
"""

from __future__ import annotations

from typing import Any

import httpx


class ApprovalClient:
    def __init__(self, url: str, key: str, *, workflow: str = "w3-incident", requester_upn: str = "",
                 timeout_s: float = 10.0, client: httpx.Client | None = None) -> None:
        self.url = url.rstrip("/")
        self.workflow, self.requester_upn = workflow, requester_upn
        self.client = client or httpx.Client(timeout=timeout_s)
        self.headers = {"Authorization": f"Bearer {key}"}

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        response = self.client.post(f"{self.url}{path}", json=body, headers=self.headers)
        if response.status_code >= 400:
            raise RuntimeError(f"approval service {response.status_code}: {response.json().get('error', response.text)}")
        return response.json()

    # --- the harness's side (triage.Approvals) ----------------------------------------------------

    def request(self, trace_id: str, call: dict[str, Any], requester: str) -> str:
        record = self._post("/requests", {"workflow": self.workflow, "trace_id": trace_id, "tool": call["name"],
                                          "args": call["args"], "service": call["args"].get("service", ""),
                                          "requester_oid": requester, "requester_upn": self.requester_upn})
        return record["approval_id"]

    def get(self, approval_id: str) -> dict[str, Any]:
        response = self.client.get(f"{self.url}/requests/{approval_id}", headers=self.headers)
        if response.status_code >= 400:
            raise RuntimeError(f"approval service {response.status_code}: {response.json().get('error', response.text)}")
        return response.json()

    def decision(self, approval_id: str) -> dict[str, Any] | None:
        record = self.get(approval_id)
        if record["status"] == "approved":
            return {"approved": True, "by": ",".join(record["approved_by"]), "reason": ""}
        if record["status"] == "declined":
            last = [d for d in record["decisions"] if d["accepted"] and d["approved"] is False][-1]
            return {"approved": False, "by": last["oid"], "reason": last["reason"]}
        return None

    def expired(self, approval_id: str) -> bool:
        return self.get(approval_id)["status"] == "expired"

    # --- the write tool's side ----------------------------------------------------------------------

    def check(self, approval_id: str, *, tool: str, args: dict[str, Any], trace_id: str) -> dict[str, Any]:
        return self._post(f"/requests/{approval_id}/check", {"tool": tool, "args": args, "trace_id": trace_id})

    def applied(self, approval_id: str) -> dict[str, Any]:
        return self._post(f"/requests/{approval_id}/applied", {})
