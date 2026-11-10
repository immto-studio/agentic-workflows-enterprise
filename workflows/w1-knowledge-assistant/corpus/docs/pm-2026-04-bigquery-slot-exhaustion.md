---
title: 'Postmortem: BigQuery slot exhaustion delayed pricing exports'
doc_type: postmortem
owner_team: quill-data-platform
classification: Internal
system: Google BigQuery
last_reviewed: 2026-04-20
access_groups:
- lm-eng-all
---

# Postmortem: BigQuery slot exhaustion delayed pricing exports

**Severity:** Sev3 · **Incident:** INC0116280 · **Date:** 2026-04-01, 18:31 to 18:58 ET (27 minutes)

## Summary

The pricing factors export was 27 minutes late and the AWS rating cache used old factors.

## Timeline (ET)

- 18:31 impact begins
- 18:40 Freshness alert on `pricing_factors_daily`.
- 18:45 incident declared, bridge opened
- 18:58 mitigated

## Root cause

An analyst notebook ran a cross join over `trips_raw` on the shared batch reservation.

## Contributing factors

- The change was reviewed by one person outside business hours.
- Dashboards for the dependency were owned by another team and not linked.

## Action items

| Ticket | Action | Due |
|---|---|---|
| QDP-1634 | Separate reservations for scheduled and ad-hoc queries. | 2026-05-01 |
| QDP-2862 | Maximum bytes billed on notebook service accounts. | 2026-04-15 |
