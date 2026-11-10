---
title: Encryption standard
doc_type: policy
owner_team: security-engineering
classification: Internal
system: AWS KMS
last_reviewed: 2026-01-02
access_groups:
- lm-eng-all
---

# Encryption standard

**Effective:** 2025-05-21 · **Approved by:** VP Infrastructure · **Review cycle:** yearly

## Purpose

Minimum encryption requirements for data at rest and in transit.

## Rules

1. TLS 1.2 or later for all traffic; TLS 1.3 preferred for new endpoints.
2. Data at rest encrypted with AES-256; Confidential and Restricted data with customer-managed keys.
3. Keys rotate yearly, except PCI keys which follow the PCI key management procedure.
4. Cryptographic libraries come from the platform-provided base images only.

## Exceptions

Exceptions are requested in ServiceNow (catalogue item **Policy exception**) and approved by security-engineering for up to 180 days.
