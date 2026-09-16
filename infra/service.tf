# Cloud Map gives the task a stable name to be found by. API Gateway's VPC Link
# integrates with a Cloud Map service, which is what replaces the load balancer this
# stack deliberately does not have: the task's IP changes on every replacement, and
# nothing else would follow it.
resource "aws_service_discovery_private_dns_namespace" "internal" {
  name        = "${var.project}.internal"
  description = "Private namespace for the Firmware Tracker task"
  vpc         = aws_vpc.main.id
}

resource "aws_service_discovery_service" "app" {
  name = "app"

  dns_config {
    namespace_id   = aws_service_discovery_private_dns_namespace.internal.id
    routing_policy = "MULTIVALUE"

    # A for the address and SRV for the port: the VPC Link integration reads the port
    # from SRV rather than being told it.
    dns_records {
      type = "A"
      ttl  = 15
    }

    dns_records {
      type = "SRV"
      ttl  = 15
    }
  }
}

resource "aws_ecs_service" "app" {
  name            = local.name
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = var.desired_count

  capacity_provider_strategy {
    capacity_provider = var.use_spot ? "FARGATE_SPOT" : "FARGATE"
    weight            = 1
    base              = 1
  }

  network_configuration {
    subnets = aws_subnet.public[*].id
    # No NAT gateway, so the task needs a public IP to reach the vendors it scrapes.
    # Its security group is what keeps the internet from reaching back.
    assign_public_ip = true
    security_groups  = [aws_security_group.app.id]
  }

  service_registries {
    registry_arn   = aws_service_discovery_service.app.arn
    container_name = var.project
    container_port = var.container_port
  }

  # One writer, always. SQLite on EFS cannot have two, and the scheduler runs in the
  # same process, so an overlapping deployment would double every scrape as well as
  # risk the database. This stops the old task before starting the new one, which costs
  # a few seconds of downtime per deploy.
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100

  # The deploy workflow registers a new task definition revision and updates the
  # service, so Terraform should not fight it over which revision is current.
  lifecycle {
    ignore_changes = [task_definition]
  }

  depends_on = [aws_efs_mount_target.data]
}
