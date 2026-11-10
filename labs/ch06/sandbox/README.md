# Chapter 6's sandbox: stand-ins for a first apply on synthetic data

Chapter 6's Terraform builds the incident workflow on AgentCore and takes the rest of Larkspur's
platform as given: a VPC with private subnets, the model gateway, the collector, the MCP servers,
the tool servers' roles, the gateway key, the private root CA, and the harness image. This folder
makes stand-ins for those in a sandbox account, so the lab can be applied, checked and destroyed in
one session. None of it is Larkspur's design.

Larkspur runs the workflow in ca-central-1, because its Confidential data stays in Canada, and the
lab's `region` refuses any other Region unless `synthetic_data = true`. An account from AWS's newer
sign-up is a project in an organization AWS manages, and AWS's own service control policy lets it
create resources only in the Region AWS assigned it (US East (Ohio) for a Canadian address); it may
call Bedrock's models anywhere. Such an account runs the lab in its own Region on synthetic data
(book D-034, D-036).

What it makes, in the Region you give it:

- a VPC with two private subnets in Availability Zones that AgentCore Runtime and the tool
  gateway's private targets both support, a route table with the local route only, and the security
  groups of the model gateway, the collector, and the MCP servers, with nothing behind them;
- an EKS control plane with no nodes and a private endpoint, the cluster the tool roles' access
  entries name;
- an ECR repository and a CodeBuild project that builds the harness image for linux/arm64 (no Docker
  is needed on your machine);
- the tool servers' and the model gateway's base roles, which nothing assumes;
- the gateway key's secret, which holds no key;
- a root CA made here and valid for two days, in an S3 object the lab's `private_ca_s3_uri` names;
- two MCP stand-ins (`mcp_stand_ins.tf`, `mcp_stand_in/`): one function answering as `k8s-mcp` and
  `knowledge-mcp` by the Host header, with the catalog's four tools (`tools.json`), behind an internal
  Application Load Balancer that terminates TLS with a certificate the sandbox root signed, under the
  names the lab's `k8s_mcp_endpoint` and `knowledge_mcp_endpoint` carry in a private hosted zone; the
  function checks no token and logs the one it is shown by its claims, so the log records what the
  gateway sent (book #69);
- the bot's stand-in (`bot_stand_ins.tf`, `bot_stand_in/`): a function inside the VPC that makes the
  one invocation, because the lab's runtime takes a call only through Larkspur's AgentCore endpoint.

What it doesn't make: Entra app registrations, the model gateway, and the collector. The four
registrations are the author's, made once in the trial's tenant (book #69) and passed in with
`--entra-apps`; without that file `lab.tfvars` gives the runtime and the tool gateway placeholder
client IDs, so the runtime accepts no token and the tool gateway's targets end `FAILED` on the OAuth
grant, which is what the first apply of 30 October 2026 showed. The model gateway and the collector
stay names that resolve to nothing, so an invocation ends at the model call.

Run (from `labs/ch06/sandbox`, with AWS credentials in the environment and, for the Entra steps,
`AZURE_CONFIG_DIR` naming an Azure CLI profile that may read and change the four registrations):

```
terraform init
terraform apply -var region=us-east-2 -var 'az_ids=["use2-az1","use2-az2"]'
python sandbox.py image                                   # the image, built in CodeBuild, with the four-tool lock
python sandbox.py tfvars --entra-apps <registrations.json> # ../terraform/lab.tfvars with the author's apps
cd ../terraform
terraform apply -var-file=lab.tfvars -target=aws_budgets_budget.account
terraform apply -var-file=lab.tfvars -target=aws_kms_key.tool_gateway_signing
cd ../sandbox
python sandbox.py signing-cert --entra-apps <registrations.json>   # step 6: the KMS-signed certificate, uploaded
python sandbox.py tfvars --entra-apps <registrations.json>         # again, now with the thumbprint
cd ../terraform
terraform apply -var-file=lab.tfvars                      # the targets end FAILED without the CA (step 7)
cd ../sandbox
python sandbox.py register-ca                             # both targets READY
cd ../terraform
terraform untaint 'aws_bedrockagentcore_gateway_target.mcp["k8s"]'
terraform untaint 'aws_bedrockagentcore_gateway_target.mcp["knowledge"]'
terraform apply -var-file=lab.tfvars                      # the Cedar permits
cd ../sandbox
python check.py --out ../results/<date>/first-apply.json
python invoke.py --entra-apps <registrations.json> --out ../results/<date>/invocation.json
```

The registrations file holds client and object IDs only (no secret exists for any of the four):
`entra_tenant_id`, `entra_runtime_client_id`, `entra_bot_client_id`, `entra_tool_gateway_client_id`,
`tool_gateway_object_id`, `bot_object_id`, `mcp_servers_scope`; `signing-cert` writes
`entra_tool_gateway_cert_thumbprint` into it. `invoke.py` gives the bot's app a two-day certificate
for the session, takes a client-credentials token for the runtime's `.default` scope, and calls the
runtime through the bot stand-in with a session ID that ends as the adapter requires.

Teardown, in the same session: `terraform destroy -var-file=lab.tfvars` in `../terraform`
(`force_destroy_stores` is already true), then `terraform destroy` here with the same `-var` flags.
The VPC can outlast the rest: AgentCore removes the runtime's network interfaces up to eight hours
after the runtime is deleted, Lambda removes the bot stand-in's some minutes after the function, and
the subnets wait for them. Nothing left in the VPC bills by the hour. The cluster and the load
balancer bill by the hour while they exist, so they go in the same destroy. Once AWS has freed the
interfaces, run both destroys again, then `python leftovers.py --region <Region>`, which lists,
read-only, whatever the lab or the sandbox left, KMS keys pending deletion included. The four Entra
registrations are deleted by hand afterwards (`az ad app delete`), the certificates with them.
