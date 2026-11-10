---
title: 'Postmortem: Quote latency spike after a rules publish'
doc_type: postmortem
owner_team: policy-engineering
classification: Internal
system: Amazon EKS
last_reviewed: 2026-01-02
access_groups:
- lm-eng-all
---

# Postmortem: Quote latency spike after a rules publish

**Severity:** Sev2 · **Incident:** INC0103786 · **Date:** 2025-12-09, 18:31 to 20:42 ET (131 minutes)

## Summary

Quote p99 rose above 6 seconds for 131 minutes and agents saw timeouts on the agent portal.

## Timeline (ET)

- 18:31 impact begins
- 18:40 Burn-rate alert on the quote SLO.
- 18:45 incident declared, bridge opened
- 20:42 mitigated

## Root cause

A new underwriting rule set added a regex evaluated per vehicle with catastrophic backtracking for some VIN formats.

## Contributing factors

- A similar near miss six months earlier had no action items.
- The alert that would have caught it earlier was set to ticket, not page.

## Action items

| Ticket | Action | Due |
|---|---|---|
| POL-1326 | Add rule performance tests to the publishing pipeline with a 50 ms budget per rule. | 2026-01-23 |
| POL-1723 | Allow pinning the previous rule set without a deploy. | 2026-01-23 |
