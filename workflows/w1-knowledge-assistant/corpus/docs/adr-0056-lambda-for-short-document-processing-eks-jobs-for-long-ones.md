---
title: 'ADR-0056: Lambda for short document processing, EKS jobs for long ones'
doc_type: adr
owner_team: claims-engineering
classification: Internal
system: AWS Lambda
last_reviewed: 2025-05-13
access_groups:
- lm-eng-all
---

# ADR-0056: Lambda for short document processing, EKS jobs for long ones

**Status:** Proposed · **Date:** 2025-03-17 · **Deciders:** Chief Architect, Principal engineer, SRE lead

## Context

Document processing ran in a mix of Lambda, EKS deployments and EC2 cron jobs.

## Decision

Event-driven processing under 5 minutes and 3 GB of memory runs on Lambda. Anything longer or heavier runs as Kubernetes Jobs triggered by KEDA from SQS.

## Alternatives considered

- Everything on EKS: rejected.
- Step Functions with Fargate: rejected.

## Consequences

- Teams use the lambda-function and sqs-queue modules.
- Cold starts are acceptable for asynchronous work.
