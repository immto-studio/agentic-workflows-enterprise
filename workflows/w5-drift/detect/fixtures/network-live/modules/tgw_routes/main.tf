# module.tgw_routes of the network-live fixture: the Transit Gateway route to the mainframe range.

variable "transit_gateway_attachment_id" {
  type = string
}

resource "aws_ec2_transit_gateway_route" "mainframe" {
  destination_cidr_block         = "10.250.0.0/16"
  transit_gateway_attachment_id  = var.transit_gateway_attachment_id
  transit_gateway_route_table_id = "tgw-rtb-0a1b2c3d4e5f60071"
}
