---
title: 'ADR-0050: Graviton by default for new workloads'
doc_type: adr
owner_team: platform-engineering
classification: Internal
system: Amazon EKS
last_reviewed: 2025-07-16
access_groups:
- lm-eng-all
---

# ADR-0050: Graviton by default for new workloads

**Status:** Accepted · **Date:** 2025-03-22 · **Deciders:** Engineering manager, Security architect, Head of Platform

## Context

Price-performance tests on claims-api and policy-quote-service showed 22% lower cost per request on Graviton.

## Decision

New EKS and Lambda workloads target arm64. Images are built multi-arch. x86 is allowed with a reason in the service catalogue.

## Alternatives considered

- Stay on x86: rejected.
- Decide per team: rejected.

## Consequences

- Native dependencies need arm64 builds.
- Karpenter NodePools list Graviton families first.
