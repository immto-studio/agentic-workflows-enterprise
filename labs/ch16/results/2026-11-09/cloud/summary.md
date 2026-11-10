# Chapter 16, step 7: the cloud session in us-east-2

Written by `cloud/cloud_summary.py` from the files beside it: one session in the lab account on 9 November 2026, profile `book-lab`, every resource in us-east-2 on synthetic data (book D-034, D-036), the budget first and everything destroyed in the same session. Every number is a measurement; account IDs, access key IDs, principal IDs, user names, addresses, and public IP addresses are replaced in every file here. Timings count seconds with time.perf_counter() on this workstation and stamp moments with its UTC clock.

## The budget (item 1)

|Moment |At (UTC) |Budget |Limit |Actual spend |Notifications |Credits left |
|---|---|---|---|---|---|---|
|start |2026-11-09T09:37:59 |ch16-cloud-session |5.0 USD a month |0.0 USD |80% ACTUAL, OK, SNS sns-topic; 100% ACTUAL, OK, SNS sns-topic |139.38 USD (FREE, ACTIVE) |
|end |2026-11-09T10:07:04 |ch16-cloud-session |5.0 USD a month |0.0 USD |80% ACTUAL, OK, SNS sns-topic; 100% ACTUAL, OK, SNS sns-topic |159.38 USD (FREE, ACTIVE) |

## Transaction Search (item 2)

|Step |What AWS answered |Seconds |
|---|---|---|
|on: resource policy |put as TransactionSearchAccess |0.3 |
|on: destination to CloudWatchLogs |CloudWatchLogs PENDING |1.3 |
|on: destination ACTIVE |still PENDING after 37 readings |182.6 |
|on: indexing rule after the switch |0.0 percent | |
|on: indexing rule set |1.0 percent, the page's default |182.7 |
|status at 09:46:42 UTC |CloudWatchLogs ACTIVE, indexing 1.0 percent, aws/spans present (0 bytes stored) | |
|status at 10:08:05 UTC |XRay PENDING, indexing 0.0 percent, aws/spans absent | |
|status at 10:10:40 UTC |XRay ACTIVE, indexing 0.0 percent, aws/spans absent | |
|off: destination to XRay |XRay PENDING |0.3 |
|off: destination XRay ACTIVE |not reached after 37 readings |181.7 |
|off: resource policy |deleted |182.0 |
|off: aws/spans |deleted |182.0 |
|off: /aws/application-signals/data |deleted |182.1 |
|off: indexing rule restored |0.0 percent, as before the session |182.2 |

|Setting |Before the session |After `on` |After `off` |
|---|---|---|---|
|Trace segment destination |XRay ACTIVE |CloudWatchLogs PENDING |XRay PENDING |
|Default indexing rule (percent) |0.0 |1.0 |0.0 |
|Resource policy TransactionSearchAccess |no |yes |no |
|Log group aws/spans |no |yes |no |
|Log group /aws/application-signals/data |no |yes |no |

|While on, AWS bills |Quote |Source, date |
|---|---|---|
|span ingestion |$0.35 per GB of Application Signals data ingested for the first 10TB - US East (Ohio) |fact sheet 8.8, AmazonCloudWatch offer file for us-east-2, 2026-11-03 |
|spans indexed as trace summaries |$0.00000075 per spans indexed for USE2-XRay-Spans-Indexed in US East (Ohio); By default you will also index 1% of ingested spans for free as trace summary |fact sheet 8.8 and 8.2, 2026-11-03 |

## The live run through the Collector (items 2 and 7)

|Runs |Passed |Traces |Spans sent |Left the Collector |In the span file |Traces with every span left |Share of the rest |decision_wait |Collector exit |Error or warning lines in its log |
|---|---|---|---|---|---|---|---|---|---|---|
|25 |25 |25 |257 |257 |257 |25 of 25 |100.0% |30 s |0 |0 |

### CloudWatch

|Traces expected |Group seen after (s) |Traces seen |Traces complete |Spans found / sent |Events not the run's |First reading (s after the poll began) |Traces complete at the first reading |Had left the Collector (s) before it, min / median / max |ingestionTime minus the span's start (s), min / median / max |
|---|---|---|---|---|---|---|---|---|---|
|25 |0.3 |25 |25 |257 / 257 |0 |0.7 |25 |2.6 / 27.6 / 38.6 |31.4 / 32.4 / 34.8 |

|Record keys |Field that holds the trace id |X-Ray trace summaries in the window |Of them, the run's |Indexing rule (percent) |Application Signals services |Logs Insights query |Rows |Bytes scanned |Records matched |
|---|---|---|---|---|---|---|---|---|---|
|attributes, durationNano, endTimeUnixNano, flags, kind, name, parentSpanId, resource, scope, spanId, startTimeUnixNano, status, traceId |traceId |0 |0 |1.0 |none |Complete |25 |309,817 |257 |

