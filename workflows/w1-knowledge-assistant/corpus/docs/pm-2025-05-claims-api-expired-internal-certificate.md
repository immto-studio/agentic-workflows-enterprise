---
title: 'Postmortem: claims-api calls to policy-store failed after an internal certificate expired'
doc_type: postmortem
owner_team: claims-engineering
classification: Internal
system: HashiCorp Vault
last_reviewed: 2025-06-07
access_groups:
- lm-eng-all
---

# Postmortem: claims-api calls to policy-store failed after an internal certificate expired

**Severity:** Sev2 · **Incident:** INC0129425 · **Date:** 2025-05-19, 07:38 to 08:12 ET (34 minutes)

## Summary

Calls from claims-api to policy-store failed TLS verification for 34 minutes.

## Timeline (ET)

- 07:38 impact begins
- 07:47 Synthetic check `claims-policy-lookup` failed; first page at 07:47.
- 07:51 incident declared, bridge opened
- 08:12 mitigated

## Root cause

The intermediate CA `pki_int` was re-issued with a new key, but the trust bundle ConfigMap in `claims-prod` was copied by hand in 2024 and never updated.

## Contributing factors

- The on-call engineer was handling a second incident.
- A similar near miss six months earlier had no action items.

## Action items

| Ticket | Action | Due |
|---|---|---|
| CLM-2217 | Distribute trust bundles with trust-manager instead of copied ConfigMaps. | 2025-07-18 |
| CLM-2607 | Alert 30 days before any CA in the bundle expires. | 2025-06-02 |
