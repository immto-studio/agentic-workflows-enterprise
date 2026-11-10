---
title: 'ADR-0019: Retirement timeline for the LPAS mainframe'
doc_type: adr
owner_team: enterprise-architecture
classification: Confidential
system: LPAS mainframe
last_reviewed: 2026-03-26
access_groups:
- lm-ea-leads
---

# ADR-0019: Retirement timeline for the LPAS mainframe

**Status:** Accepted (Architecture Review Board, 2026-03-24)
**Deciders:** CTO, Chief Architect, VP Policy Engineering, CFO delegate

## Context

LPAS, the policy administration system for personal lines, runs on z/OS with CICS and DB2. The
hardware lease and software licences renew in June 2026. The vendor offered a 5-year renewal at a
discount or a shorter term at list price. Two COBOL engineers retire in 2027.

## Decision

- Renew the mainframe contract for **3 years only** (to June 2029), accepting the higher annual cost
  of about 4.1 million USD per year.
- Move policy servicing to the new `policy-core` platform on EKS and Aurora in three waves:
  auto (2027), homeowners (2027-2028), umbrella and specialty (2028).
- Target final LPAS cutover and **retirement by Q4 2028 (cutover weekend 2028-11-11)**, leaving
  seven months of contract as contingency.
- Do not announce the date outside the programme until the workforce plan for the mainframe
  operations team is agreed with HR.

## Consequences

- The MQ-to-Kafka bridge becomes the primary integration path and must reach 99.95% availability.
- No new features are built on LPAS after 2026-12-31 except regulatory changes.
