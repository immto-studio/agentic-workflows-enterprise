---
title: 'Postmortem: Mobile release created duplicate claims'
doc_type: postmortem
owner_team: digital-channels
classification: Internal
system: Amazon EKS
last_reviewed: 2026-07-31
access_groups:
- lm-eng-all
---

# Postmortem: Mobile release created duplicate claims

**Severity:** Sev2 · **Incident:** INC0112938 · **Date:** 2026-07-21, 08:09 to 09:04 ET (55 minutes)

## Summary

About 310 duplicate first notices of loss were created over 55 minutes.

## Timeline (ET)

- 08:09 impact begins
- 08:13 Claims adjusters reported duplicates in the morning queue.
- 08:15 incident declared, bridge opened
- 09:04 mitigated

## Root cause

The mobile app retried FNOL submission on a 504 without an idempotency key after a client library upgrade dropped the header.

## Contributing factors

- A similar near miss six months earlier had no action items.
- The runbook did not cover this failure mode.

## Action items

| Ticket | Action | Due |
|---|---|---|
| DIG-1377 | Reject FNOL submissions without an `Idempotency-Key` header at the API. | 2026-08-20 |
| DIG-1660 | Contract test for the header in the mobile CI. | 2026-09-19 |
