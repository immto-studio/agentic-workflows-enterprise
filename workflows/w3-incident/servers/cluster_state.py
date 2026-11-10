"""The fake cluster's writable state: what the writer changes and the verification read sees.

Chapter 12, W3-D4, W3-D8. Chapter 5's fake namespace is a constant; W2 reads it as deployed. W3's two
writes change it, so the changes live in one JSON file (`CLUSTER_STATE_FILE`) that the writer updates
and W2's Kubernetes fake reads back for `get_pod_status`. The rules are deterministic, so every run of
the golden set gives the same verification:

- a restart rolls the pods: every pod comes back Running with zero restarts, and the deployment is
  healthy again, unless the service is one whose fault a restart does not fix (`document-ocr`, whose
  Pending pod is a scheduling constraint, as its alert's annotation says); a restart bumps the
  deployment's generation and records `restartedAt`, as `kubectl rollout restart` does through the
  pod template's annotation (the fact sheet, B.1 and B.2);
- a scale sets the desired count and brings up as many pods as the service's capacity allows
  (`fraud-scoring` has capacity for four), so a scale past capacity leaves ready below desired and
  the verification fails, which is the rollback's case; a scale creates no revision (B.2).

Nothing here is Kubernetes; in production the writer patches the Deployment and the verification reads
its status fields and conditions (B.5).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CH05_SERVER = Path(__file__).resolve().parents[3] / "labs" / "ch05" / "mcp-server"
if str(CH05_SERVER) not in sys.path:
    sys.path.insert(0, str(CH05_SERVER))
from fake_platform import DEPLOYMENTS, UnknownService  # noqa: E402

HEALS_ON_RESTART: dict[str, bool] = {"document-ocr": False}  # every other service heals
CAPACITY: dict[str, int] = {"fraud-scoring": 4}  # pods the service can run; every other service, ten
DEFAULT_CAPACITY = 10
MIN_REPLICAS, MAX_REPLICAS = 1, 8  # the bounds the catalog gives scale_deployment


def state_path() -> Path | None:
    path = os.environ.get("CLUSTER_STATE_FILE", "").strip()
    return Path(path) if path else None


class ClusterState:
    """The overrides for the deployed namespace, in one file, written whole on every change."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, data: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=self.path.name, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=1, sort_keys=True)
        os.replace(tmp, self.path)

    def current(self, service: str) -> dict[str, Any]:
        """The deployment as the cluster now has it: the deployed constants under the recorded changes."""
        base = DEPLOYMENTS.get(service)
        if base is None:
            raise UnknownService(f"no deployment named {service!r}")
        view = {"desired": base["desired"], "ready": base["ready"], "image": base["image"],
                "pods": [dict(p) for p in base["pods"]], "generation": 1, "restartedAt": None}
        view.update(self.load().get(service, {}))
        return view

    # --- the two writes -------------------------------------------------------------------------

    def restart(self, service: str, at: datetime | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        """Roll the pods. Returns (previous, applied): the generation and restartedAt before, and after."""
        before = self.current(service)
        stamp = (at or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
        generation = before["generation"] + 1
        heals = HEALS_ON_RESTART.get(service, True)
        pods = []
        for index, pod in enumerate(before["pods"]):
            name = f"{service}-{generation:x}{index:04x}-{pod['name'].rsplit('-', 1)[-1]}"
            phase = "Running" if heals or index < before["desired"] - 1 else "Pending"
            pods.append({"name": name, "phase": phase, "restarts": 0})
        ready = before["desired"] if heals else before["desired"] - 1
        after = {**before, "generation": generation, "restartedAt": stamp, "pods": pods, "ready": ready}
        data = self.load()
        data[service] = after
        self.save(data)
        previous = {"generation": before["generation"], "restartedAt": before["restartedAt"], "ready": before["ready"]}
        applied = {"generation": generation, "restartedAt": stamp, "ready": ready, "desired": after["desired"]}
        return previous, applied

    def scale(self, service: str, replicas: int) -> tuple[dict[str, Any], dict[str, Any]]:
        """Set the desired count. Returns (previous, applied); ready is what the capacity allows."""
        if not isinstance(replicas, int) or isinstance(replicas, bool) or not MIN_REPLICAS <= replicas <= MAX_REPLICAS:
            raise ValueError(f"replicas must be between {MIN_REPLICAS} and {MAX_REPLICAS}, got {replicas!r}")
        before = self.current(service)
        capacity = CAPACITY.get(service, DEFAULT_CAPACITY)
        ready = min(replicas, capacity)
        suffixes = [p["name"].rsplit("-", 1)[-1] for p in before["pods"]]
        pods = []
        for index in range(replicas):
            suffix = suffixes[index] if index < len(suffixes) else f"n{index:04x}"
            pods.append({"name": f"{service}-{before['generation']:x}{index:04x}-{suffix}",
                         "phase": "Running" if index < ready else "Pending", "restarts": 0})
        after = {**before, "desired": replicas, "ready": ready, "pods": pods}
        data = self.load()
        data[service] = after
        self.save(data)
        previous = {"replicas": before["desired"], "ready": before["ready"]}
        applied = {"replicas": replicas, "ready": ready, "capacity": capacity}
        return previous, applied
