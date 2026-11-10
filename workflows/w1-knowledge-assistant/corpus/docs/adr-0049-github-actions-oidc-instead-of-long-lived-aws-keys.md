---
title: 'ADR-0049: GitHub Actions OIDC instead of long-lived AWS keys'
doc_type: adr
owner_team: platform-engineering
classification: Internal
system: GitHub Actions
last_reviewed: 2026-01-21
access_groups:
- lm-eng-all
---

# ADR-0049: GitHub Actions OIDC instead of long-lived AWS keys

**Status:** Proposed · **Date:** 2025-12-22 · **Deciders:** Principal engineer, SRE lead, Domain architect

## Context

Pipelines in GitHub Enterprise and Jenkins used IAM user access keys stored as secrets; two keys leaked in logs in 2024.

## Decision

GitHub Actions workflows assume IAM roles through OIDC. Trust policies restrict `sub` to `repo:<org>/<repo>:environment:<env>`. IAM users with access keys are denied by SCP in workload accounts.

## Alternatives considered

- Rotate keys automatically: rejected.
- Self-hosted runners with instance profiles only: rejected.

## Consequences

- Jenkins jobs that still need AWS access move to GitHub Actions or get a documented exception.
- Environment protection rules become part of the security boundary.
