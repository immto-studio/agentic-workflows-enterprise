# Lab, chapter 8: the skeleton on Microsoft Foundry

Chapter 8 deploys the chapter 5 skeleton as a Foundry hosted agent for Larkspur's
commercial-lines team. None of the lab needs an Azure subscription to validate. On 2 November 2026
it was applied once in a trial subscription with the stand-ins of `sandbox/` and destroyed;
`results/2026-11-02/` holds what the apply found and what the trial refused (book D-037).

- Part 1 is validated and was applied once. Terraform creates the agents' Foundry account with network
  injection (chosen at creation, as it must be), no keys and no public access; the workflow's
  project with a user-assigned identity; a separate models account in Canada East with a Standard
  deployment of gpt-4o 2024-11-20 that only the model gateway's managed identity can call; an Azure
  Policy on the agents' account that denies any model deployment in it, and one on the models
  account that denies every deployment type except Standard and Regional Provisioned; a private
  registry that accepts Foundry's tokens; private endpoints; and Application Insights, with both
  accounts' resource logs in its workspace. Roles are assigned by ID, Terraform refuses to replace
  the agents' account or the project, and the budget on the resource group comes first.
  `terraform validate` and sixteen policy tests check it, and five more check the model register
  and the cost sheet.
- Part 2 is the harness image: chapter 7's entry point, started with `RUNTIME=foundry` on port
  8088, tested in-process and as a running process. It isn't built here, because this machine
  has no container engine.

Why two accounts: inside its project a hosted agent may call models through the project endpoint
without any role assignment, and the project endpoint passes inference to the deployments of the
account the project belongs to. The agents' account therefore holds no deployments, and the policy
keeps it that way; the model gateway reaches the models account through a private endpoint under
its own managed identity. The models account has a policy of its own, which refuses the deployment
types that may process data outside Canada, so a Global or Data Zone deployment can't appear there
under a name the gateway trusts.

```
terraform/              part 1
  versions.tf           azurerm 5.11.0; destroy purges the soft-deleted accounts (the default, stated)
  main.tf               the resource group and the budget, first
  foundry.tf            the agents' account with network injection, the project (both kept from replacement), the registry
  models.tf             the models account in Canada East, the Standard deployment, the gateway's role
  network.tf            private endpoints for both accounts and the registry
  policy.tf             two deny rules, one on each account
  monitoring.tf         Log Analytics, Application Insights, both accounts' resource logs
  outputs.tf            the project, its identity, the models endpoint for the gateway
  example.tfvars.txt    placeholder values for a personal sandbox subscription
image/Dockerfile        part 2: chapter 7's entry point for Foundry
models.yaml             the Canadian Standard chat models with their lifecycle stages and dates; the pinned one
cost/cost-sheet.yaml    hosted agent and token prices from Microsoft's pricing pages, dated
results/2026-10-29/     the validate output and the test runs behind the chapter
tests/                  see "Tests"
requirements.txt        this lab's pinned set; the image's tests use chapter 5's
```

## Setup

```
python -m venv .venv-ch08
.venv-ch08/Scripts/python -m pip install -r requirements.txt     # bin/python on Linux and macOS
```

Terraform 1.13 or later runs part 1. Part 2's tests use chapter 5's environment
(`pip install -r ../ch05/requirements.txt` in a second virtual environment); in this lab's own
environment they skip.

## Models and costs

On 29 October 2026 Microsoft's region table listed two chat models as Standard deployments in
Canada, gpt-4o 2024-11-20 and gpt-4.1-mini 2025-04-14, both in Canada East and both retiring on
14 April 2027. The retirement schedule put them at different stages. gpt-4.1-mini was Deprecated,
which Microsoft's lifecycle policy defines as "No longer available to new customers", and the
policy decides who is new per subscription: "A new subscription under the same tenant doesn't
inherit access." A sandbox, or any subscription that has never deployed that version, can't create
it. gpt-4o 2024-11-20 was Legacy, which still allows new deployments until deprecation. Its named
replacement is gpt-5.1 (retiring 15 May 2027), which Canada had only as a regional provisioned
deployment and as Global ones. The lab pins gpt-4o 2024-11-20.

