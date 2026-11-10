---
title: Jenkins controller disk almost full
doc_type: runbook
owner_team: developer-platform
classification: Internal
system: Jenkins
last_reviewed: 2026-06-09
access_groups:
- lm-eng-all
---

# Jenkins controller disk almost full

**Service:** `jenkins-controller` · **Platform:** Jenkins · **Owner:** developer-platform · **Alert:** `JenkinsDiskHigh`

## When to use this runbook

The alert fires when the `/var/lib/jenkins` volume on `jenkins-ctl-01` is above 90% used. Reports may reach #ops-announce before the alert does; check there for context.

## Before you start

- Acknowledge the page in ServiceNow On-Call and join the incident bridge from the incident record.
- Use your Jenkins API token from Vault at `secret/ci/jenkins/<your-user>`.

## Diagnose

1. `aws ssm start-session --target <instance-id>` then `du -sh /var/lib/jenkins/jobs/*/builds | sort -h | tail`
2. Jobs without a build discarder are the usual cause.

## Mitigate

1. Apply the build discarder (keep 30 builds, 14 days) through the job DSL seed job, then run `Discard old builds` from the script console.
2. Grow the EBS volume online: `aws ec2 modify-volume --volume-id <vol> --size 750` and `xfs_growfs /var/lib/jenkins`.

## Verify

- `JenkinsDiskHigh` resolves in Grafana and stays clear for 10 minutes.
- Post a short summary in the incident: what you saw, what you changed, the time it recovered.

## Escalate

If the alert is not mitigated within 30 minutes, declare a Sev3 incident if none is open and page the owning team's secondary through assignment group `LM-DevPlatform`.

## History

- 2025-03-26: first version.
- 2026-06-09: reviewed after a game day; commands re-tested.
