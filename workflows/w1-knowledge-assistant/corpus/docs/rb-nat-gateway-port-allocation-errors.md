---
title: NAT gateway port allocation errors
doc_type: runbook
owner_team: network-engineering
classification: Internal
system: Amazon VPC
last_reviewed: 2026-01-15
access_groups:
- lm-eng-all
---

# NAT gateway port allocation errors

**Service:** `nat-egress` · **Platform:** Amazon VPC · **Owner:** network-engineering · **Alert:** `NatPortAllocationErrors`

## When to use this runbook

The alert fires when `ErrorPortAllocation` on a production NAT gateway is above 10 per minute. Check the service's SLO panel first to see how fast the error budget is burning.

## Before you start

- Acknowledge the page in ServiceNow On-Call and join the incident bridge from the incident record.
- `aws sso login --profile lm-network-readonly`

## Diagnose

1. `aws ec2 describe-nat-gateways --filter Name=tag:env,Values=prod --query 'NatGateways[].[NatGatewayId,SubnetId]'`
2. Find the top talkers with VPC flow logs in Splunk: `index=vpcflow action=ACCEPT dest_port=443 earliest=-15m | stats count by src_ip | sort -count | head 20`

## Mitigate

1. Add a secondary IP to the NAT gateway: `aws ec2 assign-private-nat-gateway-address --nat-gateway-id <id> --private-ip-address-count 1`
2. Move S3 and DynamoDB traffic to gateway endpoints if a service still uses the NAT for them.

## Verify

- `NatPortAllocationErrors` resolves in Grafana and stays clear for 10 minutes.
- Post a short summary in the incident: what you saw, what you changed, the time it recovered.

## Escalate

If the alert is not mitigated within 30 minutes, declare a Sev2 incident if none is open and page the owning team's secondary through assignment group `LM-Network`.

## History

- 2025-01-03: first version.
- 2026-01-15: reviewed after a game day; commands re-tested.
