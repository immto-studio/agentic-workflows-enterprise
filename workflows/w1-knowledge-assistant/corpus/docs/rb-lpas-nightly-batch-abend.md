---
title: LPAS nightly batch abend
doc_type: runbook
owner_team: mainframe-operations
classification: Internal
system: LPAS mainframe
last_reviewed: 2026-06-23
access_groups:
- lm-eng-all
---

# LPAS nightly batch abend

The LPAS nightly batch runs from **23:00 to 04:30 ET**. Renewals (`LPB0420`), billing extract
(`LPB0610`) and the data warehouse feed (`LPB0900`) must finish before online CICS regions open at 05:00.

## If a job abends

1. Mainframe operations is the first responder; the platform on-call is paged only if a downstream
   AWS consumer is affected.
2. `S0C7` in `LPB0420` is almost always a bad packed-decimal premium field from a policy endorsed
   that day. Operations restart the job from step `STEP040` after moving the bad record to the
   suspense file `LPAS.PROD.RENEW.SUSPENSE`.
3. If `LPB0610` has not finished by 03:30 ET, page Billing Engineering: the billing run on AWS
   (`billing-run-prod` Step Functions state machine) starts at 05:15 and reads the extract from
   `s3://lm-lpas-extracts-prod/billing/`.

## Check the S3 handoff

```
aws s3 ls s3://lm-lpas-extracts-prod/billing/$(date +%Y/%m/%d)/
```

The file `_SUCCESS` marks a complete extract.
