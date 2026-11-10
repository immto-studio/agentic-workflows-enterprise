---
title: 'Postmortem: billing-gateway outage from Aurora connection exhaustion'
doc_type: postmortem
owner_team: billing-engineering
classification: Internal
system: Amazon Aurora PostgreSQL
last_reviewed: 2026-02-04
access_groups:
- lm-eng-all
---

# Postmortem: billing-gateway outage from Aurora connection exhaustion

**Severity:** Sev1 · **Incident:** INC0113071 · **Date:** 2026-01-26, 08:47 to 09:58 ET (71 minutes)

## Summary

Policyholders could not make payments online or by phone for 71 minutes on the first business day
after the January billing run.

## Root cause

The January deploy of `billing-gateway` raised the HikariCP pool size from 20 to 60 per pod. When
the HPA scaled to 18 pods for the Monday morning peak, the application asked for 1,080 connections
against `billing-aurora-prod`, whose `max_connections` is 1,000. New connections failed and
health checks timed out, so pods restarted and made it worse.

## Actions

- BILL-771: put RDS Proxy `billing-proxy-prod` in front of the cluster with `max_connections_percent = 75` (done).
- BILL-772: pool size back to 20 and a CI check that pool size x HPA max fits the database (done).
- BILL-775: readiness probe no longer opens a database connection.
