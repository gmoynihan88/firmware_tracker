resource "aws_ecs_cluster" "main" {
  name = local.name

  setting {
    name  = "containerInsights"
    value = "disabled" # Insights bills per metric; CloudWatch Logs answers enough here.
  }
}

# Spot is the default strategy: this is one small task that may be interrupted with two
# minutes' notice, and a restart costs a few seconds of downtime rather than any data,
# because the database is on EFS. FARGATE stays registered so a task can be moved to
# on-demand by changing the strategy, without recreating the cluster.
resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name       = aws_ecs_cluster.main.name
  capacity_providers = ["FARGATE_SPOT", "FARGATE"]

  default_capacity_provider_strategy {
    capacity_provider = var.use_spot ? "FARGATE_SPOT" : "FARGATE"
    weight            = 1
    base              = 1
  }
}

resource "aws_ecs_task_definition" "app" {
  family                   = local.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.task_execution.arn
  # No task_role_arn on purpose -- see iam.tf.

  # Stated rather than defaulted. The image is built on an Apple Silicon laptop unless
  # CI builds it, and an arm64 image against Fargate's x86_64 default fails at task
  # start with an exec format error rather than at deploy time. ARM64 Fargate is about
  # 20% cheaper and Chromium supports it, but that needs an arm64 builder in CI.
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.cpu_architecture
  }

  volume {
    name = "data"

    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.data.id
      transit_encryption = "ENABLED"

      authorization_config {
        access_point_id = aws_efs_access_point.data.id
        # IAM authorization would need a task role, which this task does not have. The
        # mount target's security group is what restricts access instead.
        iam = "DISABLED"
      }
    }
  }

  container_definitions = jsonencode([
    {
      name      = var.project
      image     = "${aws_ecr_repository.app.repository_url}:${var.image_tag}"
      essential = true

      portMappings = [{
        containerPort = var.container_port
        protocol      = "tcp"
      }]

      # The image's entrypoint runs the migrations, then this replaces its CMD. Both
      # proxy flags matter: TLS ends at CloudFront, so without --proxy-headers the app
      # sees http and every client address is API Gateway's -- which would drop the
      # session cookie's Secure flag and make the login throttle lock out everyone at
      # once.
      #
      # --forwarded-allow-ips was "*". The old comment here reasoned that nothing but
      # the VPC Link can reach this port, so forwarded headers from any peer are safe --
      # which is true about *who may connect* and misses what the flag actually does.
      # In uvicorn it also decides *which* X-Forwarded-For entry is believed: "*" sets
      # `_TrustedHosts.always_trust`, and get_trusted_client_address then returns
      # x_forwarded_for_hosts[0] -- the leftmost entry, whatever the client sent --
      # instead of walking the chain in reverse. CloudFront and API Gateway append to a
      # client-supplied header rather than replacing it, so that entry is attacker
      # controlled.
      #
      # src/auth/throttle.py keys the login limiter on exactly that value, so rotating
      # one header put every password guess in a fresh bucket and the 5-per-300s limit
      # never fired. It also wrote the spoofed string into CloudWatch, leaving the logs
      # unable to attribute the attempts.
      #
      # The trusted set has to cover every hop *downstream of* CloudFront so the reverse
      # walk stops at the viewer address CloudFront appended. The VPC CIDR on its own is
      # not enough -- the walk would stop at CloudFront's egress address and drop every
      # visitor into one shared bucket, which is the failure "*" was reaching for in the
      # first place.
      #
      # AWS republishes the CloudFront ranges without notice, so an apply may register a
      # task definition revision for that change alone. That is the price of reading the
      # list instead of pinning a copy that goes stale quietly.
      command = [
        "uvicorn", "src.main:app",
        "--host", "0.0.0.0",
        "--port", tostring(var.container_port),
        "--proxy-headers",
        "--forwarded-allow-ips",
        join(",", concat([var.vpc_cidr], data.aws_ip_ranges.cloudfront_origin_facing.cidr_blocks)),
      ]

      mountPoints = [{
        sourceVolume  = "data"
        containerPath = "/data"
        readOnly      = false
      }]

      environment = [
        { name = "DATABASE_URL", value = "sqlite+aiosqlite:////data/firmware_tracker.db" },
        # TLS ends upstream, so the scheme the app sees is never https.
        { name = "SESSION_COOKIE_SECURE", value = "true" },
        { name = "LOG_LEVEL", value = var.log_level },
        # A cached run cannot discover a new firmware version.
        { name = "SCRAPE_CACHE", value = "false" },
        { name = "LOG_FILE", value = "" },
        { name = "NOTIFY_TRANSPORT", value = var.notify_transport },
        { name = "PUBLIC_CATALOG", value = tostring(var.public_catalog) },
        { name = "SCRAPE_INTERVAL_HOURS", value = tostring(var.scrape_interval_hours) },
      ]

      secrets = [
        for key, variable in local.secrets : {
          name      = variable
          valueFrom = aws_ssm_parameter.secret[key].arn
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.app.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "ecs"
        }
      }

      # Liveness, matching the Dockerfile: /health does not touch the database, so a
      # transient database fault does not put the task into a restart loop.
      healthCheck = {
        command     = ["CMD-SHELL", "python -c \"import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:${var.container_port}/health', timeout=4).status == 200 else 1)\""]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }
    }
  ])
}
