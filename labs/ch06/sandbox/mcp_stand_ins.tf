# Stand-ins for Larkspur's two MCP servers, so the tool gateway's targets have something to list
# tools from (book #69). One Lambda function answers as both servers, by the Host header, behind an
# internal Application Load Balancer that terminates TLS with a certificate the sandbox root signed;
# a private hosted zone gives the servers the names the lab's `k8s_mcp_endpoint` and
# `knowledge_mcp_endpoint` carry. The gateway's interfaces reach the load balancer through the
# MCP servers' security group, which admits HTTPS from the VPC here (Larkspur's admits the
# gateway's group alone; that group is the lab's and doesn't exist before the lab's apply).
#
# None of this is Larkspur's design, and the function checks no token: what the sandbox tests is
# the gateway's side, the OAuth grant with the KMS-signed credential, the CA from S3, and the tool
# definitions it relays. The load balancer bills by the hour while it exists and goes with the
# destroy. The archive provider that zips the function is pinned in main.tf with the others.

locals {
  mcp_zone  = "sandbox.larkspur.example"
  mcp_hosts = { k8s = "k8s-mcp", knowledge = "knowledge-mcp" }
  mcp_names = [for host in values(local.mcp_hosts) : "${host}.${local.mcp_zone}"]
}

# --- the names ----------------------------------------------------------------------------------

resource "aws_route53_zone" "sandbox" {
  name    = local.mcp_zone
  comment = "The sandbox's private names for the MCP stand-ins"

  vpc {
    vpc_id = aws_vpc.lab.id
  }
}

resource "aws_route53_record" "mcp" {
  for_each = local.mcp_hosts

  zone_id = aws_route53_zone.sandbox.zone_id
  name    = "${each.value}.${local.mcp_zone}"
  type    = "A"

  alias {
    name                   = aws_lb.mcp.dns_name
    zone_id                = aws_lb.mcp.zone_id
    evaluate_target_health = false
  }
}

# --- the server certificate, from the sandbox root ----------------------------------------------

resource "tls_private_key" "mcp" {
  algorithm   = "ECDSA"
  ecdsa_curve = "P256"
}

resource "tls_cert_request" "mcp" {
  private_key_pem = tls_private_key.mcp.private_key_pem
  dns_names       = local.mcp_names

  subject {
    common_name  = local.mcp_names[0]
    organization = "Larkspur Mutual (fictional)"
  }
}

resource "tls_locally_signed_cert" "mcp" {
  cert_request_pem      = tls_cert_request.mcp.cert_request_pem
  ca_private_key_pem    = tls_private_key.root.private_key_pem
  ca_cert_pem           = tls_self_signed_cert.root.cert_pem
  validity_period_hours = 48
  allowed_uses          = ["key_encipherment", "digital_signature", "server_auth"]
}

resource "aws_acm_certificate" "mcp" {
  private_key       = tls_private_key.mcp.private_key_pem
  certificate_body  = tls_locally_signed_cert.mcp.cert_pem
  certificate_chain = tls_self_signed_cert.root.cert_pem
  tags              = { Name = "${var.name}-mcp" }
}

# --- the load balancer, in the MCP servers' security group -----------------------------------------

resource "aws_vpc_security_group_ingress_rule" "mcp_https" {
  security_group_id = aws_security_group.stand_in["mcp-servers"].id
  description       = "HTTPS from the VPC (the gateway interfaces, in the sandbox)"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = local.cidr
}

resource "aws_lb" "mcp" {
  name               = "${var.name}-mcp"
  internal           = true
  load_balancer_type = "application"
  subnets            = aws_subnet.private[*].id
  security_groups    = [aws_security_group.stand_in["mcp-servers"].id]
}

resource "aws_lb_target_group" "mcp" {
  name        = "${var.name}-mcp"
  target_type = "lambda"
}

resource "aws_lambda_permission" "mcp_alb" {
  statement_id  = "AllowTheLoadBalancer"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.mcp.function_name
  principal     = "elasticloadbalancing.amazonaws.com"
  source_arn    = aws_lb_target_group.mcp.arn
}

resource "aws_lb_target_group_attachment" "mcp" {
  target_group_arn = aws_lb_target_group.mcp.arn
  target_id        = aws_lambda_function.mcp.arn
  depends_on       = [aws_lambda_permission.mcp_alb]
}

resource "aws_lb_listener" "mcp" {
  load_balancer_arn = aws_lb.mcp.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate.mcp.arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.mcp.arn
  }
}

# --- the function -------------------------------------------------------------------------------

data "archive_file" "mcp" {
  type        = "zip"
  source_dir  = "${path.module}/mcp_stand_in"
  output_path = "${path.module}/.terraform/mcp-stand-in.zip"
}

data "aws_iam_policy_document" "lambda_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "mcp" {
  name               = "${var.name}-mcp-stand-in"
  description        = "The MCP stand-in's role: its own log group, nothing else"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_cloudwatch_log_group" "mcp" {
  name              = "/aws/lambda/${var.name}-mcp-stand-in"
  retention_in_days = 1
}

data "aws_iam_policy_document" "mcp_logs" {
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.mcp.arn}:*"]
  }
}

resource "aws_iam_role_policy" "mcp_logs" {
  name   = "logs"
  role   = aws_iam_role.mcp.id
  policy = data.aws_iam_policy_document.mcp_logs.json
}

resource "aws_lambda_function" "mcp" {
  function_name    = "${var.name}-mcp-stand-in"
  description      = "Answers as the k8s-mcp and knowledge-mcp servers: initialize, tools/list, tools/call"
  role             = aws_iam_role.mcp.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.mcp.output_path
  source_code_hash = data.archive_file.mcp.output_base64sha256
  timeout          = 10
  memory_size      = 256

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.mcp.name
  }

  depends_on = [aws_iam_role_policy.mcp_logs]
}

output "mcp_stand_ins" {
  description = "Where the stand-ins answer, and where their log is: the evidence of what the gateway sent them."
  value = {
    names       = local.mcp_names
    dns_name    = aws_lb.mcp.dns_name
    log_group   = aws_cloudwatch_log_group.mcp.name
    certificate = aws_acm_certificate.mcp.arn
  }
}
