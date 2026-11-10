# The network-live workspace as its state fixture describes it (servers/state_fake.py, the third version):
# the code W5's templates are written into before `terraform init -backend=false` and `terraform validate`
# (detect/validate.py). The provider reaches no API: validate needs its schema and nothing else. The route
# to 10.251.0.0/24 is not here; it was added by hand (the postmortem's shape).

terraform {
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.71.0"
    }
  }
}

provider "aws" {
  region                      = "ca-central-1" # a placeholder: validate makes no request
  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
}

resource "aws_vpc" "main" {
  cidr_block           = "10.40.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    owner_team          = "network-engineering"
    cost_center         = "CC-4412"
    env                 = "prod"
    service             = "network-live"
    data_classification = "internal"
    Name                = "network-live"
  }
}

resource "aws_route_table" "private_a" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block         = "10.0.0.0/8"
    transit_gateway_id = "tgw-0a1b2c3d4e5f60030"
  }

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = "nat-0a1b2c3d4e5f60041"
  }

  tags = {
    owner_team          = "network-engineering"
    cost_center         = "CC-4412"
    env                 = "prod"
    service             = "network-live"
    data_classification = "internal"
    Name                = "network-live-private-a"
  }
}

resource "aws_route_table" "private_b" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block         = "10.0.0.0/8"
    transit_gateway_id = "tgw-0a1b2c3d4e5f60030"
  }

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = "nat-0a1b2c3d4e5f60041"
  }

  tags = {
    owner_team          = "network-engineering"
    cost_center         = "CC-4412"
    env                 = "prod"
    service             = "network-live"
    data_classification = "internal"
    Name                = "network-live-private-b"
  }
}

resource "aws_security_group" "eks_nodes" {
  name        = "network-live-eks-nodes"
  description = "EKS node range"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTPS from the VPC"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["10.40.0.0/16"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    owner_team          = "network-engineering"
    cost_center         = "CC-4412"
    env                 = "prod"
    service             = "network-live"
    data_classification = "internal"
    Name                = "network-live-eks-nodes"
  }
}

resource "aws_security_group" "mq_bridge" {
  name        = "network-live-mq-bridge"
  description = "MQ bridge to the mainframe channel"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "IBM MQ channel 1414 from the EKS node range"
    from_port   = 1414
    to_port     = 1414
    protocol    = "tcp"
    cidr_blocks = ["10.40.0.0/16"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    owner_team          = "network-engineering"
    cost_center         = "CC-4412"
    env                 = "prod"
    service             = "network-live"
    data_classification = "internal"
    Name                = "network-live-mq-bridge"
  }
}

resource "aws_ec2_transit_gateway_vpc_attachment" "main" {
  transit_gateway_id     = "tgw-0a1b2c3d4e5f60030"
  vpc_id                 = aws_vpc.main.id
  subnet_ids             = ["subnet-0a1b2c3d4e5f60051", "subnet-0a1b2c3d4e5f60052"]
  dns_support            = "enable"
  appliance_mode_support = "disable"

  tags = {
    owner_team          = "network-engineering"
    cost_center         = "CC-4412"
    env                 = "prod"
    service             = "network-live"
    data_classification = "internal"
    Name                = "network-live-tgw"
  }
}

module "tgw_routes" {
  source = "./modules/tgw_routes"

  transit_gateway_attachment_id = aws_ec2_transit_gateway_vpc_attachment.main.id
}

output "vpc_id" {
  value = aws_vpc.main.id
}

output "private_route_table_ids" {
  value = [aws_route_table.private_a.id, aws_route_table.private_b.id]
}
