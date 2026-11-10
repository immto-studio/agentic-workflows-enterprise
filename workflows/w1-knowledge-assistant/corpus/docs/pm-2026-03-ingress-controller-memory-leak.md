---
title: 'Postmortem: Ingress controller memory leak caused 502s'
doc_type: postmortem
owner_team: platform-engineering
classification: Internal
system: Amazon EKS
last_reviewed: 2026-04-09
access_groups:
- lm-eng-all
---

# Postmortem: Ingress controller memory leak caused 502s

**Severity:** Sev2 · **Incident:** INC0113364 · **Date:** 2026-03-11, 07:23 to 07:41 ET (18 minutes)

## Summary

Intermittent 502 errors across several services for 18 minutes.

## Timeline (ET)

- 07:23 impact begins
- 07:27 ALB 5xx alerts on several services.
- 07:31 incident declared, bridge opened
- 07:41 mitigated

## Root cause

A Lua plugin in the ingress controller leaked memory with long-lived WebSocket connections from the agent portal.

## Contributing factors

- The alert that would have caught it earlier was set to ticket, not page.
- A similar near miss six months earlier had no action items.

## Action items

| Ticket | Action | Due |
|---|---|---|
| PLAT-1463 | Remove the plugin and move WebSocket traffic to a dedicated ALB. | 2026-04-25 |
| PLAT-2912 | Memory alerts on ingress controller pods. | 2026-03-25 |
