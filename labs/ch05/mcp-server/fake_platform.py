"""An in-memory fake of one Kubernetes namespace and its alert store.

Everything here is synthetic. The services are the Larkspur Mutual platform as the book
describes it; the numbers are chosen so that the lab output is stable from run to run.
Nothing talks to a real cluster, which is the point of running this lab first.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

NAMESPACE = "larkspur-prod"


# The result types. The MCP server derives each tool's `outputSchema` from them, so a client can
# check a result against a schema with named, typed fields instead of an open object.
class Pod(TypedDict):
    name: str
    phase: str
    restarts: int


class PodStatus(TypedDict):
    service: str
    namespace: str
    ready: int
    desired: int
    image: str
    pods: list[Pod]


class Alert(TypedDict):
    service: str
    severity: Literal["critical", "warning", "info"]
    age_minutes: int
    source: str
    summary: str


class AlertList(TypedDict):
    service: str
    window_minutes: int
    count: int
    alerts: list[Alert]

# service -> deployment state. `ready` below `desired` is the interesting case.
DEPLOYMENTS: dict[str, dict[str, Any]] = {
    "claims-api": {
        "desired": 3, "ready": 2, "image": "claims-api:2.14.1",
        "pods": [
            {"name": "claims-api-7d9f8b6c4-2xk9p", "phase": "Running", "restarts": 0},
            {"name": "claims-api-7d9f8b6c4-m4q7z", "phase": "Running", "restarts": 1},
            {"name": "claims-api-7d9f8b6c4-t8w2c", "phase": "CrashLoopBackOff", "restarts": 7},
        ],
    },
    "policy-admin": {
        "desired": 2, "ready": 2, "image": "policy-admin:5.3.0",
        "pods": [
            {"name": "policy-admin-5c6d7e8f9-a1b2c", "phase": "Running", "restarts": 0},
            {"name": "policy-admin-5c6d7e8f9-d3e4f", "phase": "Running", "restarts": 0},
        ],
    },
    "billing-worker": {
        "desired": 4, "ready": 4, "image": "billing-worker:1.9.2",
        "pods": [
            {"name": f"billing-worker-6f7a8b9c0-{s}", "phase": "Running", "restarts": 0}
            for s in ("h5j6k", "l7m8n", "p9q0r", "s1t2u")
        ],
    },
    "quote-engine": {
        "desired": 3, "ready": 3, "image": "quote-engine:3.1.4",
        "pods": [
            {"name": f"quote-engine-8a9b0c1d2-{s}", "phase": "Running", "restarts": 0}
            for s in ("v3w4x", "y5z6a", "b7c8d")
        ],
    },
    "document-ocr": {
        "desired": 2, "ready": 1, "image": "document-ocr:0.8.0",
        "pods": [
            {"name": "document-ocr-9e0f1a2b3-e9f0g", "phase": "Running", "restarts": 0},
            {"name": "document-ocr-9e0f1a2b3-h1i2j", "phase": "Pending", "restarts": 0},
        ],
    },
    "fraud-scoring": {
        "desired": 2, "ready": 2, "image": "fraud-scoring:4.0.1",
        "pods": [
            {"name": "fraud-scoring-1b2c3d4e5-k3l4m", "phase": "Running", "restarts": 0},
            {"name": "fraud-scoring-1b2c3d4e5-n5o6p", "phase": "Running", "restarts": 2},
        ],
    },
    "customer-portal": {
        "desired": 3, "ready": 3, "image": "customer-portal:7.2.0",
        "pods": [
            {"name": f"customer-portal-2c3d4e5f6-{s}", "phase": "Running", "restarts": 0}
            for s in ("q7r8s", "t9u0v", "w1x2y")
        ],
    },
    "notification-gateway": {
        "desired": 2, "ready": 2, "image": "notification-gateway:2.0.3",
        "pods": [
            {"name": "notification-gateway-3d4e5f6a7-z3a4b", "phase": "Running", "restarts": 0},
            {"name": "notification-gateway-3d4e5f6a7-c5d6e", "phase": "Running", "restarts": 0},
        ],
    },
}

# Alerts keep an age in minutes instead of a timestamp so the output never depends on the clock.
ALERTS: list[dict[str, Any]] = [
    {"service": "claims-api", "severity": "critical", "age_minutes": 4, "source": "prometheus",
     "summary": "KubePodCrashLooping: claims-api-7d9f8b6c4-t8w2c restarted 7 times in 30m"},
    {"service": "claims-api", "severity": "warning", "age_minutes": 12, "source": "prometheus",
     "summary": "HighErrorRate: 5xx ratio 3.8% over 5m (threshold 1%)"},
    {"service": "claims-api", "severity": "warning", "age_minutes": 95, "source": "grafana",
     "summary": "p95 latency 1.9s over 10m (threshold 1.2s)"},
    {"service": "document-ocr", "severity": "warning", "age_minutes": 18, "source": "prometheus",
     "summary": "KubePodNotReady: document-ocr-9e0f1a2b3-h1i2j Pending for 15m (insufficient GPU)"},
    {"service": "fraud-scoring", "severity": "info", "age_minutes": 41, "source": "prometheus",
     "summary": "Container restarted (OOMKilled), recovered"},
    {"service": "billing-worker", "severity": "warning", "age_minutes": 380, "source": "grafana",
     "summary": "Queue depth above 10k for 20m (nightly batch, resolved)"},
]

MAX_WINDOW_MINUTES = 24 * 60


class UnknownService(ValueError):
    pass


def pod_status(service: str) -> PodStatus:
    """Ready and desired pod counts for one deployment, plus the pods themselves."""
    deployment = DEPLOYMENTS.get(service)
    if deployment is None:
        raise UnknownService(f"no deployment named {service!r} in namespace {NAMESPACE}")
    return PodStatus(service=service, namespace=NAMESPACE, ready=deployment["ready"],
                     desired=deployment["desired"], image=deployment["image"],
                     pods=[Pod(**p) for p in deployment["pods"]])


def recent_alerts(service: str, minutes: int) -> AlertList:
    """Alerts for one service that fired within the last `minutes` minutes, newest first."""
    if service not in DEPLOYMENTS:
        raise UnknownService(f"no deployment named {service!r} in namespace {NAMESPACE}")
    if not 1 <= minutes <= MAX_WINDOW_MINUTES:
        raise ValueError(f"minutes must be between 1 and {MAX_WINDOW_MINUTES}, got {minutes}")
    hits = sorted(
        (Alert(**a) for a in ALERTS if a["service"] == service and a["age_minutes"] <= minutes),
        key=lambda a: a["age_minutes"],
    )
    return AlertList(service=service, window_minutes=minutes, count=len(hits), alerts=hits)
