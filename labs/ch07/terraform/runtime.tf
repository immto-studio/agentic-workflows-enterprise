# The skeleton's harness, in its own container (labs/ch07/image), as an Agent Runtime agent.

locals {
  models = "projects/${var.project_id}/locations/${var.region}/publishers/google/models"
  ttl    = "${var.memory_retention_days * 86400}s"
}

resource "google_vertex_ai_reasoning_engine" "harness" {
  display_name    = var.workflow
  description     = "The platform harness of the skeleton, behind the runtime adapter"
  region          = var.region
  labels          = { workflow = var.workflow, owner = var.owner }
  deletion_policy = var.deletion_policy

  encryption_spec {
    kms_key_name = var.kms_key
  }

  spec {
    # A principal of its own; Agent Gateway bindings require it.
    identity_type = "AGENT_IDENTITY"

    container_spec {
      image_uri = var.harness_image # by digest; the variable refuses a tag
      port      = 8080
    }

    # Terraform doesn't discover methods: declare the one the adapter serves.
    class_methods = jsonencode([{
      name     = "query"
      api_mode = ""
      parameters = {
        type       = "object"
        required   = ["message"]
        properties = { message = { type = "string" } }
      }
    }])

    deployment_spec {
      min_instances         = 1
      max_instances         = 10
      resource_limits       = { cpu = "2", memory = "2Gi" }
      container_concurrency = 5 # 2 x cpu + 1, as the provider recommends

      # The image's entry point serves both Agent Runtime and Foundry; this picks Google's route.
      env {
        name  = "RUNTIME"
        value = "agent-runtime"
      }
      env {
        name  = "GATEWAY_URL"
        value = var.gateway_url
      }
      env {
        name  = "WORKFLOW"
        value = var.workflow
      }
      env {
        name  = "MODEL_ALIAS"
        value = var.model_alias
      }
      env {
        name  = "DATA_CLASS"
        value = var.data_class
      }
      env {
        name  = "MCP_URL"
        value = var.mcp_url
      }
      env {
        name  = "OTEL_EXPORTER_OTLP_ENDPOINT"
        value = var.otel_endpoint
      }

      secret_env {
        name = "GATEWAY_KEY"
        secret_ref {
          secret  = var.gateway_key_secret
          version = var.gateway_key_version
        }
      }

      # Every outbound call, platform APIs included, goes through this gateway.
      # Changing the binding archives every earlier revision.
      agent_gateway_config {
        agent_to_anywhere_config {
          agent_gateway = google_network_services_agent_gateway.egress.id
        }
      }
    }
  }

  # The platform's harness keeps no memories. These are the defaults every engine gets, for
  # the ADK agents that do: the manifest's retention, for memories and their revisions, and
  # models Google's residency table lists as processed in Canada.
  context_spec {
    memory_bank_config {
      generation_config {
        model = "${local.models}/gemini-3.5-flash"
      }
      similarity_search_config {
        embedding_model = "${local.models}/text-multilingual-embedding-002"
      }
      ttl_config {
        default_ttl                 = local.ttl
        memory_revision_default_ttl = local.ttl
      }
    }
  }

  depends_on = [
    google_billing_budget.workflow,
    google_artifact_registry_repository_iam_member.image_reader,
    google_secret_manager_secret_iam_member.gateway_key_reader,
    google_kms_crypto_key_iam_member.agent_platform,
    google_network_security_authz_policy.egress,
  ]
}
