---
title: 'Postmortem: quill_telematics_raw dataset readable by all authenticated users'
doc_type: postmortem
owner_team: security-incident-response
classification: Restricted
system: Google BigQuery
last_reviewed: 2025-12-09
access_groups:
- lm-sec-incident-response
---

# Postmortem: quill_telematics_raw dataset readable by all authenticated users

**Severity:** Sev1 (privacy) · **Incident:** INC0102284 · **Date:** 2025-11-18 to 2025-11-20

## Summary

The BigQuery dataset `quill-analytics-prod:quill_telematics_raw` was granted
`roles/bigquery.dataViewer` to `allAuthenticatedUsers` for **41 hours**. The dataset holds
trip-level telematics for 18,240 policyholders, including GPS start and end points. Access logs
show three reads from outside the Quill organization, all from a research crawler; no evidence of
download beyond schema metadata.

## Root cause

A Terraform change in `quill-infra` (PR #2291) added a `google_bigquery_dataset_iam_member` with
`member = "allAuthenticatedUsers"` intended for a sandbox project. The variable file for prod was
copied from sandbox. The plan output showed the binding but review focused on the table schema.

## Detection

Security Command Center finding `PUBLIC_DATASET` at 2025-11-20 07:12 UTC, 41 hours after apply.

## Actions

- SEC-1873: org policy `iam.allowedPolicyMemberDomains` enforced on the Quill organization (done).
- SEC-1874: conftest rule rejecting `allUsers` and `allAuthenticatedUsers` in all Terraform plans (done).
- LEGAL-311: regulator notification assessment completed; notification filed with two states.
