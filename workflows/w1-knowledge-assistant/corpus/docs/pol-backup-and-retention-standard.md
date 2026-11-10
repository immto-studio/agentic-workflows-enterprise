---
title: Backup and retention standard
doc_type: policy
owner_team: sre-core
classification: Internal
system: AWS Backup
last_reviewed: 2026-10-16
access_groups:
- lm-eng-all
---

# Backup and retention standard

**Effective:** 2026-10-06 · **Approved by:** Chief Risk Officer · **Review cycle:** yearly

## Purpose

Sets backup frequency, retention and restore testing by tier.

## Rules

1. Tier 1: continuous backup with point-in-time recovery for 35 days, daily copies to us-west-2, vault lock enabled.
2. Tier 2: daily backups kept 35 days.
3. Policy records are retained for 7 years after policy expiry; claims records 10 years after closure.
4. Restores are tested quarterly for tier 1 and yearly for tier 2, with results in the service catalogue.

## Exceptions

Exceptions are requested in ServiceNow (catalogue item **Policy exception**) and approved by sre-core for up to 90 days.
