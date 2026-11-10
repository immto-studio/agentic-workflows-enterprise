---
title: 'ADR-0022: WAF rate limits for the agent portal'
doc_type: adr
owner_team: security-engineering
classification: Confidential
system: AWS WAF
last_reviewed: 2026-05-12
access_groups:
- lm-security-engineering
---

# ADR-0022: WAF rate limits for the agent portal

**Status:** Accepted

## Context

Credential-stuffing attempts against `agents.larkspur-mutual.com` peaked at 1.8 million requests
per hour in March 2026. The previous single rate rule (2,000 requests per 5 minutes per IP) did not
stop distributed attempts.

## Decision

The CloudFront web ACL `lm-agent-portal-prod` uses these rules, in priority order:

1. `/login` and `/api/auth/*`: block above **100 requests per 5 minutes per IP**.
2. Same paths: CAPTCHA challenge above 300 requests per 5 minutes per JA3 fingerprint.
3. All other paths: block above 1,500 requests per 5 minutes per IP.
4. Managed rule groups: core rule set, known bad inputs, IP reputation, bot control (targeted).

The thresholds are confidential because they tell an attacker exactly how fast they can go.
