# Lab safety

Rules for every lab in this repository. They exist because agent labs create resources that keep billing when nobody is looking.

## Spending

- Cap: 150 USD per month per cloud (book D-018). A budget alarm is the first resource created in every account (`terraform/billing-alarms`).
- AWS: the lab account is on AWS's free plan, whose credits are the cap (book D-029), and it can create resources in us-east-2 only (book D-034). A lab whose Terraform targets Larkspur's ca-central-1 runs in us-east-2 on synthetic data (book D-036).
- Azure: a trial subscription with its spending limit on, which stays a trial (book D-035, D-039).
- Google Cloud: a lab project reached through Workload Identity Federation with an X.509 certificate; it holds no service account key (book D-040).
- Local models run on the workstation's GPU at no cost per token, one model on the GPU at a time.
- Known traps: Amazon OpenSearch Serverless behind Knowledge Bases bills by compute unit even when idle; GPU nodes on Kubernetes bill per hour whether or not a model is loaded; provisioned throughput on any provider is never used in labs.
- Every lab README states its expected cost per hour and per run.

## Teardown

- Every lab ends with `terraform destroy` or an equivalent script in the session that applied it, and the README says how to confirm nothing is left. On AWS, `labs/ch06/sandbox/leftovers.py` lists what remains by the labs' names and tags.
- Nothing is left running overnight. If a lab needs state across days, the README says what to keep and what it costs.

## Identity

- Labs use a dedicated account or project, never a production one.
- Each lab role or service account has the minimum permissions for that lab, written out in Terraform so the reader can audit them.
- Credentials come from environment variables (`.env` outside the repository). The repository contains no keys, and the `.gitignore` refuses common key file names.

## Data

- Labs use synthetic data only (generated Larkspur documents, fake tickets, fake metrics). No real customer, employee or company data.

## Reproducibility

- Provider versions and model identifiers are pinned in every lab.
- Each README records the date the lab was last run successfully and the versions used.

## When the work pauses

Before a pause, every applied lab's teardown has run, and a read-only check confirms that nothing in the three clouds bills. The check is a set of the author's scripts, kept outside this repository; for chapter 6 there is also `labs/ch06/sandbox/leftovers.py`. On 10 November 2026 all three clouds were idle: AWS on its free plan with nothing running, the Azure trial with its spending limit on and no model deployments, and the Google Cloud trial project with no running services.