### Langfuse

|Langfuse |Traces expected |Seen |Complete |First reading (s after the poll began) |Traces complete at the first reading |Had left the Collector (s) before it, min / median / max |Traces with every span id |Gateway spans with a cost |Cost equal to gen_ai.usage.cost |Tokens equal |Tracestate anywhere |Span attributes kept as metadata |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
|4.74.0 |25 |25 |25 |2.1 |25 |1.7 / 26.7 / 37.7 |25 of 25 |45 |45 |45 |no |yes |

|Observation types |Count |
|---|---|
|AGENT |25 |
|GENERATION |48 |
|SPAN |121 |
|TOOL |63 |

### The VM

|Instance type |Ready after launch (s) |Image pull (s) |`up` to healthy (s) |Langfuse health |Pinned tags |Docker |Compose |Cores |Memory (MB) |Tunnel |
|---|---|---|---|---|---|---|---|---|---|---|
|m7i-flex.large |119.0 |40 |25 |{"status": "OK", "version": "4.74.0"} |pinned |29.1.3, build 29.1.3-0ubuntu3~24.04.2 |2.40.3+ds1-0ubuntu1~24.04.1 |2 |7776 |open-tunnel to port 22, ssh -L 3000 |

|Image |Digest |
|---|---|
|redis:7 |sha256:2e3eb11462c4... |
|cgr.dev/chainguard/minio:latest |sha256:a1ac4589a5f8... |
|docker.langfuse.com/langfuse/langfuse-worker:4.74.0 |sha256:d9cf97c0ae7d... |
|clickhouse/clickhouse-server:26.3.62.3 |sha256:de3e47c64078... |
|docker.langfuse.com/langfuse/langfuse:4.74.0 |sha256:f409386b80aa... |
|postgres:17 |sha256:ff87138949ad... |

## Bedrock with the trace id in requestMetadata (items 3 and 4)

|Call |Path |Answered |Tokens in / out |Gateway cost (USD) |Cost lines / spans |Invocation record |Record after the call (s) |requestMetadata in the record |Text fields |inferenceRegion in the record |
|---|---|---|---|---|---|---|---|---|---|---|
|Canada profile, chapter 5's W3 manifest, regions [ca-central-1] |gateway, litellm.bedrock-ca.yaml, W3 larkspur-chat (confidential), called in ca-central-1 |no: 400 request refused: 'larkspur-chat' serves from ca-west-1, outside the regions of 'w3-incident' |none / none |none |1 / 0 |not readable here (ca-central-1) | | | | |
|Canada profile, chapter 6's W3 manifest, regions [ca-central-1, ca-west-1] |gateway, litellm.bedrock-ca.yaml, W3 larkspur-chat (confidential), called in ca-central-1 |yes |99 / 2 |0.000007 |2 / 1 |not readable here (ca-central-1) | | | | |
|In-Region us-east-2, text delivery off |gateway, litellm.bedrock-us.yaml, W2 larkspur-chat (internal), Nova Lite In-Region us-east-2 |yes |99 / 2 |0.000006 |1 / 1 |found |12.2 |{"workflow": "w2-ops-assistant", "trace_id": "280e7796708b45d0b8b1eafa04a57511"} |none |absent |
|In-Region us-east-2, text delivery on |gateway, litellm.bedrock-us.yaml, W2 larkspur-chat (internal), Nova Lite In-Region us-east-2 |yes |99 / 2 |0.000006 |1 / 1 |found |11.4 |{"workflow": "w2-ops-assistant", "trace_id": "bfd8a29fb80447f5bf1ceb2899434154"} |inputBodyJson, outputBodyJson |absent |
|US profile from us-east-2 (SDK) |the SDK's Converse in us-east-2 on us.amazon.nova-lite-v1:0, with the same requestMetadata |yes |8 / 3 |none |SDK call |found |11.3 |{"workflow": "w2-ops-assistant", "trace_id": "21e37613001e4962af4e937a4d9d9daa"} |inputBodyJson, outputBodyJson |us-west-2 |

|ca-central-1, anything but a model call |Answer |
|---|---|
|get logging configuration |refused (AccessDeniedException) |
|describe log groups |refused (AccessDeniedException) |
|cloudtrail lookup |refused (AccessDeniedException) |

### CloudTrail, us-east-2

