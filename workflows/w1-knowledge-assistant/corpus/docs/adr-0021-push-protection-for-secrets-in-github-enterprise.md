---
title: 'ADR-0021: Push protection for secrets in GitHub Enterprise'
doc_type: adr
owner_team: security-engineering
classification: Internal
system: GitHub Enterprise
last_reviewed: 2025-03-23
access_groups:
- lm-eng-all
---

# ADR-0021: Push protection for secrets in GitHub Enterprise

**Status:** Accepted · **Date:** 2025-01-31 · **Deciders:** Domain architect, SRE lead, Head of Platform

## Context

Secret scanning found 140 live secrets in repositories in 2025, mostly test credentials and webhooks.

## Decision

Enable secret scanning push protection for every organization, with custom patterns for Vault tokens and ServiceNow credentials. Bypass requires a reason and is reviewed weekly.

## Alternatives considered

- Pre-commit hooks only: rejected.
- Scan after push: rejected.

## Consequences

- Developers see blocked pushes; the developer portal explains how to remove a secret from history.
