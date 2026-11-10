# Where AWS, Google Cloud, and Microsoft differ: the eight questions of chapter 16

Chapter 16 asked eight questions of each cloud and prints three of the answers (the bill, what a budget can do, and
committed capacity). This is the whole comparison. It is documentation, not measurement: the lab ran one cloud
session, on AWS, and everything in the Google and Microsoft columns is what the vendors' pages say.

Read between 29 October and 3 November 2026 for the first reading, then checked and corrected on 9 November 2026
against the live pages listed at the end of this file. Where the two readings differ, the second wins. Pages
change; read them again on the day you decide.

| Question | AWS | Google | Microsoft |
|---|---|---|---|
| What the provider keeps of each call | The model invocation log, off until turned on, for calls through the `bedrock-runtime` endpoint: tokens, the caller's `requestMetadata`, the Region of the invocation, and text only if delivery is on; calls through `bedrock-mantle` are not captured. CloudTrail's `additionalEventData.inferenceRegion` names the serving Region for a profile; the lab's log record carried it too, though the schema doesn't list it | Inference request metadata logging, generally available since 30 October 2026: one entry per request with model, Region, tokens, and error code, never the prompt | Metrics by deployment, and API Management's token metric by caller if it is in the path; no per-request log was found |
| Where a trace's content goes by default | Off the spans: the distro moves model payloads out unless `AWS_GENAI_CONTENT_EXTRACTION_OPT_OUT` is true; spans land as logs, 1 percent indexed free | Not in the spans: prompts and responses go to Cloud Storage, which Google recommends, or Cloud Logging, as entries that point to files in a bucket | Seven content attributes in a protected table, `AppGenAIContent`, since 30 September 2026; the opt-out ends 30 September 2027 |
| What the bill can say about one workflow | Tags on an application inference profile and the calling principal reach Cost Explorer; the finest grain is a usage type per day, and `requestMetadata` is never a cost tag | Request labels reach the billing export on pay-as-you-go calls only; Provisioned Throughput ignores them | A `deployment` tag, and project-level attribution in preview; API Management's token metric goes to telemetry, not to the bill |
| What a budget can do | A budget action can attach an IAM policy or a service control policy, automatically or after approval | A spend cap budget can pause the Gemini Enterprise Agent Platform in one project, monthly and on estimated cost, which arrives late; an alerts-only budget caps nothing, and Pub/Sub notifications can feed automation you write | Alerts, evaluated every 24 hours, and a call to an action group that runs automation you write; Azure OpenAI has no hard spend limit |
| What a 429 means | The account's quota was exceeded; a call reserves its prompt plus `max_tokens` up front and settles on use, with output tokens counted at a burndown rate that depends on the model (5, 10, or 15 times for Anthropic models by version, 1 to 1 unless the model's card says otherwise); 503 and 529 are other conditions | On pay-as-you-go, temporary high contention, not a fixed quota; under standard Provisioned Throughput, when use is below the purchased amount, an error that would have been a 429 is returned as a 5XX and counts in the SLA's error rate, and use above it runs on demand (Single Zone Provisioned Throughput's 5XX does not count) | Tokens a minute per subscription, Region, model, and deployment type, counted on actual input and generated tokens with no reservation for `max_tokens`; the answer carries `retry-after-ms`; a failed request still counts against the minute |
| Committed capacity | The Reserved tier, a fixed price per 1,000 tokens a minute for one or three months, from 100,000 input and 10,000 output, arranged through the account team; provisioned model units cover no Claude 4.x or 5.x model | Generative scale units for a week to a year; unused throughput does not accumulate; overflow runs on demand by default | Provisioned throughput units, hourly or reserved for a month or a year; a Regional deployment starts at 50 units for gpt-5.5, the minimum varying by model; spillover to a standard deployment on a 429 |
| Fallback between models | AgentCore Gateway's model fallback, announced 22 October 2026: one or two alternates and a circuit breaker with unpublished thresholds | No native model fallback was found; the guidance is to retry with backoff in your own code | No failover between deployments in Foundry itself; API Management backend pools with circuit breakers, and the model router inside its own model set |
| Notice before a model retires | For a model launched on or after 7 September 2026, a Legacy period of 6 months or 45 days, as its model card says; for older models, at least six months in Legacy; in both, existing customers may lose access after 15 days of inactivity; Claude 5.5 identifiers carry no version | At least 45 days to migrate; a stable model stays at least 12 months; a date is not moved earlier | At least 60 days for a generally available model and 30 for a preview; dates cannot be extended; Claude identifiers carry no version |

