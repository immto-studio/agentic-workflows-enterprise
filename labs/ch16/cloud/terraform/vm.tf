# The Langfuse VM: Ubuntu 24.04 from Canonical's published parameter, Docker and the Compose plugin from
# Ubuntu's own packages, and Langfuse v4.74.0 from its Compose file (cloud/langfuse/, vendored from the
# release tag at step 1 with its SHA-256 recorded) with the two floating `:4` images pinned by an override
# file. The user data writes the files, installs Docker, pulls and starts the stack, and leaves markers
# the session reads back over SSH: the versions, the images with their digests, Langfuse's health answer,
# and the moment the stack answered. The headless init makes the organization, the project and the API
# keys the Collector uses (fact sheet 8.5).

data "aws_ssm_parameter" "ubuntu" {
  name = "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
}

locals {
  compose  = file("${path.module}/../langfuse/docker-compose.yml")
  override = templatefile("${path.module}/../langfuse/docker-compose.override.yml.tftpl", { version = var.langfuse_version })
  env = templatefile("${path.module}/templates/langfuse.env.tftpl", {
    public_key      = var.langfuse_public_key
    secret_key      = var.langfuse_secret_key
    nextauth_secret = var.langfuse_nextauth_secret
    salt            = var.langfuse_salt
    encryption_key  = var.langfuse_encryption_key
    user_email      = var.langfuse_user_email
    user_password   = var.langfuse_user_password
    store_password  = var.store_password
  })
}

resource "aws_instance" "langfuse" {
  ami                         = data.aws_ssm_parameter.ubuntu.insecure_value
  instance_type               = var.instance_type
  subnet_id                   = aws_subnet.public.id
  vpc_security_group_ids      = [aws_security_group.vm.id]
  associate_public_ip_address = true # outbound only (network.tf)
  user_data_replace_on_change = true

  user_data = templatefile("${path.module}/templates/user-data.sh.tftpl", {
    compose_b64gz = base64gzip(local.compose)
    override_b64  = base64encode(local.override)
    env_b64       = base64encode(local.env)
    version       = var.langfuse_version
  })

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_gib
    encrypted             = true
    delete_on_termination = true
  }

  tags = { Name = "${var.name}-langfuse" }

  depends_on = [aws_budgets_budget.session, aws_route_table_association.public]
}
