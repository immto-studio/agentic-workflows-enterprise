---
title: trip-scoring-service latency on GKE
doc_type: runbook
owner_team: quill-data-platform
classification: Internal
system: Google Kubernetes Engine
last_reviewed: 2025-05-02
access_groups:
- lm-eng-all
---

# trip-scoring-service latency on GKE

**Service:** `trip-scoring-service` · **Platform:** Google Kubernetes Engine · **Owner:** quill-data-platform · **Alert:** `TripScoringLatency`

## When to use this runbook

The alert fires when p99 latency of `trip-scoring-service` is above 2000 ms. Reports may reach #ops-announce before the alert does; check there for context.

## Before you start

- Acknowledge the page in ServiceNow On-Call and join the incident bridge from the incident record.
- Sign in with `gcloud auth login` using your Quill federated account.

## Diagnose

1. `gcloud container clusters get-credentials quill-prod-usc1 --region us-central1 --project quill-prod-4821`
2. `kubectl -n scoring top pods -l app=trip-scoring-service`
3. Check the model artifact version in the pod environment: `kubectl -n scoring get deploy trip-scoring-service -o jsonpath='{.spec.template.spec.containers[0].env}'`

## Mitigate

1. Roll back the model version in `quill-gitops/apps/trip-scoring/values-prod.yaml`.
2. Scale out: `kubectl -n scoring scale deploy/trip-scoring-service --replicas=12`

## Verify

- `TripScoringLatency` resolves in Grafana and stays clear for 10 minutes.
- Post a short summary in the incident: what you saw, what you changed, the time it recovered.

## Escalate

If the alert is not mitigated within 30 minutes, declare a Sev3 incident if none is open and page the owning team's secondary through assignment group `LM-Quill-Data`.

## History

- 2025-03-27: first version.
- 2025-05-02: reviewed after a game day; commands re-tested.
