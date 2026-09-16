# A VPC with public subnets and no NAT gateway.
#
# The usual shape puts the task in private subnets behind a NAT gateway, and that
# gateway is $32/month before a byte moves -- three times the budget for this whole
# stack. The task instead runs in a public subnet with a public IP, which is how it
# reaches the vendors it scrapes, and nothing reaches it: its security group allows
# no inbound traffic except from the VPC Link that API Gateway will own, added with
# the edge resources.
#
# Two subnets because ECS wants more than one availability zone, not because the
# service runs in both: SQLite on EFS allows exactly one writer, so the desired count
# stays at 1.

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = local.name
  }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = local.name
  }
}

resource "aws_subnet" "public" {
  count = 2

  vpc_id                  = aws_vpc.main.id
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index)
  map_public_ip_on_launch = true

  tags = {
    Name = "${local.name}-public-${data.aws_availability_zones.available.names[count.index]}"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name = "${local.name}-public"
  }
}

resource "aws_route_table_association" "public" {
  count = length(aws_subnet.public)

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# The task's security group. No ingress rule at all yet -- the only thing that should
# ever reach port 8000 is the VPC Link, and its security group does not exist until
# the edge resources land. An empty ingress is the correct state in between, not an
# oversight: the task has a public IP, and this is what keeps it unreachable.
resource "aws_security_group" "app" {
  name        = "${local.name}-app"
  description = "Firmware Tracker task: egress to vendors, ingress only from the VPC Link."
  vpc_id      = aws_vpc.main.id

  tags = {
    Name = "${local.name}-app"
  }
}

# Scraping is the app's whole purpose, so it needs to reach arbitrary vendor hosts on
# 443 and 80. Outbound is unrestricted in destination but not in protocol; the app
# refuses non-public addresses itself in src/scrapers/netguard.py.
resource "aws_vpc_security_group_egress_rule" "app_https" {
  security_group_id = aws_security_group.app.id
  description       = "Vendor sites, ECR, S3, Secrets and logs"
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "app_http" {
  security_group_id = aws_security_group.app.id
  description       = "Vendor sites that still redirect from http"
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 80
  to_port           = 80
  ip_protocol       = "tcp"
}
