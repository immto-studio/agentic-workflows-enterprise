---
title: 'ADR-0037: SLOs as code next to the service'
doc_type: adr
owner_team: sre-core
classification: Internal
system: Grafana
last_reviewed: 2026-07-07
access_groups:
- lm-eng-all
---

# ADR-0037: SLOs as code next to the service

**Status:** Accepted · **Date:** 2025-08-17 · **Deciders:** SRE lead, Head of Platform, Principal engineer

## Context

SLOs lived in spreadsheets and were not connected to alerting.

## Decision

Each tier-1 service defines SLOs in `slo.yaml` in its repository. A pipeline generates Grafana recording rules and multi-window burn-rate alerts.

## Alternatives considered

- Define SLOs in the Grafana UI: rejected.
- Keep spreadsheets: rejected.

## Consequences

- Paging alerts for tier-1 services are burn-rate alerts, not raw thresholds.
- Error budget status is reviewed monthly.
