---
title: 'ADR-0048: Renovate for dependency updates'
doc_type: adr
owner_team: developer-platform
classification: Internal
system: GitHub Enterprise
last_reviewed: 2026-09-26
access_groups:
- lm-eng-all
---

# ADR-0048: Renovate for dependency updates

**Status:** Proposed · **Date:** 2025-10-23 · **Deciders:** Principal engineer, Security architect, Domain architect

## Context

Dependency updates were manual and lagged months behind security fixes.

## Decision

Run Renovate self-hosted on GitHub Actions across all organizations with a shared preset `larkspur-platform/renovate-config`. Patch updates auto-merge when CI is green.

## Alternatives considered

- Dependabot only: rejected.
- Quarterly manual update sprints: rejected.

## Consequences

- Teams must keep CI meaningful because auto-merge trusts it.
- Grouped PRs limit noise to one per ecosystem per week.
