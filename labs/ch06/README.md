# Lab, chapter 6: the skeleton on Amazon Bedrock AgentCore

Chapter 6 deploys the chapter 5 skeleton on Amazon Bedrock AgentCore Runtime in ca-central-1, for
Larkspur's incident workflow, and builds the identities its manifest implies. Nothing here needs an
AWS account to validate. On 30 October 2026 the Terraform was applied on synthetic data in a
sandbox account that may create resources only in us-east-2, with the stand-ins of `sandbox/`
(book D-036), and destroyed; `results/2026-10-30/` holds what it found. On 2 November 2026 it was
applied there again with the author's four Entra registrations, two MCP stand-ins behind a private
load balancer, and one invocation from inside the VPC, and destroyed; `results/2026-11-02/` holds
what that run settled, and the section "What the sandbox applies settled" below tells it. Larkspur's
own deployment stays in ca-central-1: the `region` variable refuses any other Region unless
`synthetic_data`.

- Part 1 is the Terraform: the budget first; the runtime in a private VPC, behind Entra, with its
  execution role, a permission boundary, a named endpoint and a resource policy; the endpoints it
  needs without internet access; the tool gateway (AgentCore Gateway with IAM authorization, a
  policy engine in ENFORCE mode, its own Entra credential for the MCP servers, and a resource
  policy); the runbook Knowledge Base on S3 Vectors; the workflow's key for the stores fixed at
  creation; a guardrail whose Standard tier evaluates in Canada; and model invocation logging.
  `terraform validate`, an offline plan of 76 resources and fifteen policy tests check it.
- Part 2 is the module chapter 4 promised. `terraform/modules/manifest_roles` turns a workflow
  manifest and the platform's tool catalog into a role per tool and the workflow's invoke scopes
  as Cedar permits. `pipeline/scope_check.py` refuses a manifest or catalog change that grows a
  workflow's scope without a change record. Nine plan-based tests and twenty-three check tests.
  `org/scp.json` is the service control policy the chapter describes, with five tests.
- Part 3 is the harness image: chapter 7's entry point with `RUNTIME=agentcore`, built for
  linux/arm64. The gateway key comes from AgentCore Identity's token vault, the MCP requests are
  signed for the tool gateway, the gateway's tool names are mapped back to the tools' own, and a
  session serves only the engineer its ID names. Nineteen tests, in chapter 5's environment.

```
terraform/                part 1
  versions.tf             hashicorp/aws 6.71.0; the provider's default tags name the workflow and its owner
  main.tf                 the manifest and the catalog, read once; names; the data class every call carries
  budget.tf               the account budget, first: 80 and 100 percent, and a forecast over it
  kms.tf                  the workflow's key; the tool gateway's signing key for Entra
  network.tf              eight interface endpoints and the S3 gateway endpoint; security groups by reference
  iam.tf                  the boundary; the harness's role (no bedrock:InvokeModel); the tool gateway's role
  runtime.tf              the gateway key's provider; the runtime, V1, in the VPC, behind Entra; its endpoint,
                          log group and resource policy
  gateway.tf              the policy engine, the tool gateway, its credential, its two private MCP targets,
                          the Cedar permits, its resource policy and its logs
  tools.tf                part 2's module, called with the manifest
  knowledge.tf            the corpus bucket, S3 Vectors, the Knowledge Base, its data source
  guardrail.tf            the guardrail on the Canada profile, detect mode first, and its version
  logging.tf              model invocation logging, without prompts when the manifest says so
  outputs.tf              what the Teams bot, the model gateway and the pipeline need
  modules/manifest_roles/ part 2: manifest and catalog in; tool roles, EKS access, Cedar permits out
  example.tfvars.txt      placeholder values; the tests plan with them
manifests/w3-incident.yaml  the incident workflow on AWS: chapter 5's manifest, grown by a Region and a tool
catalog/tools.yaml        the tool catalog: each tool's server, AWS grants, Kubernetes access; never-list denies
pipeline/scope_check.py   part 2: refuses grown scopes without a change record
org/scp.json              the organization's service control policy for agent accounts, as a sample
gateway/litellm.aws.yaml  the AWS gateway pair's deployments for chapter 5's aliases, and the guardrail
image/Dockerfile          part 3: chapter 7's entry point for AgentCore, linux/arm64
models.yaml               what Bedrock serves in Canada, with lifecycle dates; the pinned model
cost/cost-sheet.yaml      ca-central-1 prices from AWS's Price List API, dated; the idle month; the OpenSearch trap
results/2026-10-29/       validate, the offline plan, the scope check, the test runs
tests/                    see "Tests"
requirements.txt          this lab's pinned set; the image's tests use chapter 5's
```

