---
title: Privileged access review standard
doc_type: policy
owner_team: identity-access-management
classification: Confidential
system: Microsoft Entra ID
last_reviewed: 2026-05-28
access_groups:
- lm-iam-admins
---

# Privileged access review standard

## Scope

Entra ID roles (Global Administrator, Privileged Role Administrator, Conditional Access
Administrator), AWS IAM Identity Center permission sets `AdministratorAccess` and `BreakGlass`,
GCP `roles/owner`, Vault policies `admin` and `root-recovery`, and conditional access exclusion groups.

## Rules

1. Privileged roles are eligible, not active, and are activated just in time for at most **4 hours**.
2. Activation of Global Administrator requires approval from two members of `lm-iam-admins`.
3. Reviews run quarterly in Entra ID Governance; reviewers who do not respond within 10 business days
   cause automatic removal.
4. The two break-glass Entra accounts (`bg-admin-01`, `bg-admin-02`) are excluded from MFA conditional
   access, use FIDO2 keys stored in the Hartford safe, and alert the SOC on every sign-in.
