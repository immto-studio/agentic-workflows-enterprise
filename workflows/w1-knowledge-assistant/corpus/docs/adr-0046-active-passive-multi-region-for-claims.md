---
title: 'ADR-0046: Active-passive multi-region for claims'
doc_type: adr
owner_team: claims-engineering
classification: Internal
system: Amazon Aurora PostgreSQL
last_reviewed: 2025-05-24
access_groups:
- lm-eng-all
---

# ADR-0046: Active-passive multi-region for claims

**Status:** Accepted · **Date:** 2025-04-24 · **Deciders:** Engineering manager, Security architect, Domain architect

## Context

A regional outage in us-east-1 would stop first notice of loss intake, which regulators expect to be available during catastrophes.

## Decision

claims-api and fnol-intake run active-passive across us-east-1 and us-west-2 with Aurora Global Database. Target RPO 5 minutes, RTO 60 minutes. Failover is manual and rehearsed twice a year.

## Alternatives considered

- Active-active: rejected.
- Backup and restore only: rejected.

## Consequences

- DR environment costs about 38% of production.
- Game days are scheduled in March and September.
