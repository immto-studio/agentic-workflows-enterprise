# Chapter 8's sandbox: stand-ins for a first apply in a trial subscription

Chapter 8's Terraform takes Larkspur's network as inputs: a virtual network with the agents'
delegated subnet and the private endpoints' subnet, the four private DNS zones, and the managed
identity the model gateway runs as. This folder makes stand-ins for those in a sandbox subscription,
so the lab can be applied, read, and destroyed in one session (book D-037). None of it is Larkspur's
design.

What it makes, in Canada Central:

- a resource group, a virtual network, a /27 subnet delegated to `Microsoft.App/environments` for
  the agents (about twenty sessions: enough for a sandbox, and in Microsoft's words not for
  production), and a /27 subnet for the private endpoints;
- the four private DNS zones (`privatelink.cognitiveservices.azure.com`,
  `privatelink.openai.azure.com`, `privatelink.services.ai.azure.com`, `privatelink.azurecr.io`),
  linked to the network;
- a user-assigned identity standing in for the LiteLLM pods' identity, which the lab's role
  assignment names and nothing runs as;
- a root CA made here and valid for two days, for the image build.

Run (from `labs/ch08/sandbox`, with the `ARM_*` variables in the environment or in a file):

```
terraform init
terraform apply -var subscription_id=<the subscription>
python sandbox.py --azure-env <file> tfvars --budget-email <address>   # ../terraform/lab.tfvars
cd ../terraform
terraform apply -var-file=lab.tfvars -target=azurerm_consumption_budget_resource_group.workflow
terraform apply -var-file=lab.tfvars
cd ../sandbox
python sandbox.py --azure-env <file> check --out ../results/<date>/first-apply.json
python sandbox.py --azure-env <file> image        # ACR Tasks; the trial refuses it (below)
```

`check` reads, with the lab's service principal, what the apply made: both accounts and their
network injection, the project and its identity, its connections and capability hosts, the
deployments, the registry's mode and token policy, the private endpoints' state, the policy
assignments, and the budget. `leftovers` lists after a destroy what is left: resource groups,
soft-deleted Cognitive Services accounts, role assignments below the subscription, custom policy
definitions, and budgets.

What the trial subscription refused on 2 November 2026 (`../results/2026-11-02/`):

- the model deployment: `InsufficientQuota`, "The deployment requires 50 quota units, but only 0
  quota units are available in Tokens Per Minute (thousands) - gpt-4o". The quota rows read before
  the apply showed 0 of 0 for every gpt-4o form in Canada East. A trial deploys no OpenAI model
  without a quota request;
- ACR Tasks: `TasksOperationsNotAllowed`, "ACR Tasks requests for the registry ... are not
  permitted. Please file an Azure support request". The machine has no container engine either, so
  the trial built no image, and the facts that need an agent version stay open on it.

What the service principal lacked: `Microsoft.Authorization/policyDefinitions/write`
(`AuthorizationFailed`). Contributor doesn't carry it; Resource Policy Contributor does, on the
subscription, and the next run adds that role to the lab's identity (book #70).

Teardown, in the same session: in `../terraform`, set both `prevent_destroy` guards to `false` in
the working copy of `foundry.tf`, run `terraform destroy -var-file=lab.tfvars`, and restore the file
with `git checkout`. The agents' account answers `RequestConflict` ("provisioning state is not
terminal") after its project is deleted and stays `Deleting` for a while (seventeen minutes on
2 November 2026), and the delegated subnet answers `InUseSubnetCannotBeDeleted` while the account's
`serviceAssociationLinks/legionservicelink` holds it; both destroys succeed on a retry once the
account has gone. An account that finishes deleting in the background this way skips the
provider's purge and stays soft-deleted, so `leftovers` lists it; purge it with a `DELETE` on
`Microsoft.CognitiveServices/locations/<region>/resourceGroups/<group>/deletedAccounts/<name>`.
Then `terraform destroy` here, and `python sandbox.py leftovers`.
