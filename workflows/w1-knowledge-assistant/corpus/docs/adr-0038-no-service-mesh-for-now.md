---
title: 'ADR-0038: No service mesh for now'
doc_type: adr
owner_team: platform-engineering
classification: Internal
system: Amazon EKS
last_reviewed: 2025-07-28
access_groups:
- lm-eng-all
---

# ADR-0038: No service mesh for now

**Status:** Accepted · **Date:** 2025-01-29 · **Deciders:** Chief Architect, Domain architect, Head of Platform

## Context

A service mesh was proposed for mTLS and traffic shifting. Most traffic is north-south and the team has no mesh experience.

## Decision

Do not adopt a service mesh in 2026. Use Kubernetes NetworkPolicies through the VPC CNI policy agent and TLS at the ingress. Revisit when east-west traffic between domains passes 30% of requests.

## Alternatives considered

- Istio ambient mode: rejected.
- AWS VPC Lattice: rejected.

## Consequences

- Canary releases use the ALB weighted target groups.
- Zero-trust between namespaces relies on NetworkPolicies and identity at the application layer.