## Setup

```
python -m venv .venv-ch06
.venv-ch06/Scripts/python -m pip install -r requirements.txt     # bin/python on Linux and macOS
cd terraform && terraform init -backend=false && cd ..
```

Terraform 1.13 or later. The image's tests run in chapter 5's environment
(`pip install -r ../ch05/requirements.txt` in a second virtual environment).

## What AWS serves in Canada, and the design that follows

These were AWS's pages on 29 October 2026; the book's fact sheet, section 11, quotes them.

- One model has a Canadian geographic profile: Amazon Nova Lite, `ca.amazon.nova-lite-v1:0`,
  which serves from ca-central-1 and ca-west-1. Every newer model, the Claude 5 and 5.5 families
  included, reaches Canada through the US or global profiles; the US profile's destinations from
  ca-central-1 are Montréal, Virginia, Ohio and Oregon. The only Active chat model In-Region in
  ca-central-1 is Mistral Large (24.02), with a 32K window. Nothing is In-Region in ca-west-1.
- So the Confidential alias on AWS, `larkspur-chat`, is Nova Lite through the Canada profile, and
  the Internal fallback is the same model In-Region in us-east-2 (`gateway/litellm.aws.yaml`). A
  profile serves from every destination it lists, so the deployment declares them in
  `serves_from`, chapter 5's rules compare all of them with the manifest, and the incident
  workflow's manifest lists ca-west-1. Chapter 5's lab manifest, with ca-central-1 alone, would be
  refused, and a test shows it.
- The incident workflow can carry Restricted text, and until the harness classifies each call
  (chapter 12) it labels every call with the manifest's highest class. On AWS its calls therefore
  go to the self-hosted alias of chapter 9; Nova Lite serves the Confidential workflows, and the
  incident workflow's Confidential calls once they are classified.
- AWS doesn't offer its Managed Knowledge Base in Canada, so there's no native Gateway target for
  a knowledge base here, and no document-level ACLs. The runbook corpus is a customer-managed
  Knowledge Base on S3 Vectors, embedded with Titan Text Embeddings V2 In-Region, parsed by the
  default parser, which calls no model, and reached through Larkspur's own knowledge MCP server.
  The knowledge base calls Titan with its own service role, so the service control policy that
  keeps model calls to the gateway's role (chapter 3) carries one exception: that role pattern,
  for that model (`org/scp.json`). AWS also warns that ingestion runs as the role bound to the
  knowledge base, so whoever can change a data source can index whatever the role can read; this
  one reads `runbooks/` in one bucket, and the boundary on agent and tool roles leaves the
  data-source actions out.
- Guardrails have a Canada profile, `ca.guardrail.v1:0` (ca-central-1 and ca-west-1), so the
  Standard tier keeps its evaluation in Canada.
- AgentCore's Runtime, Gateway, Identity, Memory, Policy and harness are offered in Canada
  (Central), and none of it in Canada West; Runtime Instances, payments and the Web Search tool
  aren't offered in Canada. Runtime V2, which starts sessions from a snapshot, isn't offered there
  either, so the runtime is V1. AgentCore Runtime runs ARM64 containers only.

## Part 1: the Terraform

```
cd terraform
terraform validate
```

`results/2026-11-09/terraform-plan.txt` is the plan of the whole configuration with
`example.tfvars.txt`, made with placeholder credentials, `skip_credentials_validation` and
`-refresh=false` in an override file, so no request reached AWS: 76 resources. The plan of
29 October (`results/2026-10-29/terraform-plan.txt`) had 74; the two sandbox applies added the
tool gateway role's first grant and the runtime's egress rule to S3.

What the configuration does, and why:

- The budget comes first. Every resource that refers to nothing else depends on
  `aws_budgets_budget.account` (150 USD a month; alarms at 80 and 100 percent and on a forecast over
  100). Apply it alone first: `terraform apply -var-file=lab.tfvars -target=aws_budgets_budget.account`.
