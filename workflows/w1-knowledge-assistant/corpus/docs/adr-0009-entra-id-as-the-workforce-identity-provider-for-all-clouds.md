---
title: 'ADR-0009: Entra ID as the workforce identity provider for all clouds'
doc_type: adr
owner_team: identity-access-management
classification: Internal
system: Microsoft Entra ID
last_reviewed: 2026-08-08
access_groups:
- lm-eng-all
---

# ADR-0009: Entra ID as the workforce identity provider for all clouds

**Status:** Accepted · **Date:** 2025-04-06 · **Deciders:** Domain architect, SRE lead, Chief Architect

## Context

AWS used a separate SSO directory, and Quill used Google identities, so leavers kept access in one cloud for days.

## Decision

Entra ID is the only workforce IdP. AWS IAM Identity Center and Google Cloud are federated to Entra with SCIM provisioning. Group membership in Entra drives permission sets.

## Alternatives considered

- Keep per-cloud directories: rejected.
- Use Google as IdP for Quill only: rejected.

## Consequences

- Leaver deprovisioning completes in all clouds within 1 hour.
- Quill engineers sign in to GCP with their Larkspur identities.
