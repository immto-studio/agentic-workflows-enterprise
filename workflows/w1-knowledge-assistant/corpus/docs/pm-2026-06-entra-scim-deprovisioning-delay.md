---
title: 'Postmortem: Leavers kept AWS access because SCIM provisioning stalled'
doc_type: postmortem
owner_team: identity-access-management
classification: Internal
system: Microsoft Entra ID
last_reviewed: 2026-07-24
access_groups:
- lm-eng-all
---

# Postmortem: Leavers kept AWS access because SCIM provisioning stalled

**Severity:** Sev3 · **Incident:** INC0105403 · **Date:** 2026-06-24, 07:38 to 08:46 ET (68 minutes)

## Summary

Provisioning to AWS IAM Identity Center stopped for 68 minutes and 9 leavers kept access.

## Timeline (ET)

- 07:38 impact begins
- 07:42 The quarterly access review found the accounts.
- 07:48 incident declared, bridge opened
- 08:46 mitigated

## Root cause

The SCIM token for IAM Identity Center expired; it has a 1-year lifetime and no alert.

## Contributing factors

- The change was reviewed by one person outside business hours.
- A similar near miss six months earlier had no action items.

## Action items

| Ticket | Action | Due |
|---|---|---|
| IAM-2928 | Alert on SCIM provisioning quarantine. | 2026-08-23 |
| IAM-1279 | Calendar the token rotation and store it in Vault. | 2026-08-08 |
