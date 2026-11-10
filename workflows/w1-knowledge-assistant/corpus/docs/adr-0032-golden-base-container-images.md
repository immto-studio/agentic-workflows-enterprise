---
title: 'ADR-0032: Golden base container images'
doc_type: adr
owner_team: developer-platform
classification: Internal
system: Amazon ECR
last_reviewed: 2026-02-08
access_groups:
- lm-eng-all
---

# ADR-0032: Golden base container images

**Status:** Proposed · **Date:** 2025-03-19 · **Deciders:** Engineering manager, Chief Architect, Principal engineer

## Context

Teams built on dozens of public images; critical CVEs took weeks to patch because nobody knew which images were affected.

## Decision

Services build on golden base images in ECR (`lm-base/*`), rebuilt weekly from Amazon Linux 2023 or distroless. Admission policy in EKS rejects images not derived from a golden base.

## Alternatives considered

- Scan only, no base image mandate: rejected.
- Buy a hardened image subscription: rejected.

## Consequences

- Weekly rebuilds trigger downstream builds through Renovate.
- Exceptions are recorded in the service catalogue.
