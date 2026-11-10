---
title: 'Incident response: paging and acknowledgement times'
doc_type: policy
owner_team: sre-core
classification: Internal
system: ServiceNow
last_reviewed: 2026-06-30
access_groups:
- lm-eng-all
---

# Incident response: paging and acknowledgement times

Revised after the 2026 incident review; replaces the February 2025 version.

| Severity | Acknowledge within | Escalate if unacknowledged |
|---|---|---|
| Sev1 | 5 minutes | to the incident commander rotation `lm-ic-primary` after 10 minutes |
| Sev2 | **15 minutes** | to the incident commander rotation `lm-ic-primary` after 10 minutes past the deadline |
| Sev3 | 4 business hours | none |

Pages go out through ServiceNow On-Call by push notification, then phone call after 2 minutes.
Acknowledging the page is not enough: post a first update in the incident within 15 minutes of ack.
