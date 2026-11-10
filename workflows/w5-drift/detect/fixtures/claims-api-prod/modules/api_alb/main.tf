# module.api_alb of the claims-api-prod fixture: the internal application load balancer.

variable "security_group_ids" {
  type = list(string)
}

variable "subnet_ids" {
  type = list(string)
}

resource "aws_lb" "api" {
  name               = "claims-api-prod"
  internal           = true
  load_balancer_type = "application"
  security_groups    = var.security_group_ids
  subnets            = var.subnet_ids

  tags = {
    owner_team          = "claims-platform"
    cost_center         = "CC-3120"
    env                 = "prod"
    service             = "claims-api"
    data_classification = "confidential"
    Name                = "claims-api-prod"
  }
}

output "dns_name" {
  value = aws_lb.api.dns_name
}
