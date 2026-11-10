---
title: 'ADR-0055: Integrate with LPAS through MQ, not DB2 reads'
doc_type: adr
owner_team: integration-engineering
classification: Internal
system: LPAS mainframe
last_reviewed: 2026-06-29
access_groups:
- lm-eng-all
---

# ADR-0055: Integrate with LPAS through MQ, not DB2 reads

**Status:** Accepted · **Date:** 2026-02-06 · **Deciders:** Principal engineer, Security architect, Engineering manager

## Context

Several services read LPAS DB2 tables directly through JDBC, which locked rows during the batch window and broke after copybook changes.

## Decision

AWS services consume LPAS changes from the MQ-to-Kafka bridge only. Direct DB2 access from AWS is removed by the end of 2026.

## Alternatives considered

- Change data capture on DB2: rejected.
- Nightly file extracts only: rejected.

## Consequences

- Event schemas mirror copybooks and are versioned.
- Mainframe operations own the MQ side; integration engineering owns the bridge.
