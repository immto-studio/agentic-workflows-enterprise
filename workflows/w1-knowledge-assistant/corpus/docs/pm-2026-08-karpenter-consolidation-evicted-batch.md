---
title: 'Postmortem: Karpenter consolidation evicted renewal batch pods'
doc_type: postmortem
owner_team: platform-engineering
classification: Internal
system: Amazon EKS
last_reviewed: 2026-09-14
access_groups:
- lm-eng-all
---

# Postmortem: Karpenter consolidation evicted renewal batch pods

**Severity:** Sev3 · **Incident:** INC0111866 · **Date:** 2026-08-21, 17:09 to 17:27 ET (18 minutes)

## Summary

The nightly renewals batch on EKS restarted 14 times and finished 18 minutes late.

## Timeline (ET)

- 17:09 impact begins
- 17:20 Billing Engineering noticed the late extract the next morning.
- 17:27 incident declared, bridge opened
- 17:27 mitigated

## Root cause

The batch Job pods had no `karpenter.sh/do-not-disrupt` annotation and consolidation moved them repeatedly.

## Contributing factors

- The on-call engineer was handling a second incident.
- Dashboards for the dependency were owned by another team and not linked.

## Action items

| Ticket | Action | Due |
|---|---|---|
| PLAT-2484 | Annotate batch pods with `karpenter.sh/do-not-disrupt: "true"`. | 2026-09-04 |
| PLAT-2940 | Add a consolidation budget for the batch NodePool. | 2026-10-05 |
