---
title: 'ADR-0052: Karpenter for EKS node provisioning'
doc_type: adr
owner_team: platform-engineering
classification: Internal
system: Amazon EKS
last_reviewed: 2025-10-16
access_groups:
- lm-eng-all
---

# ADR-0052: Karpenter for EKS node provisioning

**Status:** Accepted · **Date:** 2025-09-14 · **Deciders:** Principal engineer, Head of Platform, Domain architect

## Context

Cluster Autoscaler with managed node groups needed one node group per instance shape, and scale-up took 4 to 6 minutes.

## Decision

Use Karpenter for all workload nodes in EKS. Keep one small managed node group for system add-ons. NodePools prefer Graviton and allow spot for stateless workloads labelled `lm.io/spot-ok=true`.

## Alternatives considered

- Keep Cluster Autoscaler with more node groups: rejected.
- EKS Auto Mode: rejected.

## Consequences

- Node consolidation moves pods more often; every Deployment needs a PodDisruptionBudget.
- The eks-cluster module ships Karpenter from version 5.0.
