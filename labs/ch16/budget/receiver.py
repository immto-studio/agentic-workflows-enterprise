"""A local receiver for LiteLLM's budget webhook, standing in for the owner's and FinOps's channels.

Chapter 16, step 4 (companion #14, O-D7). The alarm at 80 percent of the monthly figure goes "to the owner
and to Ingrid's team" (ch02:144). LiteLLM's MIT core sends budget alerts to Slack, Teams, Discord or a
webhook, and email needs the license (fact sheet 8.1), so the gateway POSTs its webhook event to this
receiver, which forwards it. Here the forwarding is a line in an outbox per alert, naming the two
recipients: the owner from the manifest of the workflow the key belongs to (the key's alias), and FinOps.
In production the receiver would post to the owner's team channel and FinOps's queue, which the lab
doesn't have. It keeps everything LiteLLM sent; an alert for a key no manifest names goes to FinOps alone.

Step 5b adds the platform's alerts: the gateway's own callback (`capacity/store_hooks.py`) POSTs
`limiter_store_unreachable` when the store LiteLLM's limiter counts in stops answering, and
`limiter_store_reachable` when it answers again. They go to the platform's on-call, whom chapter 5 pages "when
the gateway itself fails" (ch05:498), and to no workflow's owner.

Run:  python budget/receiver.py --port 8899 --outbox budget/_lab/alerts.jsonl
Binds 127.0.0.1 only. GET /alerts lists what arrived.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

HERE = Path(__file__).resolve().parent
FINOPS = "finops@larkspur.example"  # Ingrid Holm's team
PLATFORM_ONCALL = "platform.oncall@larkspur.example"  # paged when the gateway itself fails (ch05:498)
HOST = "127.0.0.1"


def load_owners(folder: Path) -> dict[str, str]:
    import yaml

    owners = {}
    for path in sorted(Path(folder).glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, Mapping) and "workflow" in data and "owner" in data:
            owners[data["workflow"]] = data["owner"]
    return owners


KINDS = {"soft_budget_crossed": "the soft budget reached", "threshold_crossed": "15 or 5 percent of the budget left",
         "budget_crossed": "the budget reached"}
PLATFORM = {"limiter_store_unreachable": "the limiter's store unreachable",
            "limiter_store_reachable": "the limiter's store answering again"}


def kind_of(event: Mapping[str, Any]) -> str:
    """What the alert says, in words. LiteLLM 1.106.6 also sends a projection after a priced call when the month's
    pace passes the soft budget; it fills `max_budget` with the soft budget, so its event reads `threshold_crossed`
    or `budget_crossed` against the soft budget. Its `projected_spend` gives it away."""
    if event.get("projected_spend") is not None:
        return "the month's pace projected past the soft budget"
    name = str(event.get("event"))
    return PLATFORM.get(name) or KINDS.get(name, name)


def forward(event: Mapping[str, Any], owners: Mapping[str, str], received_at: datetime) -> dict[str, Any]:
    """The outbox line for one alert: what was said, what it means, and who it goes to."""
    alias = event.get("key_alias")
    if event.get("event") in PLATFORM:
        recipients = [PLATFORM_ONCALL]
    else:
        recipients = [owners[alias], FINOPS] if alias in owners else [FINOPS]
    return {"received_at": received_at.isoformat(timespec="milliseconds"), "event": event.get("event"),
            "kind": kind_of(event), "key_alias": alias, "spend": event.get("spend"),
            "max_budget": event.get("max_budget"), "soft_budget": event.get("soft_budget"),
            "projected_spend": event.get("projected_spend"), "event_group": event.get("event_group"),
            "event_message": event.get("event_message"), "forwarded_to": recipients, "sent": dict(event)}


def build_app(outbox: Path, owners: Mapping[str, str]) -> Starlette:
    lock = threading.Lock()

    async def alert(request: Request) -> JSONResponse:
        try:
            event = await request.json()
        except ValueError:
            return JSONResponse({"error": "not JSON"}, status_code=400)
        if not isinstance(event, dict):
            return JSONResponse({"error": "not an object"}, status_code=400)
        line = forward(event, owners, datetime.now(timezone.utc))
        with lock, Path(outbox).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(line) + "\n")
        return JSONResponse({"ok": True, "forwarded_to": line["forwarded_to"]})

    async def alerts(request: Request) -> JSONResponse:
        path = Path(outbox)
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        return JSONResponse([json.loads(line) for line in lines if line.strip()])

    return Starlette(routes=[Route("/budget-alert", alert, methods=["POST"]),
                             Route("/alerts", alerts, methods=["GET"]),
                             Route("/health", lambda r: JSONResponse({"ok": True}), methods=["GET"])])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--outbox", type=Path, default=HERE / "_lab" / "alerts.jsonl")
    parser.add_argument("--manifest-dir", type=Path, default=HERE.parents[1] / "ch05" / "manifest")
    args = parser.parse_args(argv)
    args.outbox.parent.mkdir(parents=True, exist_ok=True)
    uvicorn.run(build_app(args.outbox, load_owners(args.manifest_dir)), host=HOST, port=args.port,
                log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
