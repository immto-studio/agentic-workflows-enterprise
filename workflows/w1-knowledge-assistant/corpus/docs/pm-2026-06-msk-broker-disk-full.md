---
title: 'Postmortem: MSK broker disk full stopped claims events'
doc_type: postmortem
owner_team: integration-engineering
classification: Internal
system: Amazon MSK
last_reviewed: 2026-06-30
access_groups:
- lm-eng-all
---

# Postmortem: MSK broker disk full stopped claims events

**Severity:** Sev2 · **Incident:** INC0128720 · **Date:** 2026-06-10, 17:46 to 19:30 ET (104 minutes)

## Summary

Producers to `claims.claim-events.v3` failed for 104 minutes.

## Timeline (ET)

- 17:46 impact begins
- 17:57 Producer error alerts from claims-api.
- 18:05 incident declared, bridge opened
- 19:30 mitigated

## Root cause

A consumer group was deleted while its topic used `cleanup.policy=compact,delete` with a 30-day retention set by mistake, and broker storage auto-scaling had a maximum that was reached.

## Contributing factors

- The on-call engineer was handling a second incident.
- The alert that would have caught it earlier was set to ticket, not page.

## Action items

| Ticket | Action | Due |
|---|---|---|
| INT-2174 | Alert on broker disk at 70% instead of 85%. | 2026-06-24 |
| INT-2875 | Validate topic retention in the msk-topic module. | 2026-07-10 |
