---
title: Regulatory notification for incidents involving policyholder data
doc_type: policy
owner_team: legal-regulatory
classification: Confidential
system: ServiceNow
last_reviewed: 2026-08-11
access_groups:
- lm-legal-regulatory
---

# Regulatory notification for incidents involving policyholder data

## Rule

For any Sev1 or Sev2 incident where policyholder personal data may have been accessed, the
incident commander must page the **Regulatory Liaison on-call within 4 hours** of the incident
being declared (ServiceNow On-Call group `LM-Regulatory-Liaison`).

The Regulatory Liaison decides on notification. Several states where Larkspur writes business
follow the NAIC Insurance Data Security Model Law, which requires notice to the insurance
commissioner within **72 hours** of determining that a cybersecurity event occurred.

## What to hand over

- Incident number and current timeline
- Systems and data classes involved (use the data classification standard)
- Number of policyholders potentially affected, even if estimated
- Whether data left Larkspur-controlled systems
