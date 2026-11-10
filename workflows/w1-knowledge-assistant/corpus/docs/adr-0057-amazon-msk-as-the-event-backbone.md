---
title: 'ADR-0057: Amazon MSK as the event backbone'
doc_type: adr
owner_team: integration-engineering
classification: Internal
system: Amazon MSK
last_reviewed: 2026-06-08
access_groups:
- lm-eng-all
---

# ADR-0057: Amazon MSK as the event backbone

**Status:** Accepted · **Date:** 2025-11-01 · **Deciders:** Security architect, Engineering manager, Chief Architect

## Context

Events moved through SNS, SQS and point-to-point HTTP callbacks. Replay was impossible and ordering was not guaranteed.

## Decision

Business events go to Amazon MSK with IAM authentication. Schemas are Avro in the Glue Schema Registry with BACKWARD compatibility. Topic names follow `<domain>.<entity>-events.v<n>`.

## Alternatives considered

- Amazon Kinesis Data Streams: rejected.
- Self-managed Kafka on EKS: rejected.

## Consequences

- Teams own their topics through the `msk-topic` Terraform module.
- SQS remains for work queues inside one service.
