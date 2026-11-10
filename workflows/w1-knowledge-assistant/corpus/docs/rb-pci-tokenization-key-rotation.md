---
title: Rotating the PCI tokenization KMS key
doc_type: runbook
owner_team: billing-engineering
classification: Restricted
system: AWS KMS
last_reviewed: 2026-04-21
access_groups:
- lm-pci-cde-operators
---

# Rotating the PCI tokenization KMS key

The card-tokenization service `payments-tokenizer` (account `lm-pci-cde-prod`) encrypts the
token vault with the customer-managed key `alias/lm-pci-tokenization-prod`. PCI DSS requirement
3.7 and our key management standard require rotation every **180 days**, or immediately after a
suspected compromise.

## Dual control

Rotation is a **dual-control** operation: two members of `lm-pci-cde-operators` must be present,
one from Billing Engineering and one from Security Engineering. The first creates the new key
version; the second approves the alias switch in the change record. Neither may perform both steps.

## Steps

1. Raise a standard change in ServiceNow using template **PCI-KMS-ROTATE**.
2. Operator A creates the new key and grants the tokenizer role:

   ```
   aws kms create-key --description "lm-pci-tokenization-prod $(date +%Y-%m)" \
     --key-usage ENCRYPT_DECRYPT --origin AWS_KMS --tags TagKey=pci-scope,TagValue=cde
   aws kms create-grant --key-id <new-key-id> \
     --grantee-principal arn:aws:iam::<cde-account>:role/payments-tokenizer-prod \
     --operations Encrypt Decrypt GenerateDataKey
   ```

3. Operator B approves the change, then switches the alias:

   ```
   aws kms update-alias --alias-name alias/lm-pci-tokenization-prod --target-key-id <new-key-id>
   ```

4. Run the re-wrap job `tokenizer-rewrap` (EKS namespace `cde-payments`); it re-encrypts data keys
   at about 40,000 tokens per minute. The old key stays enabled for 30 days, then is scheduled for
   deletion with a 30-day window.

## Evidence for the QSA

Export the CloudTrail events `CreateKey`, `CreateGrant` and `UpdateAlias` for the change window
to `s3://lm-pci-evidence-prod/kms/` and attach the change record.
