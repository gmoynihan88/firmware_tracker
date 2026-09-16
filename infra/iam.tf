# The execution role is the one ECS itself uses: pull the image, read the secrets, write
# the logs. It is assumed by the ECS agent before the container starts.
#
# **There is deliberately no task role.** A task role is served over the container
# credential endpoint at 169.254.170.2, which no security group can filter. This app
# fetches arbitrary vendor URLs, and Chromium resolves DNS independently of the app's own
# egress guard (src/scrapers/netguard.py), so a DNS-rebinding host has a small window in
# which a rendered page could reach that endpoint -- and scraped text is displayed in the
# UI. With no task role there is nothing at that address to steal. Nothing the app does at
# runtime calls an AWS API: EFS is mounted by the agent, and the secrets arrive as
# environment variables.

data "aws_iam_policy_document" "task_execution_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }

    # Scoped so the role can only be assumed on behalf of this account's tasks.
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

data "aws_caller_identity" "current" {}

resource "aws_iam_role" "task_execution" {
  name               = "${local.name}-task-execution"
  assume_role_policy = data.aws_iam_policy_document.task_execution_assume.json
}

# Image pull and log writing.
resource "aws_iam_role_policy_attachment" "task_execution" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Secret injection, narrowed to this environment's parameters rather than the account's.
data "aws_iam_policy_document" "task_secrets" {
  statement {
    effect    = "Allow"
    actions   = ["ssm:GetParameters"]
    resources = [for parameter in aws_ssm_parameter.secret : parameter.arn]
  }
}

resource "aws_iam_role_policy" "task_secrets" {
  name   = "${local.name}-secrets"
  role   = aws_iam_role.task_execution.id
  policy = data.aws_iam_policy_document.task_secrets.json
}