`models.yaml` records each model's stage, retirement date and replacement, with the dates of the
pages they come from. One test fails when the pinned model is Deprecated or Retired, and another
90 days before it retires, which for gpt-4o 2024-11-20 is mid-January 2027. Regional provisioned
deployments reached gpt-5.2 (retiring 8 June 2027). Global deployments may process data in any
Azure region, and no data zone covers Canada, so neither carries Confidential data.

The deployment is pinned with `NoAutoUpgrade`, so a model change goes through the golden set first.
Microsoft's lifecycle policy describes that setting as "never auto-upgrade—deployment stops working
at retirement": on 14 April 2027 the alias returns errors unless it has moved. With
`OnceCurrentVersionExpired`, Microsoft would swap in the replacement that day, before any golden set
had run against it.

`cost/cost-sheet.yaml` holds the hosted agents' rates in Canada Central, per vCPU-hour and per
GiB-hour of memory, and gpt-4o 2024-11-20's token rates as a Standard deployment in Canada East, in
US dollars as Microsoft's pricing pages carried them on 29 October 2026. The pages show "$-" until
their script runs; the rates are in the HTML. The registry, the private endpoints and the workspace
bill too, and the sheet doesn't price them.

## Part 1: the Terraform

```
cd terraform
terraform init -backend=false
terraform validate
```

To apply it in a personal sandbox subscription, copy `example.tfvars.txt` to `lab.tfvars` and fill
it in. Before the first apply:

