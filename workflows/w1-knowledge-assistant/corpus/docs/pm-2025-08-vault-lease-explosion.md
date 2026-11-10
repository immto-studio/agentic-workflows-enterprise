---
title: 'Postmortem: Vault performance degraded by lease explosion'
doc_type: postmortem
owner_team: security-engineering
classification: Internal
system: HashiCorp Vault
last_reviewed: 2025-08-30
access_groups:
- lm-eng-all
---

# Postmortem: Vault performance degraded by lease explosion

**Severity:** Sev2 · **Incident:** INC0102118 · **Date:** 2025-08-18, 13:02 to 13:29 ET (27 minutes)

## Summary

Vault request latency exceeded 2 seconds for 27 minutes and pod start-ups failed.

## Timeline (ET)

- 13:02 impact begins
- 13:07 Vault latency alert.
- 13:15 incident declared, bridge opened
- 13:29 mitigated

## Root cause

A CronJob running every minute requested new database credentials each run and never revoked them, creating 410,000 leases.

## Contributing factors

- The alert that would have caught it earlier was set to ticket, not page.
- The on-call engineer was handling a second incident.

## Action items

| Ticket | Action | Due |
|---|---|---|
| SEC-1590 | Lease count quotas per auth role. | 2025-10-17 |
| SEC-1180 | Reuse credentials through Vault Agent caching. | 2025-10-17 |
