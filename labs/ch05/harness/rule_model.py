"""A rule-based stand-in for the model, so the lab answers real questions without an API key.

Chapter 5, part 2. The chapter 1 `fake_model` asks one fixed question. The golden set and the
analyst agent need a "model" that reads a question, picks one of the two tools, and writes an
answer from the result. This one does it with rules and fixed sentence templates, so every answer
is reproducible and the golden set can be checked by exact match.

It plugs into `run_agent` from chapter 1 like any model: it only ever returns text parsed into a
dict, either `{"tool_call": {...}}` or `{"answer": "..."}`. The harness still owns the allowlist.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

DEFAULT_WINDOW_MINUTES = 60
MUTATION_WORDS = ("restart", "scale", "delete", "roll back", "rollback", "redeploy", "kill", "patch")
ALERT_WORDS = ("alert", "alerts", "fired", "firing", "paged", "incident")
POD_WORDS = ("pod", "pods", "healthy", "health", "ready", "replica", "replicas", "running", "status", "up")
NOT_A_SERVICE = {"larkspur-prod", "read-only", "crash-looping", "non-production"}

_SERVICE = re.compile(r"\b([a-z]+(?:-[a-z]+)+)\b")  # every Larkspur service name is hyphenated
_MINUTES = re.compile(r"\b(\d+)\s*(?:minutes?|mins?|m)\b")
_HOURS = re.compile(r"\b(\d+)\s*(?:hours?|hrs?|h)\b")


@dataclass(frozen=True)
class Intent:
    kind: str  # "pods", "alerts", "mutation", "unknown"
    service: str | None = None
    minutes: int = DEFAULT_WINDOW_MINUTES
    verb: str | None = None


def parse_question(text: str) -> Intent:
    lower = text.lower()
    service = next((m for m in _SERVICE.findall(lower) if m not in NOT_A_SERVICE), None)
    for verb in MUTATION_WORDS:
        if re.search(rf"\b{verb}\b", lower):
            return Intent("mutation", service, verb=verb)
    minutes = DEFAULT_WINDOW_MINUTES
    if m := _MINUTES.search(lower):
        minutes = int(m.group(1))
    elif h := _HOURS.search(lower):
        minutes = int(h.group(1)) * 60
    elif "today" in lower or "last day" in lower:
        minutes = 24 * 60
    words = set(re.findall(r"[a-z]+", lower))
    if words & set(ALERT_WORDS):
        return Intent("alerts", service, minutes)
    if words & set(POD_WORDS):
        return Intent("pods", service)
    return Intent("unknown", service)


def answer_from_pods(result: dict) -> str:
    base = f"{result['service']} has {result['ready']} of {result['desired']} pods ready."
    not_ready = [p for p in result["pods"] if p["phase"] != "Running"]
    if not not_ready:
        return base
    detail = ", ".join(f"{p['name']} ({p['phase']}, {p['restarts']} restarts)" for p in not_ready)
    return f"{base} Not ready: {detail}."


def answer_from_alerts(result: dict) -> str:
    service, minutes, alerts = result["service"], result["window_minutes"], result["alerts"]
    if not alerts:
        return f"{service} had no alerts in the last {minutes} minutes."
    counts = {sev: sum(1 for a in alerts if a["severity"] == sev) for sev in ("critical", "warning", "info")}
    breakdown = ", ".join(f"{n} {sev}" for sev, n in counts.items() if n)
    latest = alerts[0]  # the server returns newest first
    plural = "alert" if len(alerts) == 1 else "alerts"
    return (f"{service} had {len(alerts)} {plural} in the last {minutes} minutes ({breakdown}). "
            f"Latest, {latest['age_minutes']} minutes ago, {latest['severity']}: {latest['summary']}")


def answer_from_error(error: str) -> str:
    error = re.sub(r"^Error executing tool \S+: ", "", error)  # the MCP SDK's prefix on a ToolError
    return error[:1].upper() + error[1:] + ("" if error.endswith(".") else ".")


def rule_based_model(messages: list[dict]) -> dict:
    """Model stand-in: one tool call chosen by rules, then an answer from a fixed template."""
    question = next(m["content"] for m in messages if m["role"] == "user")
    tool_results = [m for m in messages if m["role"] == "tool"]
    if not tool_results:
        intent = parse_question(question)
        if intent.kind == "mutation":
            target = intent.service or "anything"
            return {"answer": f"I can only read the namespace: there is no tool to {intent.verb} {target}."}
        if intent.service is None:
            return {"answer": "I could not find a service name in the question. Name one deployment, "
                              "for example claims-api."}
        if intent.kind == "alerts":
            return {"tool_call": {"name": "get_recent_alerts",
                                  "args": {"service": intent.service, "minutes": intent.minutes}}}
        if intent.kind == "pods":
            return {"tool_call": {"name": "get_pod_status", "args": {"service": intent.service}}}
        return {"answer": f"I can report pod status or recent alerts for {intent.service}; "
                          "ask for one of those."}
    result = json.loads(tool_results[-1]["content"])
    if "error" in result:
        return {"answer": answer_from_error(result["error"])}
    if "alerts" in result:
        return {"answer": answer_from_alerts(result)}
    return {"answer": answer_from_pods(result)}
