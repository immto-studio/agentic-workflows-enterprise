---
title: 'Postmortem: Terraform apply removed a Transit Gateway route'
doc_type: postmortem
owner_team: network-engineering
classification: Internal
system: Terraform
last_reviewed: 2026-06-13
access_groups:
- lm-eng-all
---

# Postmortem: Terraform apply removed a Transit Gateway route

**Severity:** Sev1 · **Incident:** INC0129223 · **Date:** 2026-05-19, 16:14 to 17:58 ET (104 minutes)

## Summary

Traffic from EKS to the mainframe MQ channel stopped for 104 minutes.

## Timeline (ET)

- 16:14 impact begins
- 16:21 MQ bridge depth alert.
- 16:23 incident declared, bridge opened
- 17:58 mitigated

## Root cause

A route added by hand during a 2025 incident was not in Terraform. A routine apply in `network-live` removed it; the plan showed the deletion but the reviewer missed it among 40 tag changes.

## Contributing factors

- Dashboards for the dependency were owned by another team and not linked.
- The on-call engineer was handling a second incident.

## Action items

| Ticket | Action | Due |
|---|---|---|
| NET-2801 | Fail plans that destroy routes unless the PR carries the `network-destroy-approved` label. | 2026-06-18 |
| NET-2052 | Weekly drift detection on network workspaces. | 2026-06-02 |
