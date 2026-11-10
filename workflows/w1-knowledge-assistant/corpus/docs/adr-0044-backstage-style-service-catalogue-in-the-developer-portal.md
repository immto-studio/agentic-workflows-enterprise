---
title: 'ADR-0044: Backstage-style service catalogue in the developer portal'
doc_type: adr
owner_team: developer-platform
classification: Internal
system: GitHub Enterprise
last_reviewed: 2026-05-11
access_groups:
- lm-eng-all
---

# ADR-0044: Backstage-style service catalogue in the developer portal

**Status:** Accepted · **Date:** 2025-02-27 · **Deciders:** Head of Platform, Engineering manager, Principal engineer

## Context

Ownership of 600 services was spread over spreadsheets and Confluence pages.

## Decision

Every repository has a `catalog-info.yaml` with owner, tier, runbook link and on-call group. The developer portal indexes it and CI fails without it for tier-1 services.

## Alternatives considered

- ServiceNow CMDB as the source: rejected.
- Confluence page per service: rejected.

## Consequences

- ServiceNow CMDB is populated from the catalogue nightly.
- Runbook links are checked for 404s weekly.
