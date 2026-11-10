---
title: 'Postmortem: Lambda concurrency starvation in the claims account'
doc_type: postmortem
owner_team: claims-engineering
classification: Internal
system: AWS Lambda
last_reviewed: 2026-01-27
access_groups:
- lm-eng-all
---

# Postmortem: Lambda concurrency starvation in the claims account

**Severity:** Sev2 · **Incident:** INC0127469 · **Date:** 2026-01-11, 20:38 to 22:49 ET (131 minutes)

## Summary

Attachment scanning and photo classification stopped for 131 minutes.

## Timeline (ET)

- 20:38 impact begins
- 20:49 Throttle alarms on two functions.
- 20:51 incident declared, bridge opened
- 22:49 mitigated

## Root cause

A backfill job invoked a Lambda without reserved concurrency and used the whole account limit of 1,000.

## Contributing factors

- The alert that would have caught it earlier was set to ticket, not page.
- The on-call engineer was handling a second incident.

## Action items

| Ticket | Action | Due |
|---|---|---|
| CLM-1575 | Reserved concurrency for every production function. | 2026-02-10 |
| CLM-2285 | Backfills run in a separate account. | 2026-01-25 |
