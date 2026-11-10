# The claims worker's task definition, as the state fixture describes it (servers/state_fake.py). Its
# container definitions are one JSON string, which the provider's schema does not mark sensitive, and the
# database password reaches a container's environment from a variable nobody marked sensitive either: the
# state holds the string, password included, in clear. The state reader masks the attribute whole
# (servers/common.MASKED_ATTRIBUTES); the code holds no secret.

variable "claims_worker_db_password" {
  type = string
}

resource "aws_ecs_task_definition" "claims_worker" {
  family                   = "claims-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"

  container_definitions = jsonencode([
    {
      name      = "claims-worker"
      image     = "422233334444.dkr.ecr.ca-central-1.amazonaws.com/claims-worker:2026-10-16"
      essential = true
      environment = [
        { name = "DB_PASSWORD", value = var.claims_worker_db_password },
        { name = "QUEUE_URL", value = "https://sqs.ca-central-1.example/422233334444/claims-work" },
      ]
    }
  ])

  tags = {
    owner_team          = "claims-platform"
    cost_center         = "CC-3120"
    env                 = "prod"
    service             = "claims-worker"
    data_classification = "confidential"
  }
}
