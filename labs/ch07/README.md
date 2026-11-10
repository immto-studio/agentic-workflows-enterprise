# Lab, chapter 7: the skeleton on Google Cloud

Chapter 7 deploys the chapter 5 skeleton on Gemini Enterprise Agent Platform for the Quill team.
None of the lab needs a Google Cloud account.

- Part 1 runs. ADK 2.13.0 with a rule-based model holds a restart for a person's approval in two
  ways: ADK's tool confirmation, which its documentation marks experimental and unsupported with
  the database and Agent Platform session services, and a long-running approval call: the approval
  service sends the decision back as the call's final response, and the agent then calls the write
  tool, which checks that a recorded yes covers exactly that restart and applies each approval
  once. Each runs against three of ADK's session services, with a new runner between the request
  and the answer.
- Part 2 is validated but not applied. Terraform puts the skeleton's harness on Agent Runtime in
  Montréal behind the workflow's own egress Agent Gateway (audit-only to start, an `ALL_TRAFFIC`
  connectivity template, Identity-Aware Proxy deciding and failing closed). The agent runs under
  its own identity with its image by digest, reads its gateway key from Secret Manager, encrypts
  with a customer-managed key, and gets Memory Bank's models and the manifest's expiry for
  memories and their revisions. A deny policy leaves only the model gateway's service account and
  Google's service agents able to send a prompt. The budget alarm comes first, after the two APIs
  it needs. `terraform validate` and nineteen policy tests check it.
- Part 3 is the harness image: a Dockerfile and an entry point that read the environment the
  Terraform sets, tested in-process with chapter 5's code; the image is not built here, because
  this machine has no container engine.

```
adk/
  runbook_model.py      a rule-based stand-in for Gemini: asks for the restart, then answers
  approval.py           the two patterns; the approval service and the write tool as stand-ins
  approval_matrix.py    part 1: both patterns, three session services, approved and rejected
terraform/              part 2
  services.tf           the budget's two APIs first, then the platform's
  budget.tf             the alarm, before everything else
  gateway.tf            egress gateway, connectivity template, IAP extension and policy; essential endpoints
  runtime.tf            the agent
  iam.tf                service-agent grants and the deny policy
  example.tfvars.txt    placeholder values for a personal sandbox project
image/                  part 3: Dockerfile and entry point for the harness container
models.yaml             the models the lab pins, with Google's dates and residency
cost/cost-sheet.yaml    Agent Runtime, Agent Gateway, Sessions and Memory Bank prices, dated
results/2026-10-29/     the matrix, the validate output and the test runs behind the chapter
tests/                  see "Tests"
requirements.txt        this lab's own pinned set (ADK's dependencies differ from chapter 5's)
```

## Setup

```
python -m venv .venv-ch07
.venv-ch07/Scripts/python -m pip install -r requirements.txt     # bin/python on Linux and macOS
```

On Windows set `PYTHONUTF8=1` first. Terraform 1.13 or later runs part 2. Part 3's tests use
chapter 5's environment (`pip install -r ../ch05/requirements.txt` in a second virtual
environment); in this lab's own environment they skip.

## Part 1: approval on ADK

```
python adk/approval_matrix.py --out results/2026-10-29/adk-approval.json
```

Every scenario is one engineer asking the incident workflow to restart `claims-api`. The first turn
runs on one ADK runner. The approver's answer goes to a second runner built on a new
session-service object over the same SQLite file, the way a new Agent Runtime instance would pick
the conversation up. The in-memory service keeps nothing across a restart, so its second turn
reuses the same object.

Results on 29 October 2026, google-adk 2.13.0, Python 3.12.9, Windows 11:

| Pattern | In-memory | SQLite service | Database service (SQLAlchemy over SQLite) |
|---|---|---|---|
| Tool confirmation, approved | paused, restarted once | paused, restarted once | paused, restarted once |
| Tool confirmation, rejected | paused, not restarted | paused, not restarted | paused, not restarted |
| Long-running approval, approved, decision delivered twice | write tool called twice, restarted once | the same | the same |
| Long-running approval, rejected | paused, not restarted | paused, not restarted | paused, not restarted |

Tool confirmation worked on both SQLite-backed services, across the new runner, although ADK's
page on it still lists the database service as unsupported. ADK's source shows why the managed
service is on the list: `VertexAiSessionService` writes the whole event when the installed Agent
Platform SDK accepts it and otherwise falls back to named fields that leave out the confirmation
request, so the SDK version decides. The managed service needs a project and is not in the matrix.
One test records the observation and runs on any ADK version, failing with what it saw.

With the decision delivered twice, ADK gave the model the conversation without the restart it had
already made, and the model called the write tool again on all three services; the write tool's
one restart per approval held. Neither pattern carries who approved: anyone who can query the
agent can send a decision, so the write tool checks the approval service's own record.

## Part 2: the Terraform

```
cd terraform
terraform init -backend=false
terraform validate
```

`terraform plan` needs credentials and stops there. To apply it in a personal sandbox project:

1. Copy `example.tfvars.txt` to `lab.tfvars` and fill it in. The network attachment, the trust
   configuration with your private CA, the key ring, the Secret Manager secret and the Artifact
   Registry repository are prerequisites the lab does not create.
2. Create the budget alarm first: `terraform apply -var-file=lab.tfvars
   -target=google_billing_budget.workflow`. The provider block sets `billing_project` and
   `user_project_override`, without which the Billing Budgets API refuses user credentials.
3. Apply the gateway (`-target=google_network_security_authz_policy.egress`), fetch its CA
   certificate from the gateway resource's `agentGatewayCard.rootCertificates` into
   `image/gateway-ca.pem`, build and push the image, and put its digest in `lab.tfvars`.
