---
title: GitHub Actions self-hosted runners not picking up jobs
doc_type: runbook
owner_team: developer-platform
classification: Internal
system: GitHub Actions
last_reviewed: 2026-09-02
access_groups:
- lm-eng-all
---

# GitHub Actions self-hosted runners not picking up jobs

Self-hosted runners for GitHub Enterprise (`github.larkspur.internal`) run as Actions Runner
Controller scale sets in EKS cluster `lm-tools-use1-01`, namespace `arc-runners`. Labels:
`lm-linux-x64`, `lm-linux-arm64`, `lm-docker`.

## Symptoms

Jobs sit in "Waiting for a runner" for more than 5 minutes; the Grafana panel
**CI / Pending jobs by label** is above 20.

## Diagnose

```
kubectl -n arc-systems logs deploy/arc-gha-rs-controller --since=15m | grep -iE 'error|rate limit'
kubectl -n arc-runners get autoscalingrunnersets
kubectl -n arc-runners get ephemeralrunners | grep -v Running | head
```

A `403 rate limit exceeded` in the controller log means the GitHub App token is throttled.

## Mitigate

1. Restart the listener for the affected scale set:
   `kubectl -n arc-systems delete pod -l app.kubernetes.io/component=runner-scale-set-listener,actions.github.com/scale-set-name=lm-linux-x64`
2. If runners are pending because of capacity, check Karpenter: `kubectl get nodeclaims | grep arc`.
3. The scale set maximum is 120 runners for `lm-linux-x64`; raising it is a change to
   `platform-gitops/arc/values-prod.yaml`, not a manual edit.
