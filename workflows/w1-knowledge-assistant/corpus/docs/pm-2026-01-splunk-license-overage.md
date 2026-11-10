---
title: 'Postmortem: Splunk ingest blocked after a licence overage'
doc_type: postmortem
owner_team: observability
classification: Internal
system: Splunk
last_reviewed: 2026-02-09
access_groups:
- lm-eng-all
---

# Postmortem: Splunk ingest blocked after a licence overage

**Severity:** Sev3 · **Incident:** INC0101717 · **Date:** 2026-01-20, 07:14 to 07:41 ET (27 minutes)

## Summary

Search was blocked for 27 minutes after five licence warnings in 30 days.

## Timeline (ET)

- 07:14 impact begins
- 07:25 Splunk licence warning emails had gone to a distribution list nobody read.
- 07:31 incident declared, bridge opened
- 07:41 mitigated

## Root cause

Debug logging left on for `payments-ledger` after an incident generated 600 GB per day.

## Contributing factors

- The runbook did not cover this failure mode.
- The on-call engineer was handling a second incident.

## Action items

| Ticket | Action | Due |
|---|---|---|
| OBS-1653 | Debug logging expires automatically after 4 hours. | 2026-02-03 |
| OBS-1511 | Licence warnings page the observability on-call. | 2026-02-19 |