## What the chapter did with each answer

- The bill carries no run identifier on any of the three, so the ledger is Larkspur's on every cloud.
- AWS and Google ship a stop (a budget action on an identity; a spend cap on one project's use of the AI platform).
  Microsoft ships the alarm and a hook. On all three the gateway's key is also a stop, and the one whose refusal the
  harness counts as a budget stop.
- Committed capacity is sized in tokens a minute, in normalized tokens, and in scale units, so the lab computed the
  share a workflow fills before it looked at any price (`capacity/calculator.py`).
- A 429 means different things: a reservation that did not fit (AWS), temporary contention (Google, pay-as-you-go),
  or actual tokens over the minute (Microsoft). The key's token limit has to be sized in the provider's units.
- The service level agreements count requests to a model, not runs of a workflow, so none of them stands in for the
  indicators of chapter 16's service levels. Bedrock's page is dated 4 October 2023 and counts only a 500 as an
  error, so a throttled request is outside it.

## Pages read on 9 November 2026

Each address is the page the cells above rest on, with the page's own date where it shows one. The cells of the first
two rows, the bill row's AWS and Microsoft cells, and the fallback row were read between 29 October and 3 November
and found unchanged where the 9 November reading touched them; the book's fact sheet holds their addresses.

AWS (no page shows a date unless noted):

- Token burndown: https://docs.aws.amazon.com/bedrock/latest/userguide/quotas-token-burndown.html
- Model lifecycle, models launched on or after 7 September 2026: https://docs.aws.amazon.com/bedrock/latest/userguide/model-lifecycle.html
- Model lifecycle, models launched before it: https://docs.aws.amazon.com/bedrock/latest/userguide/model-lifecycle-legacy.html
- The Amazon Bedrock service level agreement, last updated 4 October 2023: https://aws.amazon.com/bedrock/sla/
- Model invocation logging: https://docs.aws.amazon.com/bedrock/latest/userguide/model-invocation-logging.html
- Cross-Region inference, where CloudTrail names the serving Region: https://docs.aws.amazon.com/bedrock/latest/userguide/cross-region-inference.html
- AgentCore cross-Region inference: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/cross-region-inference.html
- Service tiers, the Reserved tier: https://docs.aws.amazon.com/bedrock/latest/userguide/service-tiers-inference.html
- Budget actions: https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-controls.html

Google Cloud (last updated, as the page shows):

- Billing budgets, 2026-11-04: https://docs.cloud.google.com/billing/docs/how-to/budgets
- Spend cap budgets, 2026-11-04: https://docs.cloud.google.com/billing/docs/how-to/budgets-spend-caps
- Programmatic budget notifications, 2026-11-04: https://docs.cloud.google.com/billing/docs/how-to/budgets-programmatic-notifications
- Error code 429, 2026-11-07: https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/deploy/error-code-429
- Standard PayGo, 2026-11-07: https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/standard-paygo
- Custom metadata labels, 2026-11-07: https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/capabilities/add-labels-to-api-calls

Microsoft (last updated, as the page shows):

- Manage Azure OpenAI quota, 2026-08-13: https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/quota
- Quotas and limits for Foundry Agent Service, 2026-11-06: https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/limits-quotas-regions
- Create and manage budgets, 2025-06-26: https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-acm-create-budgets
- Plan and manage costs, 2026-10-22: https://learn.microsoft.com/en-us/azure/foundry/concepts/manage-costs
- Model lifecycle and support policy, 2026-07-24: https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-retirements
