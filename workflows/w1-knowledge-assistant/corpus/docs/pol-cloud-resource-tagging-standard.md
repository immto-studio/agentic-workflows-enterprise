---
title: Cloud resource tagging standard
doc_type: policy
owner_team: finops
classification: Internal
system: AWS, Azure and Google Cloud
last_reviewed: 2025-02-02
access_groups:
- lm-eng-all
---

# Cloud resource tagging standard

**Effective:** 2025-01-10 · **Approved by:** CISO · **Review cycle:** yearly

## Purpose

Makes cost allocation and ownership possible across all clouds.

## Rules

1. Required tags (labels on Google Cloud): `owner_team`, `cost_center`, `env`, `service`, `data_classification`.
2. `env` is one of `prod`, `stg`, `dev`, `sandbox`, `lab`.
3. Untagged resources in non-production accounts are stopped after 7 days and deleted after 30.
4. Tag policies in AWS Organizations and Azure Policy enforce the values; exceptions go through FinOps.

## Exceptions

Exceptions are requested in ServiceNow (catalogue item **Policy exception**) and approved by finops for up to 90 days.
