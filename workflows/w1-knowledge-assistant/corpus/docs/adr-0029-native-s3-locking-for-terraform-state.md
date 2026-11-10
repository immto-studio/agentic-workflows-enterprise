---
title: 'ADR-0029: Native S3 locking for Terraform state'
doc_type: adr
owner_team: platform-engineering
classification: Internal
system: Terraform
last_reviewed: 2026-09-22
access_groups:
- lm-eng-all
---

# ADR-0029: Native S3 locking for Terraform state

**Status:** Proposed · **Date:** 2025-12-24 · **Deciders:** Head of Platform, Principal engineer, SRE lead

## Context

State locking used one DynamoDB table per account. Terraform 1.10 added S3 native locking with conditional writes.

## Decision

New backends use `use_lockfile = true` on the S3 backend. Existing DynamoDB lock tables are removed after each workspace has run once with both enabled.

## Alternatives considered

- Keep DynamoDB locking: rejected.
- Terraform Cloud remote state: rejected.

## Consequences

- Minimum Terraform version for live workspaces becomes 1.10.
- One fewer table per account to audit.
