---
title: 'Postmortem: Private DNS zone disassociated from the shared VPC'
doc_type: postmortem
owner_team: network-engineering
classification: Internal
system: Amazon Route 53
last_reviewed: 2026-07-13
access_groups:
- lm-eng-all
---

# Postmortem: Private DNS zone disassociated from the shared VPC

**Severity:** Sev1 · **Incident:** INC0118085 · **Date:** 2026-07-01, 07:46 to 08:41 ET (55 minutes)

## Summary

Services could not resolve `*.larkspur.internal` names for 55 minutes.

## Timeline (ET)

- 07:46 impact begins
- 07:50 Widespread 5xx alerts.
- 07:58 incident declared, bridge opened
- 08:41 mitigated

## Root cause

A Terraform refactor moved the zone association into a new module; apply destroyed the old association before creating the new one.

## Contributing factors

- The on-call engineer was handling a second incident.
- Dashboards for the dependency were owned by another team and not linked.

## Action items

| Ticket | Action | Due |
|---|---|---|
| NET-1583 | `create_before_destroy` on zone associations. | 2026-08-30 |
| NET-1976 | A canary resolver check per VPC. | 2026-07-31 |
