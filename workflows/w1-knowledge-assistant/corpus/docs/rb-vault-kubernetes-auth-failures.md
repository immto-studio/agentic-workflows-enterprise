---
title: Vault Kubernetes auth failures
doc_type: runbook
owner_team: security-engineering
classification: Internal
system: HashiCorp Vault
last_reviewed: 2026-05-20
access_groups:
- lm-eng-all
---

# Vault Kubernetes auth failures

**Service:** `vault-prod` · **Platform:** HashiCorp Vault · **Owner:** security-engineering · **Alert:** `VaultK8sAuthErrors`

## When to use this runbook

The alert fires when Vault `auth/kubernetes/login` errors are above 50 per minute. Impact is usually internal at first and can become customer-facing after about 30 minutes.

## Before you start

- Acknowledge the page in ServiceNow On-Call and join the incident bridge from the incident record.
- `vault login -method=oidc role=sre-oncall`

## Diagnose

1. `vault read auth/kubernetes-<cluster>/config` and confirm `kubernetes_host` matches the cluster endpoint.
2. `kubectl -n vault logs vault-0 --since=15m | grep -i 'permission denied'`
3. After an EKS upgrade the service account token issuer can change; compare `issuer` with `kubectl get --raw /.well-known/openid-configuration | jq .issuer`.

## Mitigate

1. Update the auth backend issuer through `vault-config` Terraform (`modules/k8s-auth`), not by hand.
2. Pods keep their current tokens until expiry; only new pods fail, so pause rollouts in the affected cluster.

## Verify

- `VaultK8sAuthErrors` resolves in Grafana and stays clear for 30 minutes.
- Post a short summary in the incident: what you saw, what you changed, the time it recovered.

## Escalate

If the alert is not mitigated within 20 minutes, declare a Sev3 incident if none is open and page the owning team's secondary through assignment group `LM-SecEng`.

## History

- 2025-12-30: first version.
- 2026-05-20: reviewed after a game day; commands re-tested.
