# The sandbox-quill workspace as its state fixture describes it (servers/state_fake.py, the second
# version): the code W5's templates are written into before `terraform init -backend=false` and
# `terraform validate` (detect/validate.py). The provider reaches no API. The notebook's tags lack
# cost_center and data_classification here too; the scratch volume is here and gone from the cloud.

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

resource "aws_instance" "notebook" {
  ami                    = "ami-0f1e2d3c4b5a69788"
  instance_type          = "m5.xlarge"
  subnet_id              = "subnet-0d2b2c3d4e5f60051"
  vpc_security_group_ids = [aws_security_group.notebook.id]
  private_ip             = "10.90.4.11"
  ebs_optimized          = true
  monitoring             = false

  root_block_device {
    volume_size           = 100
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = true
  }

  tags = {
    owner_team = "quill-data"
    env        = "sandbox"
    service    = "quill-notebooks"
  }
}

resource "aws_instance" "batch" {
  ami                    = "ami-0f1e2d3c4b5a69788"
  instance_type          = "t4g.medium"
  subnet_id              = "subnet-0d2b2c3d4e5f60051"
  vpc_security_group_ids = [aws_security_group.notebook.id]
  private_ip             = "10.90.4.12"
  ebs_optimized          = true
  monitoring             = false

  root_block_device {
    volume_size           = 30
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = true
  }

  tags = {
    owner_team          = "quill-data"
    cost_center         = "CC-9901"
    env                 = "sandbox"
    service             = "quill-batch"
    data_classification = "internal"
    Name                = "quill-batch"
  }
}

resource "aws_ebs_volume" "scratch" {
  availability_zone = "ca-central-1a"
  size              = 200
  type              = "gp3"
  iops              = 3000
  encrypted         = true

  tags = {
    owner_team          = "quill-data"
    cost_center         = "CC-9901"
    env                 = "sandbox"
    service             = "quill-batch"
    data_classification = "internal"
    Name                = "quill-scratch"
  }
}

resource "aws_ebs_volume" "archive" {
  availability_zone = "ca-central-1a"
  size              = 1000
  type              = "gp3"
  iops              = 3000
  encrypted         = true

  tags = {
    owner_team          = "quill-data"
    cost_center         = "CC-9901"
    env                 = "sandbox"
    service             = "quill-batch"
    data_classification = "internal"
    Name                = "quill-archive"
  }
}

resource "aws_security_group" "notebook" {
  name        = "notebook"
  description = "Quill notebooks and batch"
  vpc_id      = "vpc-0d2b2c3d4e5f60000"

  ingress {
    description = "SSH from the sandbox VPC"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["10.90.0.0/16"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    owner_team          = "quill-data"
    cost_center         = "CC-9901"
    env                 = "sandbox"
    service             = "quill-batch"
    data_classification = "internal"
  }
}

module "budget_alarm" {
  source = "./modules/budget_alarm"
}

output "notebook_instance_id" {
  value = aws_instance.notebook.id
}

output "budget_id" {
  value = module.budget_alarm.budget_id
}
