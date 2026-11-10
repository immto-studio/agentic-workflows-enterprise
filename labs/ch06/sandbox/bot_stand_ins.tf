# The bot's stand-in: a function inside the VPC that makes the one invocation (book #69). The lab's
# runtime takes an invocation only through Larkspur's interface endpoint for AgentCore (the resource
# policy's aws:SourceVpce condition), which the sandbox's first invocation from a laptop confirmed
# with a 403, so the caller has to stand where the Teams bot stands: in the VPC, where the endpoint's
# private name resolves. The token for the bot's app is obtained outside (invoke.py) and handed to
# the function with the request; the function logs the status and nothing else.

resource "aws_security_group" "bot" {
  name        = "${var.name}-bot"
  description = "Stand-in for the bot: HTTPS to the interface endpoints"
  vpc_id      = aws_vpc.lab.id
}

resource "aws_vpc_security_group_egress_rule" "bot_https" {
  security_group_id = aws_security_group.bot.id
  description       = "to the endpoints in the VPC"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = local.cidr
}

data "archive_file" "bot" {
  type        = "zip"
  source_dir  = "${path.module}/bot_stand_in"
  output_path = "${path.module}/.terraform/bot-stand-in.zip"
}

resource "aws_iam_role" "bot" {
  name               = "${var.name}-bot-stand-in"
  description        = "The bot stand-in's role: its log group and the interfaces a function in a VPC needs"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_cloudwatch_log_group" "bot" {
  name              = "/aws/lambda/${var.name}-bot-stand-in"
  retention_in_days = 1
}

data "aws_iam_policy_document" "bot" {
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.bot.arn}:*"]
  }
  # What Lambda needs to put a function in a VPC (AWS's AWSLambdaVPCAccessExecutionRole, the EC2 part).
  statement {
    actions = ["ec2:CreateNetworkInterface", "ec2:DescribeNetworkInterfaces", "ec2:DeleteNetworkInterface",
    "ec2:DescribeSubnets", "ec2:DescribeSecurityGroups", "ec2:AssignPrivateIpAddresses", "ec2:UnassignPrivateIpAddresses"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "bot" {
  name   = "invoke-from-the-vpc"
  role   = aws_iam_role.bot.id
  policy = data.aws_iam_policy_document.bot.json
}

resource "aws_lambda_function" "bot" {
  function_name    = "${var.name}-bot-stand-in"
  description      = "Posts one invocation to the runtime through the VPC's AgentCore endpoint"
  role             = aws_iam_role.bot.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "bot.lambda_handler"
  filename         = data.archive_file.bot.output_path
  source_code_hash = data.archive_file.bot.output_base64sha256
  timeout          = 120
  memory_size      = 256

  vpc_config {
    subnet_ids         = aws_subnet.private[*].id
    security_group_ids = [aws_security_group.bot.id]
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.bot.name
  }

  depends_on = [aws_iam_role_policy.bot]
}

output "bot_stand_in" {
  description = "The function invoke.py calls to reach the runtime from inside the VPC."
  value       = aws_lambda_function.bot.function_name
}