1. Register the resource providers that Microsoft's private networking guide lists:
   Microsoft.KeyVault, Microsoft.CognitiveServices, Microsoft.Storage,
   Microsoft.MachineLearningServices, Microsoft.Search, Microsoft.Network, Microsoft.App and
   Microsoft.ContainerService (the guide adds Microsoft.Bing for the Bing search tool, which the lab
   doesn't use). The lab's other resources need Microsoft.ContainerRegistry,
   Microsoft.ManagedIdentity, Microsoft.OperationalInsights, Microsoft.Insights,
   Microsoft.AlertsManagement and Microsoft.Consumption, the providers azurerm's documentation names
   for them. azurerm 5.x registers none itself (`resource_provider_registrations` defaults to
   `none`), and registering one that is already registered does nothing:

   ```
   for ns in Microsoft.KeyVault Microsoft.CognitiveServices Microsoft.Storage \
       Microsoft.MachineLearningServices Microsoft.Search Microsoft.Network Microsoft.App \
       Microsoft.ContainerService Microsoft.ContainerRegistry Microsoft.ManagedIdentity \
       Microsoft.OperationalInsights Microsoft.Insights Microsoft.AlertsManagement Microsoft.Consumption; do
     az provider register --namespace "$ns"
   done
   ```

2. Create the network: a subnet delegated to `Microsoft.App/environments` (RFC 1918 addresses, used
   by no other Foundry account), a subnet for private endpoints, and the private DNS zones
   `privatelink.cognitiveservices.azure.com`, `privatelink.openai.azure.com`,
   `privatelink.services.ai.azure.com` and `privatelink.azurecr.io`. The delegated subnet is chosen
   once, for every project in the account: "you cannot change the delegated subnet to a new one"
   (How to configure network isolation for Microsoft Foundry, 2026-09-29). By default each
   concurrent session takes one usable address, which gives about 20 sessions on a /27, 250 on a
   /24 and 2,000 on a /21, and Azure support can raise that to ten sessions an address (Deep dive
   into Foundry Agent Service networking, 2026-09-07). A /27 is enough for this sandbox. The same
   page says "Don't use a /27 subnet for production workloads."; a production subnet is sized for
   the peak across every project in the account, plus the 20 percent headroom Microsoft recommends.
3. If a firewall sits on the agents' path, it must let them reach Entra ID's sign-in endpoints and
   must not inspect their TLS (Microsoft's private networking guide).
4. If your organization assigns Microsoft's built-in policy "Container registries should have ARM
   audience token authentication disabled", exempt the lab's registry from it. Foundry pulls the
   image with a token scoped to Azure Resource Manager, and `foundry.tf` keeps the registry
   accepting one.
5. Apply the budget first (`terraform apply -var-file=lab.tfvars
   -target=azurerm_consumption_budget_resource_group.workflow`) and the rest after it. Azure
   refuses a budget without a notification ("Insufficient notification blocks"), so
   `budget_alert_emails` needs an address, unlike the AWS lab's.
6. The lab's identity needs `Microsoft.Authorization/policyDefinitions/write` for `policy.tf`:
   Contributor doesn't carry it, Resource Policy Contributor does.

What the first apply settled, in a trial subscription on 2 November 2026 (`results/2026-11-02/`,
`sandbox/`):

- an account that runs only hosted agents needs no customer Storage, AI Search, or Cosmos DB: the
  injected account and its project came up `Succeeded` with no connection and no project
  capability host, and Foundry created one capability host of its own on the account
  (`<account>@aml_aiagentservice`);
- the roles by ID and the registry's repository-permission mode plan cleanly a second time: a plan
  of the created resources answered "No changes";
- the registry's `roleAssignmentMode` doesn't come back from the ARM API (`2025-04-01` returns
  none), while its ARM-audience token policy reads `enabled`;
- a trial subscription's gpt-4o quota in Canada East is 0, so the Standard deployment fails with
  `InsufficientQuota`, and the trial refuses ACR Tasks (`TasksOperationsNotAllowed`), so no image
  was built there. The two facts that need a deployment and an image are answered by the
  documentation instead, with that label (book D-039; the pages are under
  chapter 8 in [LINKS.md](../../LINKS.md)): with
  public network access off, a hosted agent's endpoint follows the account's network posture and is
  reachable through the private endpoint only, whatever path deployed the agent (the page the
  chapter quoted was rewritten on 2026-10-29, book #95); the project's managed identity pulls the
  image with Container Registry Repository Reader, and the pages describe the system-assigned
  identity, saying of a user-assigned one only that it must be set when the project is created. One
  question the pages raise stays open: they speak of a project connection to the registry, which
  this lab does not create and the first apply found absent, and whether the SDK path needs one is
  undocumented;
- the subscription carries Microsoft's own policy assignment `sys.blockwesteurope`, and nothing of
  the lab's.

The hosted agent itself is a data-plane object: the pipeline pushes the image to the registry and
creates an agent version with the Foundry SDK, pointing at the image's digest, and gives the Teams
bot the Foundry Agent Consumer role on that one agent. The registry uses the role assignment mode
for which Microsoft lists Container Registry Repository Reader, the project's pull role, so the
pipeline pushes with Container Registry Repository Writer; AcrPull and AcrPush aren't honored in
that mode.

Teardown is `terraform destroy -var-file=lab.tfvars`, which removes the budget last and purges the
deleted accounts, once the guard is off. The agents' account answers `RequestConflict` after its
project goes and took seventeen minutes to finish deleting on 2 November 2026; the delegated subnet
can't be deleted while the account's service association link holds it. A retry once the account
has gone succeeds, and the account it deleted in the background needs a purge of its own
(`sandbox/README.md`). The agents' account and the project carry
`prevent_destroy`, because replacing the account takes every project, agent and identity in it, so
a destroy, or any plan that would replace either of them, stops with an error. `prevent_destroy`
can't take a variable. In the sandbox's working copy, set both to `false` in `terraform/foundry.tf`,
run the destroy, and restore the file with `git checkout terraform/foundry.tf`. Never commit the
lifted guard.

## Part 2: the image

`image/Dockerfile` runs chapter 7's entry point (`../ch07/image/entrypoint.py`, reused rather than
copied) with `RUNTIME=foundry` on port 8088. Build it from `companion/labs` as the context, for
linux/amd64, the only platform Foundry runs:

```
docker build --platform linux/amd64 -f ch08/image/Dockerfile -t harness-foundry .
```

The build needs `ch08/image/private-ca.pem`, Larkspur's private root CA, and fails without it.
`*.pem` is git-ignored, so the reader or the pipeline writes the file there first. It goes into the
image as `/app/custom-roots.pem`, a file of its own. At start, and again before every question, the
entry point's `ca_bundle.py` combines it with the CA bundle the runtime provides, or with certifi's
when the runtime sets none, and points `SSL_CERT_FILE` and `REQUESTS_CA_BUNDLE` at the result. That
is Microsoft's guidance for egress controls: with them on, the runtime injects its egress proxy's
CA, which rotates about every 30 days, so the image carries none of Microsoft's certificates and
never keeps a copy of the runtime's bundle.

The rest is the agent version's environment, set when the pipeline creates the version with the
Foundry SDK and the image's digest: `GATEWAY_URL`, `WORKFLOW`, `MODEL_ALIAS`, `DATA_CLASS`,
`MCP_URL`, `OTEL_EXPORTER_OTLP_ENDPOINT`, and `GATEWAY_KEY` as a
`${{connections.<name>.credentials.<field>}}` placeholder that Foundry resolves at runtime from a
project connection. Microsoft reserves the `AGENT_*` and `FOUNDRY_*` names for the platform.
`PYTHONNOUSERSITE=1` keeps Python from loading packages out of `$HOME`, the session's storage,
which callers can upload files into.

Chapter 5's runtime adapter serves Foundry's contract, and building this image found four gaps in
it, now closed there. The last spans were lost on SIGTERM. The response didn't carry the session it
ran in (`x-agent-session-id`), so a caller that let Foundry create the session couldn't come back to
the same sandbox. The platform's `x-agent-user-id` was dropped; it now goes on every audit line of
the run. A body without a message ran the harness on an empty question; it is now a 400.

The adapter also keeps each sandbox to one engineer. Microsoft's page on isolating sessions per user
says "Within delegation, the platform doesn't fence one delegated end user from another" and "if you
route two users to the same session, they can see each other's data", and chapter 4 never reuses a
session across people. The adapter writes the first `x-agent-user-id` a sandbox sees to `$HOME`,
which the platform keeps for the session's life, and answers a request that carries any other with
a 403, without running the harness. A request without the header, as in a local run, is served and
pins nothing.

The image has not been built here, because this machine has no container engine. Its entry point
has run as a real process: readiness answered 200, and after SIGTERM it exited 0 with its spans
sent. In-process, a question went end to end through a stand-in gateway and chapter 5's MCP server,
and a question after the runtime's bundle rotated still verified.

## Tests

```
python -m pytest -q tests/
```

This lab's environment runs the Terraform, register and cost-sheet tests and skips the image's,
which need chapter 5's packages: 21 passed and 1 skipped (the image module) on 29 October 2026. In
chapter 5's environment, `python -m pytest -q tests/test_image.py` runs all eighteen image tests:
18 passed. Chapter 7's environment runs the whole folder and skips the seven image tests that need
chapter 5's packages: 32 passed. The record is `results/2026-10-29/pytest.txt`;
`results/2026-10-29/terraform-validate.txt` holds the validate output.

| File | Tests | What it checks |
|---|---|---|
| `tests/test_terraform.py` | 17 | the agents' account private, keyless and injected at creation, with no model deployment and the policy that refuses one; the account and the project kept from replacement; only Standard and Regional Provisioned deployments in the models account; only the gateway's identity may call the models; roles assigned by ID; the Standard deployment in Canada that never upgrades itself; the project's user-assigned identity and its pull role; the private registry that accepts ARM-audience tokens; private endpoints; both accounts' logs; the budget first; cost tags; `terraform validate` |
| `tests/test_models_and_costs.py` | 5 | every model in the register with its stage, retirement date, replacement and page dates; the pinned model is the one Terraform deploys in Canada East, a new subscription can still deploy it (GA or Legacy), and it is more than 90 days from retirement; the dated cost sheet prices it where it runs |
| `tests/test_image.py` | 18 | the Dockerfile (base pinned by digest, Larkspur's root as a file of its own, chapter 7's entry point on 8088, `PYTHONNOUSERSITE`, a user of its own, chapter 5's pinned set and nothing proprietary); the combined CA bundle against a server Larkspur's test root signed, with and without a runtime bundle, and through a rotation; the entry point as a process on Foundry's routes, one question end to end, and a clean stop on SIGTERM |
