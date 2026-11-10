# Grants for the project's service agents, and the deny that keeps models behind the gateway.
#
# Terraform grants the agent's own identity nothing. Google grants every agent identity
# roles/aiplatform.agentDefaultAccess and roles/aiplatform.agentContextEditor by default, and
# the first includes aiplatform.endpoints.predict; the egress gateway must also let the agent
# reach the Agent Platform API for its sessions. The deny policy below is therefore what keeps
# a direct model call out of the harness's reach. The pipeline lists the principal's roles
# after every apply (README) and fails when one appears that it didn't expect.

locals {
  # Google names the service agents after the project number.
  agent_platform_agent   = "service-${var.project_number}@gcp-sa-aiplatform.iam.gserviceaccount.com"
  reasoning_engine_agent = "service-${var.project_number}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"

  # Production: a folder that holds only agent projects, with the gateway pair's project outside
  # it. A sandbox without an organization has no folder, so the deny sits on the project.
  deny_scope_type   = var.deny_folder_number == null ? "projects" : "folders"
  deny_scope_number = var.deny_folder_number == null ? var.project_number : var.deny_folder_number
  deny_parent       = var.deny_folder_number == null ? var.project_id : var.deny_folder_number
}

resource "google_artifact_registry_repository_iam_member" "image_reader" {
  location   = var.region
  repository = var.image_repository
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${local.reasoning_engine_agent}"
  depends_on = [google_billing_budget.workflow]
}

# secret_env is read by a service agent, not by the agent identity, so any agent deployed in
# this project could name this secret: one project per workflow. The provider's documentation
# names the Reasoning Engine service agent and Google's agent identity page the Agent Platform
# service agent; both are granted until a first apply shows which one reads it.
resource "google_secret_manager_secret_iam_member" "gateway_key_reader" {
  for_each   = toset([local.reasoning_engine_agent, local.agent_platform_agent])
  secret_id  = var.gateway_key_secret
  role       = "roles/secretmanager.secretAccessor"
  member     = "serviceAccount:${each.value}"
  depends_on = [google_billing_budget.workflow]
}

resource "google_kms_crypto_key_iam_member" "agent_platform" {
  crypto_key_id = var.kms_key
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${local.agent_platform_agent}"
  depends_on    = [google_billing_budget.workflow]
}

resource "google_iam_deny_policy" "models_through_gateway" {
  parent       = urlencode("cloudresourcemanager.googleapis.com/${local.deny_scope_type}/${local.deny_parent}")
  name         = "models-through-gateway"
  display_name = "Only the model gateway sends prompts"

  rules {
    description = "Prompts from every principal but the model gateway and Google's service agents are denied"
    deny_rule {
      denied_principals = ["principalSet://goog/public:all"]
      exception_principals = [
        "principal://iam.googleapis.com/projects/-/serviceAccounts/${var.model_gateway_service_account}",
        # Google's recommendation for deny rules that could catch its service agents. It also
        # lets Memory Bank's own model calls through, which is why its models are pinned.
        "principalSet://cloudresourcemanager.googleapis.com/${local.deny_scope_type}/${local.deny_scope_number}/type/ServiceAgent",
      ]
      denied_permissions = [
        "aiplatform.googleapis.com/endpoints.predict",
        "aiplatform.googleapis.com/batchPredictionJobs.create",
        "aiplatform.googleapis.com/cachedContents.create",
        "aiplatform.googleapis.com/interactions.create",
        "aiplatform.googleapis.com/memories.generate",
      ]
    }
  }

  depends_on = [google_billing_budget.workflow]
}
