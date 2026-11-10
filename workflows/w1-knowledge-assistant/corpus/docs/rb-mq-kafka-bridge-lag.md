---
title: MQ-to-Kafka bridge lag
doc_type: runbook
owner_team: integration-engineering
classification: Internal
system: IBM MQ and Amazon MSK
last_reviewed: 2026-07-28
access_groups:
- lm-eng-all
---

# MQ-to-Kafka bridge lag

`mq-kafka-bridge` moves policy events from the LPAS IBM MQ queue `LPAS.POLICY.EVENTS.OUT` to the
MSK topic `lpas.policy-events.v2`. It runs in EKS namespace `mainframe-integration` with 3 replicas.

## Alert

`MqBridgeDepthHigh` fires when the MQ queue depth is above **50,000 messages** for 15 minutes, or
when the bridge has committed nothing to Kafka for 5 minutes.

## Diagnose

```
kubectl -n mainframe-integration logs deploy/mq-kafka-bridge --since=20m | grep -iE 'MQRC|error'
```

- `MQRC 2009` or `2059`: connection to the queue manager `LPQM01` is broken. Check with
  mainframe-operations whether the channel `LPAS.TO.AWS` is running.
- `NOT_ENOUGH_REPLICAS` from Kafka: MSK broker issue; see the MSK runbook.

## Mitigate

1. Restart the bridge: `kubectl -n mainframe-integration rollout restart deploy/mq-kafka-bridge`.
2. Do not scale above 3 replicas; ordering per policy number depends on a single consumer per
   MQ queue partition.
3. During the LPAS batch window (23:00 to 04:30 ET) depth up to 200,000 is normal.