4. Register and grant the essential endpoints (`terraform output essential_endpoints`) and the
   manifest's destinations for the agent's principal, then apply the rest. Without the essential
   endpoints every invocation fails with a 498.
5. After every apply, list the roles the agent's principal holds (`terraform output
   agent_identity`; then `gcloud projects get-iam-policy`, filtered on it) and compare them with
   what the pipeline expects. Google grants `roles/aiplatform.agentDefaultAccess` and
   `roles/aiplatform.agentContextEditor` by default, and the first includes
   `aiplatform.endpoints.predict`; the deny policy is what keeps the agent from calling a model.
6. Turn `gateway_dry_run` off only after reading a week of the gateway's request log.

A project without an organization can't reproduce everything: there is no perimeter and no
folder, so the deny policy sits on the project, and the agent identity's trust domain is built from
the project number.

Teardown is `terraform destroy -var-file=lab.tfvars` with `deletion_policy = "FORCE"` (the
example's value), because sessions created by a smoke test would otherwise stop it; then remove
the gateway grants for the deleted principal, which Google leaves in place. The budget goes last.
Production uses `deletion_policy = "PREVENT"`, so a plan that would replace the agent, and give it
a new principal, fails.

Google's Terraform guide says the Agent Gateway resource needs `google-beta`; it validates against
the GA provider 8.9.0, together with the connectivity template and the IAP extension.

## Part 3: the harness image

`image/entrypoint.py` starts chapter 5's harness behind its runtime adapter, with the model calls
going through the gateway (`GatewayModel`) and the tools pinned by chapter 5's lock. `RUNTIME`
picks the route: `agent-runtime` here, `foundry` in chapter 8's image and `agentcore` in chapter 6's,
which run the same file. On AgentCore the gateway key comes from AgentCore Identity's token vault
(`image/token_vault.py`, with `GATEWAY_KEY_PROVIDER` in place of `GATEWAY_KEY`) and the MCP requests
are signed for the tool gateway (`image/sigv4_mcp.py`, `MCP_AUTH=sigv4`); both load only there.
It reads the environment `runtime.tf` sets (`RUNTIME`, `GATEWAY_URL`, `GATEWAY_KEY`,
`WORKFLOW`, `MODEL_ALIAS`, `DATA_CLASS`, `MCP_URL`, `OTEL_EXPORTER_OTLP_ENDPOINT`, and `PORT`, which
defaults to the runtime's own port, 8080 here) and refuses to start, naming every variable that is
missing. On SIGTERM, uvicorn finishes the requests in flight and the process exits normally, so the
spans still waiting in the batch are sent.

`image/ca_bundle.py`, which the entry point imports, adds a private root CA to the CA bundle the
runtime provides, at start and again before every question, when the image carries a roots file
(`CUSTOM_ROOTS_FILE`, `/app/custom-roots.pem` by default). This image carries none: the Agent
Gateway checks the destinations' certificates against Larkspur's CA itself. Chapter 8's image
carries Larkspur's root, because on Foundry the harness reaches those services directly.

`image/Dockerfile` builds it from `companion/labs` as the context:

```
docker build -f ch07/image/Dockerfile -t harness .
```

The base image is `python:3.12-slim` pinned by digest (looked up on 29 October 2026). Chapter 5's
pinned set installs from wheels only, and the build fails if the proprietary `litellm-enterprise`
package ever appears. The Agent Gateway's CA certificate goes in from `image/gateway-ca.pem`
(git-ignored; the pipeline writes it from the gateway resource), and `SSL_CERT_FILE`,
`REQUESTS_CA_BUNDLE` and `GRPC_DEFAULT_SSL_ROOTS_FILE_PATH` point at the system bundle. The
container runs as a user of its own and listens on 8080.

The image has not been built here, because this machine has no container engine, and the CA path
has not been tried against a TLS-inspecting proxy. The entry point has run as a real process
against chapter 5's LiteLLM gateway and a stub OpenTelemetry Collector: it answered with a 200,
the gateway's manifest rules passed, and the spans arrived.

## Models and costs

`models.yaml` lists the models the Terraform pins, with Google's dates and whether Google's
residency table lists them as processed in Canada. A test fails when a pinned model retires within
90 days: the two embedding models processed in Canada retire on 1 April 2027, so that test starts
failing in January 2027. Memory Bank's models are pinned, but no Google page says Memory Bank
honors a regional path for a Gemini 3 model, so Memory Bank stays off for Confidential workflows
until Google confirms where those calls run.

`cost/cost-sheet.yaml` has Agent Runtime, Agent Gateway, Sessions and Memory Bank prices as printed
on 29 October 2026. Google's page says idle time between turns isn't billed; a day's billing export
after the first apply shows what the floor of one instance costs.

## Tests

```
python -m pytest -q tests/
```

Chapter 7's environment runs everything except the nine image tests that need chapter 5's
packages: 42 passed and 9 skipped on 29 October 2026. In chapter 5's environment,
`python -m pytest -q tests/test_image.py` runs all seventeen image tests: 17 passed.
The record is `results/2026-10-29/pytest.txt`. `tests/image_support.py` holds the helpers that
chapter 8's image tests share.

| File | Tests | What it checks |
|---|---|---|
| `tests/test_adk_approval.py` | 11 | the approval service and the write tool; both patterns against the persistent session services |
| `tests/test_terraform.py` | 20 | the policies the chapter describes, read from the HCL, and `terraform validate` |
| `tests/test_models_and_costs.py` | 3 | the model register, the 90-day retirement rule, the dated cost sheet |
| `tests/test_image.py` | 17 | the environment contract with `runtime.tf`, the Dockerfile, one question end to end in-process, a clean stop on SIGTERM, and a private root added to the runtime's CA bundle |
