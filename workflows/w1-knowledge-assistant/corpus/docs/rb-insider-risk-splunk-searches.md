---
title: 'Insider risk: Splunk saved searches and triage'
doc_type: runbook
owner_team: security-operations
classification: Restricted
system: Splunk
last_reviewed: 2026-02-17
access_groups:
- lm-insider-risk
---

# Insider risk: Splunk saved searches and triage

This runbook is for the insider-risk analysts only. Do not discuss the searches below in open
channels; knowing the thresholds makes them easy to stay under.

| Saved search | Fires when | Severity |
|---|---|---|
| `IR-001 Bulk policy export` | a single user exports more than 2,500 policy records from LPAS screens in 1 hour | High |
| `IR-004 Off-hours BigQuery scan` | more than 50 GB scanned in `quill_claims_curated` between 22:00 and 05:00 ET | Medium |
| `IR-007 Departing user S3 download` | a user flagged by HR as leaving downloads from `lm-claims-documents-prod` | High |
| `IR-011 Mass mailbox forwarding` | a new inbox rule forwards to an external domain | High |

## Triage

1. Open the notable in Splunk ES and check the user's HR status in the `hr_leavers` lookup.
2. Never contact the user or their manager directly; open a confidential case in the
   ServiceNow HR Case module under **Insider Risk** and assign it to the Insider Risk lead.
3. Preserve evidence with `| collect index=ir_evidence` before any account action.