|Call |Event found |awsRegion |inferenceRegion (CloudTrail) |inferenceRegion (log) |Request ID equals the log's |Event name |
|---|---|---|---|---|---|---|
|us text off |yes |us-east-2 |absent |absent |yes |Converse |
|us text on |yes |us-east-2 |absent |absent |yes |Converse |
|us profile |yes |us-east-2 |us-west-2 |us-west-2 |yes |Converse |

Polled for 0.7 s; 3 Converse or InvokeModel events in the window.

## The tool role with the trace id (item 5)

|Check |Result |
|---|---|
|AssumeRole with the trace id tag and the session name |allowed; session `3f2b9c1e-6a4d-4e8b-9c7f-1a2b3c4d5e6f.5de3012d83cd461e`; 0.317 s |
|One read under it (ec2:DescribeInstances) |answered; 0.344 s |
|AssumeRole with no trace_id tag |refused (AccessDenied) |
|AssumeRole with chapter 6's session name, the object ID alone |refused (AccessDenied) |
|AssumeRole with a tag key the policy doesn't list |refused (AccessDenied) |
|AssumeRole with a trace id of the wrong length |refused (AccessDenied) |

### CloudTrail, us-east-2

|Event |Seen after the call (min) |Event time |
|---|---|---|
|AssumeRole |4.4 |2026-11-09T10:02:10Z |
|DescribeInstances |4.4 |2026-11-09T10:02:10Z |

|Events of the two sessions |AssumeRole |DescribeInstances |With userIdentity.accessKeyId |Denied (errorCode) |AssumeRole with the trace_id tag |Polled (s) |
|---|---|---|---|---|---|---|
|23 |2 |21 |23 |9 |2 |0.6 |

### join.py

|Store |Records |
|---|---|
|harness log |3 |
|tool server log |1 |
|gateway cost lines |2 |
|spans |11 |
|CloudTrail |13 |

CloudTrail's events matched by: AssumeRole, session tag trace_id, role session name in userIdentity.arn. From one DescribeInstances event back to its run: 1 trace id.

## The deny-all (item 6)

|Step |Seconds |Detail |
|---|---|---|
|`identity.py pull` answered by IAM |0.151 |1 role; policy larkspur-kill-switch put |
|calls that still passed after the pull |9 |one read every 0.5 s |
|first AccessDenied on credentials already issued |8.232 |code UnauthorizedOperation |
|`identity.py release` answered by IAM |0.159 |revoke statement alone, cut-off at the release |
|a session issued after the release |0.042 |issued |
|its first successful read |8.197 |7 refusals before it |
|the earlier session after the release | |still refused (UnauthorizedOperation) |
|`release --purge` |0.161 |deleted; the later session then reads |

The clock: time.perf_counter() for intervals and datetime.now(timezone.utc) for stamps, both on this workstation.

## Cost Explorer (item 8)

Answered under the filter `product attribute model = Nova Lite` (1 request(s)); usage types: CAN1-NovaLite-input-tokens, CAN1-NovaLite-output-tokens, USE2-NovaLite-input-tokens, USE2-NovaLite-output-tokens; cost in the window 0 USD.

|Day (the bill's, UTC; the ledger's, Toronto) |Bill's usage types |Bill input tokens |Bill output tokens |Bill cost (USD) |Ledger calls |Ledger tokens in / out |Ledger cost (USD) |
|---|---|---|---|---|---|---|---|
|2026-10-29 |none |0 |0 |0 |48 |81,439 / 4,260 |0.006303 |
|2026-10-30 |CAN1-NovaLite-input-tokens, CAN1-NovaLite-output-tokens, USE2-NovaLite-input-tokens, USE2-NovaLite-output-tokens |88,246 |8,214 |0 |0 |0 / 0 |0 |

|Bill day (UTC) |Ledger day (Toronto) |Usage types |Bill tokens in / out |Ledger tokens in / out |Ledger calls |Bill over ledger, input |Bill over ledger, output |Bill cost (USD) |Bill at the table's price (USD) |Ledger cost (USD) |At list price, bill over ledger |
|---|---|---|---|---|---|---|---|---|---|---|---|
|2026-10-30 |2026-10-29 |CAN1-NovaLite-input-tokens, CAN1-NovaLite-output-tokens |88,240 / 8,211 |81,439 / 4,260 |48 |1.084 |1.927 |0 |0.007749 |0.006303 |1.229 |

The ledger's Nova Lite lines: 2026-10-29: 48 calls, 81,439 in, 4,260 out, 0.006303 USD, priced at nova-lite-ca (0.064 / 0.256 USD per million tokens, 2026-10-29).

## Teardown (item 9)

|Terraform |At (UTC) |Seconds |Result |
|---|---|---|---|
|vm destroy |2026-11-09T10:01:17 |36 |terraform destroy -target=aws_instance.langfuse; instance states after: ['terminated'] |
|destroy |2026-11-09T10:11:00 |20 |Destroy complete! Resources: 22 destroyed |

