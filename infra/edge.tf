# API Gateway is the origin CloudFront needs and the load balancer this stack does not
# have. A Fargate task's IP changes on every replacement, and CloudFront cannot point at
# an ECS task; an HTTP API with a VPC Link resolves the task through Cloud Map instead,
# for about $1 per million requests against an ALB's $16 a month standing charge.

resource "aws_security_group" "vpc_link" {
  name        = "${local.name}-vpc-link"
  description = "API Gateway VPC Link: reaches the task, nothing else."
  vpc_id      = aws_vpc.main.id

  tags = {
    Name = "${local.name}-vpc-link"
  }
}

resource "aws_vpc_security_group_egress_rule" "vpc_link_to_app" {
  security_group_id            = aws_security_group.vpc_link.id
  description                  = "Forward requests to the task"
  referenced_security_group_id = aws_security_group.app.id
  from_port                    = var.container_port
  to_port                      = var.container_port
  ip_protocol                  = "tcp"
}

# The task's only inbound rule, and the reason its security group was created empty:
# nothing but the VPC Link can reach the app, even though the task has a public IP.
resource "aws_vpc_security_group_ingress_rule" "app_from_vpc_link" {
  security_group_id            = aws_security_group.app.id
  description                  = "API Gateway VPC Link"
  referenced_security_group_id = aws_security_group.vpc_link.id
  from_port                    = var.container_port
  to_port                      = var.container_port
  ip_protocol                  = "tcp"
}

resource "aws_apigatewayv2_vpc_link" "main" {
  name               = local.name
  security_group_ids = [aws_security_group.vpc_link.id]
  subnet_ids         = aws_subnet.public[*].id
}

resource "aws_apigatewayv2_api" "main" {
  name          = local.name
  description   = "Origin for the Firmware Tracker CloudFront distribution"
  protocol_type = "HTTP"
}

# The integration resolves the task through Cloud Map: the A record gives the address and
# the SRV record the port, which is why the service registers both.
resource "aws_apigatewayv2_integration" "app" {
  api_id             = aws_apigatewayv2_api.main.id
  integration_type   = "HTTP_PROXY"
  integration_method = "ANY"
  integration_uri    = aws_service_discovery_service.app.arn
  connection_type    = "VPC_LINK"
  connection_id      = aws_apigatewayv2_vpc_link.main.id

  payload_format_version = "1.0"
  timeout_milliseconds   = 30000
}

# One route for everything. The app does its own routing and its own authentication, and
# a per-path routing table here would be a second place to keep in step with it.
resource "aws_apigatewayv2_route" "default" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.app.id}"
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/apigateway/${local.name}"
  retention_in_days = var.log_retention_days
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = "$default"
  auto_deploy = true

  # The app's own logs go to its task's log group; these say what reached the edge at
  # all, which is the half a request that never arrives cannot tell you.
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api.arn

    format = jsonencode({
      requestId       = "$context.requestId"
      ip              = "$context.identity.sourceIp"
      requestTime     = "$context.requestTime"
      httpMethod      = "$context.httpMethod"
      routeKey        = "$context.routeKey"
      path            = "$context.path"
      status          = "$context.status"
      responseLength  = "$context.responseLength"
      integrationErr  = "$context.integrationErrorMessage"
      responseLatency = "$context.responseLatency"
    })
  }

  default_route_settings {
    # A cheap ceiling: this is a single-user tracker behind a login, and API Gateway
    # bills per request. Bursts above this get 429 from the edge rather than reaching
    # a 0.5 vCPU task.
    throttling_burst_limit = 50
    throttling_rate_limit  = 20
  }
}
