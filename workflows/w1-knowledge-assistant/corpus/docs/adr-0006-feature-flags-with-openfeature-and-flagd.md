---
title: 'ADR-0006: Feature flags with OpenFeature and flagd'
doc_type: adr
owner_team: developer-platform
classification: Internal
system: Amazon EKS
last_reviewed: 2025-10-03
access_groups:
- lm-eng-all
---

# ADR-0006: Feature flags with OpenFeature and flagd

**Status:** Accepted · **Date:** 2025-02-15 · **Deciders:** Security architect, Principal engineer, SRE lead

## Context

Teams implemented flags with environment variables and config files, so turning off a feature needed a deploy.

## Decision

Use the OpenFeature SDK with flagd, flags stored in the `feature-flags` repository and synced by GitOps. Flags have an owner and an expiry date.

## Alternatives considered

- Commercial flag service: rejected.
- Build our own: rejected.

## Consequences

- Kill switches can be flipped in minutes through a pull request with fast-track approval.
- Expired flags fail a weekly CI report.