|cloud/leftovers.py, after the destroy |Found |
|---|---|
|instances_not_terminated |[] |
|volumes |0 |
|elastic_ips_allocated |0 |
|vpcs |0 |
|instance_connect_endpoints |[] |
|iam_roles |{"w3-incident-get-pod-status": {"exists": false}, "ch16-cloud-invocation-logging": {"exists": false}} |
|log_groups |{"/aws/bedrock/model-invocations-ch16": "absent", "aws/spans": "absent", "/aws/application-signals/data": "absent"} |
|other_log_groups |[] |
|invocation_logging |false |
|xray_destination |{"Destination": "XRay", "Status": "PENDING"} |
|xray_indexing_percent |[["Default", 0.0]] |
|logs_resource_policies |[] |
|budgets |[] |
|sns_topics |[] |

|tools/cloudcheck/aws_sweep.py |Found |
|---|---|
|plan |FREE ACTIVE | credits left: {'amount': 159.38, 'unit': 'USD'} | expires: 2027-04-28 |
|EC2 instances not terminated |0 |
|NAT gateways available |0 |
|Elastic IPs |0 |
|VPCs besides the default |0 |
|VPC interface endpoints |0 |
|EBS volumes |0 |
|load balancers |0 |
|EKS clusters |[] |
|RDS instances |0 |
|ECS clusters |0 |
|AgentCore runtimes |[] |
|Bedrock provisioned throughputs |0 |
|SageMaker endpoints |0 |
|OpenSearch domains |0 |
|Secrets Manager secrets |0 |
|customer KMS keys by state |{'PendingDeletion': 4} |
|S3 buckets |0 |
|CloudWatch log groups, stored MB |0.0 |
|budgets |[] |

## The spend estimate, at list price

|Service |Quantity |Price |Source, date |Estimate (USD) |
|---|---|---|---|---|
|EC2, the Langfuse VM |0.256 instance hours of m7i-flex.large |$0.09576 per On Demand Linux m7i-flex.large Instance Hour |fact sheet 8.8 (ledger/prices.yaml), read 2026-11-03 |0.0245 |
|EBS, its gp3 disk |30 GiB for 0.256 hours |$0.08 per GB-month of General Purpose (gp3) provisioned storage - US East (Ohio) |fact sheet 8.8 (ledger/prices.yaml), read 2026-11-03 |0.000842 |
|Public IPv4 address |0.256 hours |$0.005 per In-use public IPv4 address per hour |fact sheet 8.8 (ledger/prices.yaml), read 2026-11-03 |0.00128 |
|CloudWatch, spans ingested |257 spans at about 1000 bytes each (the pricing page's own assumption) |$0.35 per GB of Application Signals data ingested for the first 10TB - US East (Ohio) |fact sheet 8.8 (ledger/prices.yaml), read 2026-11-03 |0.00009 |
|CloudWatch, spans indexed |0 of the run's traces indexed, inside the free 1 percent |$0.00000075 per spans indexed for USE2-XRay-Spans-Indexed in US East (Ohio) |fact sheet 8.8 (ledger/prices.yaml), read 2026-11-03 |0 |
|CloudWatch Logs Insights |309,817 bytes scanned |$0.005 per GB log data scanned by CloudWatch Logs Insights queries - US East (Ohio) |fact sheet 8.8 (ledger/prices.yaml), read 2026-11-03 |0.000002 |
|Bedrock, Nova Lite in us-east-2 |412 input and 14 output tokens, the first run's 3 calls included |$0.00006 per 1K tokens for Nova Lite-input-tokens in us-east-2 (Ohio) |fact sheet 8.8 (ledger/prices.yaml), read 2026-11-03 |0.000028 |
|Bedrock, Nova Lite through the Canada profile |99 input and 2 output tokens |$0.000064 per 1K tokens for CAN1-NovaLite-input-tokens in Canada (Central) |fact sheet 8.8 (ledger/prices.yaml), read 2026-11-03 |0.000007 |
|Cost Explorer API |1 request(s) |$0.01 per API Request |fact sheet 8.8 (ledger/prices.yaml), read 2026-11-03 |0.0100 |
|EC2 Instance Connect endpoint |one endpoint |no charge (fact sheet 8.6: "There is no additional cost for using EC2 Instance Connect Endpoints.") | |not priced |
|AWS Budgets, SNS, IAM, STS, CloudTrail event history, the VPC, the invocation log's records |one budget, one topic, two roles, the lookups, three records |no entry in the dated table | |not priced |
|Total of the priced lines | | | |0.0368 |
