---
title: 'ADR-0004: Application secrets in AWS Secrets Manager'
doc_type: adr
owner_team: platform-engineering
classification: Internal
system: AWS Secrets Manager
last_reviewed: 2025-01-22
access_groups:
- lm-eng-all
---

# ADR-0004: Application secrets in AWS Secrets Manager

**Status:** Accepted

## Decision

Services on AWS store database credentials and API keys in AWS Secrets Manager, one secret per
service per environment, named `/<env>/<service>/<purpose>`. Rotation uses the Secrets Manager
rotation Lambda every 90 days. Pods read secrets through the Secrets Store CSI driver.

## Consequences

Vault remains for PKI only.
