---
title: Logging standard
doc_type: policy
owner_team: observability
classification: Internal
system: Splunk
last_reviewed: 2026-04-19
access_groups:
- lm-eng-all
---

# Logging standard

**Effective:** 2025-08-17 · **Approved by:** General Counsel · **Review cycle:** yearly

## Purpose

Defines what applications log and what they must never log.

## Rules

1. Logs are structured JSON with `timestamp`, `level`, `service`, `trace_id` and `message`.
2. Never log passwords, tokens, full card numbers, Social Security numbers, or full dates of birth.
3. Policy and claim numbers may be logged; policyholder names and addresses may not.
4. Production log level is INFO; DEBUG is enabled per pod and expires after 4 hours.

## Exceptions

Exceptions are requested in ServiceNow (catalogue item **Policy exception**) and approved by observability for up to 90 days.