- The harness's role is the workflow identity. Its trust policy admits AgentCore for this
  account and this runtime only. It may pull one image, write its own log group, fetch one key from
  the token vault, and invoke one gateway. It has no `bedrock:InvokeModel`, which AWS's example
  execution role grants: model calls go through the model gateway, and the boundary denies them.
  The vault's provider refers to an external secret, and AgentCore reads that secret with the
  caller's credentials, so the role also holds `secretsmanager:GetSecretValue` on that one secret,
  and only when a service calls on its behalf (`aws:ViaAWSService`; AgentCore is not on
  `aws:CalledVia`'s list). The provider's ARN in the policy is the resource's own,
  `token-vault/default/apikeycredentialprovider/<name>`. Both came out of the 2 November
  invocation: the first form the lab guessed was refused, and then the secret read was.
- The boundary on every role that acts for the workflow caps them at a named list of actions
  and denies direct model calls, `sts:AssumeRole` (no role chaining from the harness), IAM changes,
  `GetWorkloadAccessTokenForUserId` (which AWS advises denying in production), and the actions
  that change the policy engine. A boundary binds only the roles that carry it, so the
  organization's SCP (`org/scp.json`) reserves every change to a tool gateway, its targets, its
  resource policy and its policy engine for the pipeline's role, and keeps the boundary in place.
  In production the account baseline owns the boundary; the lab creates it to stand alone.
- The runtime is V1, in the VPC, behind an Entra JWT authorizer. Entra's v2.0 access tokens
  carry the runtime app's client ID as their audience and no `client_id` claim, so the authorizer
  checks the audience and a required `azp` claim equal to the Teams bot's client ID: the bot is the
  one caller. `Authorization` is on the header allowlist, so the harness can read the engineer from
  the token AgentCore validated. A microVM stops after fifteen idle minutes or an hour, against
  AWS's eight hours, and the session resumes on a new one with the next request. The bot calls the
  `live` endpoint, pinned to a version. A resource policy admits invocations only through Larkspur's
  AgentCore endpoint, because VPC mode governs the runtime's own traffic, not who may invoke it.
  The environment holds no secret: `GATEWAY_KEY_PROVIDER` names an API-key credential provider
  whose value stays in Secrets Manager (`api_key_secret_source = "EXTERNAL"`), so Terraform's state
  never holds it.
- The tool gateway authorizes with IAM, so the policy engine sees the harness as
  `AgentCore::IamEntity::"arn:aws:sts::<account>:assumed-role/w3-incident-harness"`, and enforces
  one Cedar permit per tool in the manifest. It lists a target's tools as `<target>___<tool>`;
  `TOOL_TARGETS` tells the harness which target serves which tool. Its two MCP targets are private,
  reached through interfaces in the VPC, and authenticate the gateway with a token from Entra: the
  gateway's own app registration, with a private key JWT signed in KMS, so no client secret exists
  and the servers know the workflow from the token's `azp`, which is there only when the servers'
  app registration asks for v2.0 tokens (a registration left at the default got a v1.0 token with
  `appid` instead on 2 November 2026). It passes on one header,
  `X-Larkspur-Actor`, which carries the person's token for the tool server. Its resource policy
  admits the harness's role, through Larkspur's gateway endpoint only. Its application logs, which
  can hold request and response bodies, go to a log group with the workflow's key.
- The endpoints: ECR (API and Docker), the S3 gateway endpoint scoped to ECR's layer bucket
  (the runtime's egress names S3's prefix list for it, since a gateway endpoint has no security
  group; without that rule the layer pull dials S3 and times out, which the first invocation showed),
  and CloudWatch Logs, which AWS lists for a runtime without internet access; AgentCore's data
  plane (the token vault, and the bot's invocations), the tool gateway's endpoint, STS for the tool
  servers, the Bedrock runtime (with an endpoint policy that admits the model gateway's role only),
  and the Knowledge Base runtime for Retrieve. The tool servers' cluster adds the endpoints it needs
  (CloudWatch for alarms, EKS, EKS Pod Identity). The subnets must sit in AZ IDs AgentCore supports
  in ca-central-1: cac1-az1, cac1-az2, cac1-az4. The runtime's security group reaches the
  endpoints, the model gateway and the collector by security group, not the whole VPC.
  `network.tf` builds the endpoints a sandbox VPC needs; in Larkspur's landing zone network
  security runs one set for every workflow, and an S3 gateway endpoint already on the route tables
  would collide.
- The workflow's key encrypts the stores whose encryption is fixed at creation (the
  corpus bucket and the vector bucket) and the three log groups. The tool gateway's signing key is
  an RSA key for Private Key JWT; its public key, as a certificate, is the Entra app's credential.
- The Knowledge Base is as above. Its S3 Vectors index marks `AMAZON_BEDROCK_TEXT` and
  `AMAZON_BEDROCK_METADATA` non-filterable, as AWS's setup page says; the setting is fixed at
  creation. The role lists `runbooks/` and reads nothing else.
- The guardrail runs before and after each call on the managed aliases (`litellm.aws.yaml`),
  never on the self-hosted one, so no Restricted prompt reaches it. LiteLLM sends it the text of
  every message, tool results included. In detect mode its findings exist only in the gateway's
  responses, so chapter 5's gateway writes each verdict and the filters that fired, never the text
  they matched, on its log line. Invocation logging doesn't record ApplyGuardrail.
- Invocation logging is one setting per account and Region; with the manifest's
  `trace_content: false` it delivers no text. The organization trail needs data-event selectors for
  `AWS::BedrockAgentCore::Runtime` and `::Gateway`, `AWS::Bedrock::KnowledgeBase` (Retrieve) and
  `AWS::Bedrock::Guardrail`, and the cluster's `audit` log type on: the restart is a Kubernetes
  call, recorded there under the tool role's session name, which the tool server sets from the
  engineer's object ID.

Before a first apply, in a sandbox account:

1. A VPC with two private subnets in supported AZ IDs, their route tables, and no route to the
   internet; the security groups of the model gateway's load balancer, the collector and the MCP
   servers; an ECR repository holding the image (part 3), named by digest.
2. In Entra: the runtime's app registration with `accessTokenAcceptedVersion` set to 2, an exposed
   scope, and admin consent for the Teams bot alone; the bot's app (`entra_bot_client_id`); the MCP
   servers' app, whose `.default` scope the tool gateway asks for, also with
   `accessTokenAcceptedVersion` 2 so the token the servers receive carries `azp`; and an app for the
   tool gateway, whose credential is made in step 6.
3. A Secrets Manager secret holding the workflow's virtual key for the model gateway, as JSON with
   a `key` field; Larkspur's root CA certificate as a PEM object in S3 (`private_ca_s3_uri`).
4. The tool servers' base roles (EKS Pod Identity) and the EKS cluster the Kubernetes tools act on.
   The cluster's RBAC binds `larkspur:deployment-restarters` to patch on deployments in the claims
   and billing namespaces, and an admission policy lets that group change only the
   `kubectl.kubernetes.io/restartedAt` annotation.
5. Copy `example.tfvars.txt` to `lab.tfvars` (git-ignored) and fill it in. Apply the budget, then
   `-target=aws_kms_key.tool_gateway_signing`.
6. Make an X.509 certificate from the signing key's public key (`kms:GetPublicKey`, signed with
   `kms:Sign`), upload it to the tool gateway's Entra app, and set its SHA-256 thumbprint in
   `entra_tool_gateway_cert_thumbprint`. `sandbox/sandbox.py signing-cert` does the three from a
   file with the registrations. Then apply the rest.
7. After every apply that creates or changes a gateway target, register the CA on it, because
   hashicorp/aws 6.71.0 has no field for it (`terraform output tool_gateway_targets`):
   `aws bedrock-agentcore-control update-gateway-target ... --certificate-configurations` with the
   S3 object, and alarm on the gateway's `EarliestCertificateDaysToExpiry` metric. The update
   synchronizes the target again, so it lists its tools once the CA is in place. A target created
   before its CA is registered ends `FAILED` on the TLS handshake and fails the apply (the provider
   waits for `READY`); the update brings it to `READY`, and `terraform untaint` on the two targets
   lets the next apply create the Cedar permits instead of replacing them.

Checked only at a first apply, because no page states them. Two stay open after the two sandbox
applies, and both need what the sandbox has no cheap stand-in for:

- whether EKS Pod Identity's transitive session tags count in the tool roles' `aws:TagKeys`
  condition, which would refuse every assumption (if they do, turn session tags off on the
  servers' Pod Identity associations): needs worker nodes and a pod;
- which version a session resumed on a new microVM runs (the bot opens new sessions after a
  release rather than relying on it): needs a second runtime version.

## What the sandbox applies settled

The sandbox apply of 30 October 2026, in us-east-2 (`results/2026-10-30/`):

- the PrivateLink service `com.amazonaws.<Region>.bedrock-agentcore.gateway` exists there;
- with text delivery off, an invocation record holds the content types, the token counts and the
  inference Region, and no prompt or answer;
- the Knowledge Base embeds the query at `Retrieve` itself; a role allowed only `Retrieve` gets
  answers (W1's S3 Vectors check, `workflows/w1-knowledge-assistant`);
- CreateGateway checks that the gateway's role can call `GetPolicyEngine` before it makes the
  gateway, so that grant comes first (`tool_gateway_start`), as the runtime's does;
- EC2 refuses an apostrophe in a security group's description; a test now checks every one;
- a target's creation runs the OAuth client-credentials grant at once, and without a working Entra
  credential the target ends FAILED ("Please check the OAuth setup"), so step 6 must come before
  the targets, not merely before the first tool call;
- GetGatewayTarget returns a header AgentCore adds for the policy engine,
  `x-amzn-bedrock-agentcore-policy-session-id`, and UpdateGatewayTarget refuses it back, so step
  7's update drops it (`sandbox/sandbox.py register-ca`); the update accepts the CA from S3.

The sandbox apply of 2 November 2026, with the author's four Entra registrations (book #69), two MCP
stand-ins answering as the servers behind a private load balancer with a certificate from the
sandbox root, and a function inside the VPC standing in for the bot (`results/2026-11-02/`:
`first-apply.json`, `invocation.json`, `cloudtrail-token-vault.json`, with the account ID and the
Entra tenant, app, and object IDs replaced by names in angle brackets):

- the tool gateway's client credential works as designed: the certificate made from the KMS
  signing key and uploaded to the gateway's app let Entra issue a token (`aud` the servers' app,
  `appid` the gateway's), which the gateway presented to both servers; the 30 October "OAuth setup"
  failure was the missing credential and nothing else;
- a target created before its CA is registered ends `FAILED` (`PKIX path building failed`) and
  fails the apply; `sandbox.py register-ca` brought both to `READY` in under four minutes, and the
  untainted targets stayed as they were on the next apply;
- the four Cedar permits, created after the targets with `FAIL_ON_ANY_FINDINGS`, are `ACTIVE`;
- the gateway serves the targets' tool definitions exactly as the servers do: the harness, through
  the gateway from inside the VPC, listed the four tools and verified every one against its lock,
  `get_pod_status 6a390080cc1b`, `get_recent_alerts 8e9ceceb650d`, `restart_deployment
  6b759af44fb4`, `search_runbooks 31aace634a98`, the hashes of the stand-ins' own definitions
  (`tools_verified` in the runtime's log); the list came from the gateway's synchronized copy, since
  no request reached the stand-ins during the invocation;
- before `initialize`, the gateway probes a server with `server/discover` (a method the
  specification does not name; `_meta` carries `io.modelcontextprotocol/protocolVersion`
  `2026-07-28` and `clientInfo` `genesis-gateway 1.0.0`), accepts the specification's
  "method not found", and goes on to `initialize`, `notifications/initialized`, `tools/list`;
- the runtime's resource policy holds: a call from a laptop with a valid token for the bot's app is
  refused (`User: anonymous is not authorized ... no resource-based policy allows`, the
  `aws:SourceVpce` condition), and the same call from inside the VPC through the AgentCore endpoint
  reaches the container; the JWT authorizer accepted the bot app's v2.0 token (`aud` the runtime's
  client ID, `azp` the bot's);
- the image pull needs the runtime's egress to name S3's prefix list: with the three named groups
  alone, the layer pull dialed S3 and timed out, and every invocation was a 502 until the rule
  existed;
- `GetResourceApiKey` with an external secret: the provider's ARN is
  `token-vault/default/apikeycredentialprovider/<name>` (the guessed `api-key/<name>` form was
  refused), and AgentCore reads the secret with the caller's credentials (`invokedBy
  bedrock-agentcore.amazonaws.com`), so the runtime's role needs `secretsmanager:GetSecretValue`
  on that one secret, bound with `aws:ViaAWSService` (`aws:CalledVia` does not match); with both in
  place the key arrived and the harness went on to the model gateway, which the sandbox does not
  have (`Name or service not known`), the end of what it can show;
- the Entra token the gateway presents to the servers is v1.0 (`appid`, `ver 1.0`) unless the
  servers' app registration asks for v2.0 tokens; the lab's text assumed `azp`, and step 2 now says
  so.

Teardown: set `force_destroy_stores = true` and apply, so a destroy removes the versioned corpus
bucket and the vector bucket with their contents; then `terraform destroy -var-file=lab.tfvars`.
Deleting the guardrail deletes all its versions. The runtime's network interfaces can stay in the
VPC for up to eight hours after the runtime is deleted, so a subnet made for the lab waits that long.

## Part 2: the manifest becomes identities

`terraform/modules/manifest_roles` reads a manifest (chapter 5's schema, which now takes an `allow`
list per tool) and `catalog/tools.yaml`, and creates, for each tool the manifest lists:

- a role named `<workflow>-<tool>`, with the catalog's grants for that tool and nothing more, the
  boundary, a one-hour ceiling (IAM's floor for a role; the server asks for fifteen minutes), and
  the workflow, tool, server, owner, sponsor and writes flag in its tags;
- a trust policy that admits only the tool's server, only with a source identity in
  `@larkspur.example` and a `workflow` session tag equal to the workflow, and no other tag.
  CloudTrail records the source identity on every AWS call the role makes, and the tags on the
  AssumeRole event; the Kubernetes calls are in the cluster's audit log under the session name;
- a deny for every AWS action the manifest's never-list maps to in the catalog;
- EKS access: the read-only access policy in two namespaces, or a group the cluster's RBAC binds;
- a Cedar permit for the tool gateway, narrowed by the manifest's `allow` list:

```
permit (
  principal == AgentCore::IamEntity::"arn:aws:sts::111122223333:assumed-role/w3-incident-harness",
  action == AgentCore::Action::"k8s___restart_deployment",
  resource == AgentCore::Gateway::"arn:aws:bedrock-agentcore:ca-central-1:111122223333:gateway/w3-incident-tools-a1b2c3d4e5"
)
when {
  context.input has service && ["claims-api","billing-worker"].contains(context.input.service)
};
```

The plan stops, with the reason, when the manifest names a tool the catalog doesn't have, when the
two disagree on whether a tool writes, or when an `allow` list names an argument the tool doesn't
take.

`pipeline/scope_check.py` runs before the module, on every change to a manifest or to the catalog,
against the main branch's versions of both. Growth is anything that lets the workflow reach more:
a tool, an argument, a write, a model alias, a Region, a higher data class or rung, prompts in
spans, a larger budget, a value added to an allow list or the list removed, a never-list entry
dropped, and, for the tools the manifest lists, any AWS action, resource or Kubernetes access the
catalog adds. Growth needs a change record (`--change-record CHG-1234` or `CHANGE_RECORD`);
narrowing doesn't. With `--base-manifest` the base catalog is required, because without it the
catalog would be compared with itself. Against chapter 5's lab manifest, the AWS manifest has three
grown scopes and one narrowing (`results/2026-10-29/scope-check.txt`):

```
grown: regions added: ca-west-1
grown: tool added: search_runbooks
grown: search_runbooks: IAM bedrock:Retrieve on ${knowledge_base_arn}
narrowed: restart_deployment: service only claims-api, billing-worker
scope check: refused: 3 grown scope(s) for w3-incident, no change record
```

The companion's CI isn't committed (the repository's token lacks the `workflow` scope), so the
check runs as a step the reader adds to their own pipeline: the two `git show` lines in the
script's docstring, then the script.

`org/scp.json` is the organization's service control policy for agent accounts. Chat models are
the model gateway's role's alone; Titan Text Embeddings V2 is also a knowledge base's role's; every
change to a tool gateway, its targets, its resource policy, its policies and its policy engine is
the pipeline's; a role created outside the pipeline carries the agent boundary, and nobody but the
pipeline changes it. The lab can't apply an SCP, which belongs to the organization, so the tests
read it.

## Part 3: the image

`image/Dockerfile` runs chapter 7's entry point with `RUNTIME=agentcore` on port 8080. Build it
from `companion/labs` as the context, for linux/arm64, the only platform AgentCore Runtime runs:

```
docker build --platform linux/arm64 -f ch06/image/Dockerfile -t harness-agentcore .
```

The build needs `ch06/image/private-ca.pem`, Larkspur's root CA, for the model gateway and the
collector; `*.pem` is git-ignored. The image has no `GATEWAY_KEY`:

- `ch07/image/token_vault.py` fetches the key from AgentCore Identity's token vault with the
  workload access token AgentCore sends with each request (`GetResourceApiKey`), keeps it fifteen
  minutes at most, and never fetches at start-up. Chapter 5's adapter holds that token in
  `WORKLOAD_TOKEN` for the request it came with and never logs it.
- `ch07/image/sigv4_mcp.py` signs every MCP request with the role the process runs under, for the
  tool gateway's IAM authorization (`MCP_AUTH=sigv4`). Its `GatewayNames` maps the gateway's
  `<target>___<tool>` names back to the tools' own before the harness checks them against its
  lock, only when the prefix is the tool's target in `TOOL_TARGETS`, and calls each tool by its
  served name.

Chapter 5's adapter gained three things for AgentCore, as it did for Foundry in chapter 8: a body
without a prompt is a 400 instead of a server error; the session id, the request id and the
engineer (the token's `oid`, else `sub`) go on every audit line; and a session serves only the
engineer its ID names. AgentCore "does not enforce session-to-user mappings" (Use isolated sessions
for agents, AgentCore developer guide, read 2026-10-29), and a stopped session resumes on a new
microVM, so the check keeps no state: the bot ends every session ID with a hash of the engineer's
object id, and the harness recomputes it from the validated token on every request. A refusal is a
403 from the container, which the bot receives as AgentCore's 424.

The harness checks every tool the gateway lists against its lock, so the image for AWS carries a
lock that pins the four tools of the incident manifest, written by the pipeline from the gateway's
list after the targets synchronize. The companion's lock pins chapter 5's two read-only tools; the
restart and the runbook search join it with their servers in Part III. The sandbox writes its
image's lock from the stand-ins' definitions (`sandbox/mcp_stand_in/tools.json`), which is what made
the harness's check of the gateway's list a check of what the gateway relays.

The image is built in CodeBuild by the sandbox, since this machine has no container engine
(`sandbox/sandbox.py image`). In-process, a question goes end to end on AgentCore's routes through
a stand-in gateway and chapter 5's MCP server, with the key from a stand-in vault and every MCP
request signed; on AgentCore, the 2 November invocation ran the same code up to the model call.

## Models and costs

`models.yaml` records what Bedrock served in Canada on 29 October 2026, with lifecycle dates, and
pins Nova Lite. Nova Lite and Mistral Large are both past their earliest end-of-life date
("EOL no sooner than"), so AWS may announce either's Legacy state, with at least six months before
end of life. An account that doesn't use a Legacy model for fifteen days may lose access to it, so
from the day of a notice the Internal fallback gets a synthetic call every week
(`fallback_weekly_call`), and a test fails without it. Claude 3 Haiku is already Legacy in
ca-central-1 and ends on 13 November 2026.

`cost/cost-sheet.yaml` holds ca-central-1 prices from AWS's Price List API, each with its offer
file's publication date. Two lines matter more than the rest:

- The idle month is the endpoints. An interface endpoint bills $0.011 an hour in each zone it
  has an interface in, so this configuration's eight endpoints in two subnets cost about $128.48 a
  month with no traffic; the two keys add $2.00, for 87 percent of the lab's budget. Everything
  else bills per use. A production account shares one set of endpoints across the VPC's workflows;
  a sandbox applies, runs the lab and destroys within a day.
- The OpenSearch Serverless trap: a Classic collection bills two OCUs around the clock,
  $388.36 a month at $0.266 an OCU-hour, or $194.18 without standby replicas, against the lab's
  150. A NextGen collection in a group whose minimum is 0 scales to zero after ten minutes without
  requests and takes 10 to 30 seconds to wake. The lab uses S3 Vectors, which bills nothing by the
  hour.

## Tests

```
python -m pytest -q tests/
```

In this lab's environment: 84 passed and 3 skipped (the image module, and the tests that need
LiteLLM) on 2 November 2026. In chapter 5's environment, `python -m pytest -q tests/test_image.py
tests/test_gateway_aws.py tests/test_scope_check.py tests/test_scp.py` runs those too: 55 passed.
Chapters 5, 7 and 8's suites were rerun after the shared code changed on 29 October 2026: 173; 17
and 42; 18 and 21. The records are `results/2026-10-29/pytest.txt` and `results/2026-11-02/pytest.txt`.

| File | Tests | What it checks |
|---|---|---|
| `tests/test_terraform.py` | 18 | the provider pin and the Canadian Region; the budget first; the runtime (V1, VPC, Entra's audience and the bot's `azp`, the header allowlist, short sessions, an image by digest); no secret in the environment and the data class the manifest allows; the harness's role without model access; the boundary's denies; the tool gateway's IAM authorization, ENFORCE mode, private targets and one propagated header; the endpoints; resource policies through Larkspur's endpoints and the `live` endpoint; security groups by reference; the gateway's private key JWT; the workflow's key on the stores and log groups; the customer-managed Knowledge Base; the guardrail's Canada profile and detect mode; invocation logging; `terraform validate` |
| `tests/test_manifest_roles.py` | 9 | the module, planned: a role per tool with the boundary, tags and one-hour ceiling; trust for the tool's server, a person and the workflow only; the catalog's grants and the never-list denies; EKS access; one Cedar permit per tool, narrowed by `allow`; chapter 5's operations assistant; three disagreements that stop the plan |
| `tests/test_scope_check.py` | 23 | the AWS manifest against chapter 5's; eleven kinds of growth refused without a record; a catalog change that widens a listed tool; narrowing allowed; a new workflow; what counts as a change record; a base manifest without the base catalog; invalid inputs |
| `tests/test_scp.py` | 5 | deny statements only, within the SCP size limit; chat models for the model gateway's role; Titan for knowledge bases' roles too; the tool gateways' switches for the pipeline; the boundary kept |
| `tests/test_gateway_aws.py` | 8 | chapter 5's rules on the AWS deployments: the Canada profile and its two Regions, no transfer to Ohio for Confidential data, chapter 5's lab manifest refused, Internal failover, Restricted to the self-hosted alias only; the Bedrock guardrail on the managed aliases only, as written and as LiteLLM merges it |
| `tests/test_models_and_costs.py` | 7 | one pinned model, Active, served in Canada only, far from end of life; no model that can be served abroad marked Canadian; a Legacy notice needs the fallback's weekly call; the gateway calls the pinned model at the sheet's prices; the sheet dated by offer; the idle month and the OpenSearch trap recomputed from the rates |
| `tests/test_sandbox.py` | 5 | the sandbox's stand-ins stay stand-ins: no way to the internet, nothing that outlives a destroy, the secret and the root as placeholders, the ARM64 build, the build context |
| `tests/test_stand_ins.py` | 11 | the MCP stand-ins: the catalog's four tools by server, chapter 5's two served exactly as its lock pins them, the image's lock from their definitions; the function's answers (`initialize`, `tools/list` by host, `tools/call` in the output shape, a notification's 202, POST only, a token logged by its claims and never itself); the load balancer internal and HTTPS only in the MCP servers' group, the certificate from the sandbox root for two days, the function's log and nothing else; every group and rule description one EC2 accepts |
| `tests/test_image.py` | 19 | the Dockerfile (base by digest, linux/arm64, port 8080, the vault and signing modules, Larkspur's root, its own user, chapter 5's pinned set); runtime.tf's environment; the entry point's settings for AgentCore, `TOOL_TARGETS` included; one question end to end with the key from the vault; no key, no model call; the key's fifteen minutes; signed MCP requests to a real MCP server; the gateway's prefixed names through the lock check and on the wire |
