---
title: 'ADR-0018: Customer-managed KMS keys per data domain'
doc_type: adr
owner_team: security-engineering
classification: Internal
system: AWS KMS
last_reviewed: 2025-11-29
access_groups:
- lm-eng-all
---

# ADR-0018: Customer-managed KMS keys per data domain

**Status:** Accepted · **Date:** 2025-01-21 · **Deciders:** Principal engineer, Head of Platform, SRE lead

## Context

Most data was encrypted with AWS-managed keys, which cannot be restricted by key policy.

## Decision

Each data domain (claims, policy, billing, customer, telematics) has its own customer-managed KMS key per account and environment. Key policies grant decrypt only to the domain's roles.

## Alternatives considered

- One key per account: rejected.
- AWS-managed keys: rejected.

## Consequences

- Cross-domain reads need an explicit grant and a data-sharing record.
- KMS request costs increase by about 900 USD per month.
