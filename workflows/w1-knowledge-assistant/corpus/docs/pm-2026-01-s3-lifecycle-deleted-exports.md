---
title: 'Postmortem: S3 lifecycle rule deleted export files early'
doc_type: postmortem
owner_team: billing-engineering
classification: Internal
system: Amazon S3
last_reviewed: 2026-02-27
access_groups:
- lm-eng-all
---

# Postmortem: S3 lifecycle rule deleted export files early

**Severity:** Sev3 · **Incident:** INC0105961 · **Date:** 2026-01-30, 14:46 to 15:20 ET (34 minutes)

## Summary

Billing extracts older than 7 days were deleted; reconciliation for 34 minutes of work had to be re-run.

## Timeline (ET)

- 14:46 impact begins
- 14:50 Month-end reconciliation could not find files.
- 14:53 incident declared, bridge opened
- 15:20 mitigated

## Root cause

A lifecycle rule with an empty prefix filter applied to the whole bucket instead of the `tmp/` prefix.

## Contributing factors

- Dashboards for the dependency were owned by another team and not linked.
- The alert that would have caught it earlier was set to ticket, not page.

## Action items

| Ticket | Action | Due |
|---|---|---|
| BILL-2242 | Versioning on all extract buckets. | 2026-03-16 |
| BILL-1433 | Lifecycle rules reviewed by the module's validation. | 2026-03-01 |
