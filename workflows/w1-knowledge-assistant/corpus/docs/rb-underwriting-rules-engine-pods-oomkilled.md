---
title: underwriting-rules-engine pods OOMKilled
doc_type: runbook
owner_team: policy-engineering
classification: Internal
system: Amazon EKS
last_reviewed: 2026-06-26
access_groups:
- lm-eng-all
---

# underwriting-rules-engine pods OOMKilled

**Service:** `underwriting-rules-engine` · **Platform:** Amazon EKS · **Owner:** policy-engineering · **Alert:** `UwRulesOomKilled`

## When to use this runbook

The alert fires when `underwriting-rules-engine` containers are OOMKilled more than 4 times in 15 minutes. Reports may reach #ops-announce before the alert does; check there for context.

## Before you start

- Acknowledge the page in ServiceNow On-Call and join the incident bridge from the incident record.
- `aws eks update-kubeconfig --name lm-prod-use1-02 --region us-east-1` (production clusters are read-only for engineers; mutating commands need the `lm-prod-operator` role)

## Diagnose

1. `kubectl -n uw-prod get pods -l app=underwriting-rules-engine -o wide`
2. Check JVM heap on the **Underwriting / JVM** dashboard; heap at the 3 GiB limit after a rules publish means the new rule set is larger.
3. Find the last rules publish: `index=eks_prod app=underwriting-rules-engine "ruleset loaded" earliest=-2h | table _time version`

## Mitigate

1. Pin the previous rule set: `kubectl -n uw-prod set env deploy/underwriting-rules-engine RULESET_VERSION=<previous>`
2. Do not raise the memory limit above 4 GiB without Policy Engineering; the node pool is sized for it.

## Verify

- `UwRulesOomKilled` resolves in Grafana and stays clear for 30 minutes.
- Post a short summary in the incident: what you saw, what you changed, the time it recovered.

## Escalate

If the alert is not mitigated within 45 minutes, declare a Sev2 incident if none is open and page the owning team's secondary through assignment group `LM-Policy-Eng`.

## History

- 2026-01-01: first version.
- 2026-06-26: reviewed after a game day; commands re-tested.
