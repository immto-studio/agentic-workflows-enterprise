---
title: 'ADR-0045: Amazon API Gateway for partner and broker APIs'
doc_type: adr
owner_team: digital-channels
classification: Internal
system: Amazon API Gateway
last_reviewed: 2025-08-24
access_groups:
- lm-eng-all
---

# ADR-0045: Amazon API Gateway for partner and broker APIs

**Status:** Accepted · **Date:** 2025-03-26 · **Deciders:** Security architect, Head of Platform, Engineering manager

## Context

Broker integrations hit EKS ingresses directly with API keys shared by email.

## Decision

External partner APIs are published through API Gateway REST APIs with usage plans, mutual TLS for brokers, and AWS WAF. Internal APIs stay on ALB ingresses.

## Alternatives considered

- Self-hosted API gateway on EKS: rejected.
- CloudFront functions only: rejected.

## Consequences

- Partner onboarding is a Terraform change in `partner-apis`.
- Throttling is per partner, not per IP.
