# The Langfuse VM's network: one VPC, one subnet, and two security groups that name each other. The VM's
# group accepts inbound traffic from the EC2 Instance Connect endpoint's group alone, on 22 for SSH and on
# 3000 for Langfuse's web port, so no rule opens a port to the internet (O-D4, amended). The subnet routes
# to an internet gateway and the VM gets a public address for one reason: Docker pulls Langfuse's images
# from their registries. A security group is stateful, so an outbound pull's answers come back while no
# inbound rule exists; the alternative, a NAT gateway, bills by the hour and is the classic leftover.

locals {
  cidr = "10.46.0.0/24"
}

resource "aws_vpc" "lab" {
  cidr_block           = local.cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = var.name }

  depends_on = [aws_budgets_budget.session]
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.lab.id
  cidr_block              = local.cidr
  availability_zone_id    = var.az_id
  map_public_ip_on_launch = true
  tags                    = { Name = "${var.name}-${var.az_id}" }
}

resource "aws_internet_gateway" "lab" {
  vpc_id = aws_vpc.lab.id
  tags   = { Name = var.name }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.lab.id
  tags   = { Name = "${var.name}-public" }

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.lab.id
  }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# The groups. Terraform removes the default allow-all egress rule from a group it creates, so each group
# has exactly the rules below.
resource "aws_security_group" "vm" {
  name        = "${var.name}-langfuse-vm"
  description = "The Langfuse VM: inbound from the Instance Connect endpoint alone"
  vpc_id      = aws_vpc.lab.id
  tags        = { Name = "${var.name}-langfuse-vm" }
}

resource "aws_security_group" "endpoint" {
  name        = "${var.name}-instance-connect"
  description = "The EC2 Instance Connect endpoint: outbound to the VM alone"
  vpc_id      = aws_vpc.lab.id
  tags        = { Name = "${var.name}-instance-connect" }
}

resource "aws_vpc_security_group_ingress_rule" "vm_ssh" {
  security_group_id            = aws_security_group.vm.id
  referenced_security_group_id = aws_security_group.endpoint.id
  ip_protocol                  = "tcp"
  from_port                    = 22
  to_port                      = 22
  description                  = "SSH from the Instance Connect endpoint"
}

resource "aws_vpc_security_group_ingress_rule" "vm_langfuse" {
  security_group_id            = aws_security_group.vm.id
  referenced_security_group_id = aws_security_group.endpoint.id
  ip_protocol                  = "tcp"
  from_port                    = 3000
  to_port                      = 3000
  description                  = "Langfuse web port 3000 from the Instance Connect endpoint, for the tunnel"
}

resource "aws_vpc_security_group_egress_rule" "vm_out" {
  security_group_id = aws_security_group.vm.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "Outbound only: the image pulls and the package installs"
}

resource "aws_vpc_security_group_egress_rule" "endpoint_ssh" {
  security_group_id            = aws_security_group.endpoint.id
  referenced_security_group_id = aws_security_group.vm.id
  ip_protocol                  = "tcp"
  from_port                    = 22
  to_port                      = 22
  description                  = "To the VM on 22 (SSH)"
}

resource "aws_vpc_security_group_egress_rule" "endpoint_langfuse" {
  security_group_id            = aws_security_group.endpoint.id
  referenced_security_group_id = aws_security_group.vm.id
  ip_protocol                  = "tcp"
  from_port                    = 3000
  to_port                      = 3000
  description                  = "To the VM on 3000 (Langfuse)"
}

# The endpoint costs nothing and needs no public address (fact sheet 8.6). With the client IP not
# preserved, the VM sees the endpoint's own address, which its group allows.
resource "aws_ec2_instance_connect_endpoint" "lab" {
  subnet_id          = aws_subnet.public.id
  security_group_ids = [aws_security_group.endpoint.id]
  preserve_client_ip = false
  tags               = { Name = var.name }
}
