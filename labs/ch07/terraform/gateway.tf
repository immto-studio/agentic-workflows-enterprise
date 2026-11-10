# The workflow's egress Agent Gateway: every outbound call of every agent in this project and
# region goes through it (Google requires them all to bind to the same one), and it refuses
# everything an IAM policy doesn't grant. One gateway per workflow project, so audit-only mode
# and the gateway's CA belong to one workflow.

locals {
  # Google's "Allowlist essential APIs": without these an agent's invocations fail with a 498.
  # Hostname matching is exact, so every variant the SDKs resolve is listed. The pipeline
  # registers each one and grants it to the agent's principal beside the manifest's tools.
  essential_apis = [
    "agentregistry", "aiplatform", "cloudresourcemanager", "cloudtrace", "iamcredentials",
    "logging", "monitoring", "secretmanager", "telemetry",
  ]
  essential_endpoints = concat(
    [for api in local.essential_apis : "${api}.googleapis.com"],
    [for api in local.essential_apis : "${api}.mtls.googleapis.com"],
    ["${var.region}-aiplatform.googleapis.com", "aiplatform.${var.region}.rep.googleapis.com"],
  )
}

resource "google_network_services_agent_connectivity_template" "egress" {
  agent_connectivity_template_id = "${var.workflow}-egress"
  location                       = var.region
  access_path                    = "AGENT_TO_ANYWHERE"

  egress_network_config {
    vpc_egress         = "ALL_TRAFFIC" # the mode the perimeter's enforcement needs
    network_attachment = var.network_attachment
    dns_peering_config {
      domains        = [var.internal_domain]
      target_network = var.vpc_network
    }
    tls_config {
      trust_config     = var.trust_config
      additional_roots = "NO_ADDITIONAL_ROOTS"
    }
  }

  depends_on = [google_project_service.platform]
}

resource "google_network_services_agent_gateway" "egress" {
  name     = "${var.workflow}-egress"
  location = var.region

  google_managed {
    governed_access_path = "AGENT_TO_ANYWHERE"
  }

  agent_connectivity_template = "projects/${var.project_number}/locations/${var.region}/agentConnectivityTemplates/${google_network_services_agent_connectivity_template.egress.agent_connectivity_template_id}"
  registries                  = ["//agentregistry.googleapis.com/projects/${var.project_id}/locations/${var.region}"]

  depends_on = [google_project_service.platform]
}

# IAM decides at the gateway through Identity-Aware Proxy; the agent needs
# iap.resources.egressViaIAP on each registered destination.
resource "google_network_services_authz_extension" "iap" {
  name      = "${var.workflow}-egress-iap"
  location  = var.region
  service   = "iap.googleapis.com"
  timeout   = "0.1s"
  fail_open = false # an IAP failure refuses the call
  metadata  = var.gateway_dry_run ? { iamEnforcementMode = "DRY_RUN" } : {}

  depends_on = [google_project_service.platform]
}

resource "google_network_security_authz_policy" "egress" {
  name           = "${var.workflow}-egress"
  location       = var.region
  policy_profile = "REQUEST_AUTHZ"
  action         = "CUSTOM"

  target {
    resources = [google_network_services_agent_gateway.egress.id]
  }

  custom_provider {
    authz_extension {
      resources = [google_network_services_authz_extension.iap.id]
    }
  }

  depends_on = [google_project_service.platform]
}
