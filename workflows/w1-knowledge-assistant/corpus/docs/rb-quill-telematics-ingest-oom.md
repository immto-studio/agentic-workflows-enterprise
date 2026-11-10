---
title: telematics-ingest pods OOMKilled on GKE
doc_type: runbook
owner_team: quill-data-platform
classification: Internal
system: Google Kubernetes Engine
last_reviewed: 2026-09-15
access_groups:
- lm-eng-all
---

# telematics-ingest pods OOMKilled on GKE

`telematics-ingest` (Quill) receives trip uploads from the mobile app and writes them to Pub/Sub
topic `trips-raw`. It runs on GKE cluster `quill-prod-usc1`, project `quill-prod-4821`, namespace `ingest`.

## Diagnose

```
gcloud container clusters get-credentials quill-prod-usc1 --region us-central1 --project quill-prod-4821
kubectl -n ingest get pods -l app=telematics-ingest
kubectl -n ingest describe pod <pod> | grep -A3 'Last State'
```

`OOMKilled` with exit code 137 usually follows a batch of very long trips from app version 7.2.x,
which uploads a whole trip in one request.

## Mitigate

1. Raise the memory limit from 1 GiB to **2 GiB** through the Helm values in `quill-gitops`
   (`apps/telematics-ingest/values-prod.yaml`, `resources.limits.memory`), not with `kubectl edit`.
2. Confirm the HPA still has headroom: `kubectl -n ingest get hpa telematics-ingest` (max 40 pods).
3. If restarts continue, enable the upload size guard flag `ingest.max_trip_points=200000`.
