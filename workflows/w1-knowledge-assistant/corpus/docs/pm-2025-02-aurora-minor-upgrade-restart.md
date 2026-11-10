---
title: 'Postmortem: Unplanned restart during an Aurora minor version upgrade'
doc_type: postmortem
owner_team: sre-core
classification: Internal
system: Amazon Aurora PostgreSQL
last_reviewed: 2025-02-28
access_groups:
- lm-eng-all
---

# Postmortem: Unplanned restart during an Aurora minor version upgrade

**Severity:** Sev2 · **Incident:** INC0110765 · **Date:** 2025-02-15, 16:09 to 17:53 ET (104 minutes)

## Summary

policy-aurora-prod was unavailable for 104 minutes during business hours.

## Timeline (ET)

- 16:09 impact begins
- 16:17 Error rate alerts on several policy services.
- 16:19 incident declared, bridge opened
- 17:53 mitigated

## Root cause

Auto minor version upgrade was enabled and the maintenance window was set to UTC instead of US Eastern night hours.

## Contributing factors

- The runbook did not cover this failure mode.
- The alert that would have caught it earlier was set to ticket, not page.

## Action items

| Ticket | Action | Due |
|---|---|---|
| SRE-1869 | Disable auto minor version upgrade on tier-1 clusters. | 2025-04-16 |
| SRE-1205 | Maintenance windows set in Terraform and checked by policy. | 2025-04-16 |
