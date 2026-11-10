---
title: 'Postmortem: WAF blocked broker document uploads'
doc_type: postmortem
owner_team: digital-channels
classification: Internal
system: AWS WAF
last_reviewed: 2026-09-09
access_groups:
- lm-eng-all
---

# Postmortem: WAF blocked broker document uploads

**Severity:** Sev3 · **Incident:** INC0112431 · **Date:** 2026-08-11, 10:23 to 12:07 ET (104 minutes)

## Summary

Brokers could not upload documents larger than 8 KB for 104 minutes.

## Timeline (ET)

- 10:23 impact begins
- 10:29 Broker support tickets.
- 10:31 incident declared, bridge opened
- 12:07 mitigated

## Root cause

A managed rule group version update enabled the body size restriction rule on the upload path.

## Contributing factors

- A similar near miss six months earlier had no action items.
- The change was reviewed by one person outside business hours.

## Action items

| Ticket | Action | Due |
|---|---|---|
| DIG-1244 | Pin managed rule group versions and test updates in staging. | 2026-09-25 |
| DIG-2172 | Scope-down statement excludes the upload path from size rules. | 2026-10-10 |
