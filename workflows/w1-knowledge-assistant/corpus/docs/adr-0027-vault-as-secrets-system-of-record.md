---
title: 'ADR-0027: HashiCorp Vault as the system of record for secrets'
doc_type: adr
owner_team: platform-engineering
classification: Internal
system: HashiCorp Vault
last_reviewed: 2026-05-07
access_groups:
- lm-eng-all
---

# ADR-0027: HashiCorp Vault as the system of record for secrets

**Status:** Accepted · **Supersedes:** ADR-0004

## Context

Secrets Manager worked for AWS but not for Quill on GKE or the .NET apps on Azure, and static
database passwords rotated every 90 days were still long-lived.

## Decision

- Vault is the system of record for all application secrets on every cloud.
- New services get **dynamic database credentials from Vault** at `database/creds/<service>-rw`
  with a **1-hour TTL**, delivered by the Vault Agent sidecar. No new static database passwords.
- Secrets Manager is used only where an AWS service requires it (for example RDS Proxy), and is
  populated by Vault Secrets Operator sync, never written by hand.

## Consequences

Existing Secrets Manager secrets migrate by 2026-12-31 (tracked in PLAT-2210).
