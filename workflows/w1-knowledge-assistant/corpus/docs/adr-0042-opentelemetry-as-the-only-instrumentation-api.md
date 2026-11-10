---
title: 'ADR-0042: OpenTelemetry as the only instrumentation API'
doc_type: adr
owner_team: observability
classification: Internal
system: OpenTelemetry
last_reviewed: 2025-06-29
access_groups:
- lm-eng-all
---

# ADR-0042: OpenTelemetry as the only instrumentation API

**Status:** Accepted · **Date:** 2025-05-25 · **Deciders:** SRE lead, Head of Platform, Domain architect

## Context

Services used three tracing libraries and two metrics clients, which made cross-service traces incomplete.

## Decision

New and changed services instrument with OpenTelemetry SDKs only and export OTLP to the node-local collector. W3C trace context is mandatory on all HTTP and Kafka hops.

## Alternatives considered

- Vendor agents per language: rejected.
- Keep existing libraries and translate in the collector: rejected.

## Consequences

- Library migration is part of normal work, tracked per service in the service catalogue.
- Kafka headers must carry `traceparent`.
