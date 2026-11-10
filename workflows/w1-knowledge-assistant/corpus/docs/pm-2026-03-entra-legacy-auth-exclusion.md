---
title: 'Postmortem: legacy authentication allowed for a service-account exclusion group'
doc_type: postmortem
owner_team: security-incident-response
classification: Confidential
system: Microsoft Entra ID
last_reviewed: 2026-04-02
access_groups:
- lm-sec-incident-response
---

# Postmortem: legacy authentication allowed for a service-account exclusion group

**Severity:** Sev2 · **Incident:** INC0119530 · **Date:** 2026-03-09

## Summary

The conditional access policy `CA-003 Block legacy authentication` excluded the group
`sg-ca-legacy-auth-exempt`, created in 2023 for a scanner integration. The group had grown to 37
accounts, including 4 human accounts added by a helpdesk script. A password-spray attack
succeeded against one of them over IMAP; the mailbox was accessed for 26 minutes.

## Root cause

Exclusion groups in conditional access were not covered by the quarterly access review.

## Actions

- IAM-902: exclusion group emptied; scanner moved to a workload identity with certificate auth.
- IAM-903: all CA exclusion groups added to the privileged access review.
- IAM-905: alert on any change to CA exclusion group membership.
