# GitHub Actions authenticates by OIDC, so there is no AWS key in the repository, in
# GitHub's secrets, or on anyone's laptop. The workflow presents a short-lived token
# describing which repository, workflow and environment asked, and AWS trades it for
# credentials that expire in an hour.

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]

  # thumbprint_list is deliberately not set. IAM verifies GitHub's certificate against
  # its own trust store for this provider, so the list is vestigial -- it used to need
  # updating whenever GitHub rotated an intermediate, which broke deploys for anyone who
  # had pinned one. AWS populates a thumbprint anyway, so setting it to [] here made
  # every plan propose deleting it, and that in turn left the role's trust policy
  # unresolvable at plan time.
}

# **The trust is pinned to one repository and one environment.** `repo:owner/name:*`
# would be assumable by any branch, any pull request and any fork's workflow run -- the
# exact finding from the CI/CD audit at work. With `environment:production`, only a job
# that declares `environment: production` can assume it, and that environment can carry
# reviewers or branch restrictions later.
data "aws_iam_policy_document" "deploy_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:environment:${var.environment}"]
    }
  }
}

resource "aws_iam_role" "deploy" {
  name               = "${local.name}-deploy"
  description        = "Assumed by GitHub Actions to push an image and update the service."
  assume_role_policy = data.aws_iam_policy_document.deploy_assume.json
}

# Push an image, register a task definition revision, point the service at it. Nothing
# else: this role cannot read the secrets, touch EFS, or change the infrastructure.
# Terraform still runs from a workstation with a human's credentials.
data "aws_iam_policy_document" "deploy" {
  statement {
    sid       = "EcrAuth"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"] # The token call is account-wide by definition.
  }

  statement {
    sid    = "EcrPush"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:PutImage",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [aws_ecr_repository.app.arn]
  }

  statement {
    sid    = "RegisterTaskDefinition"
    effect = "Allow"
    actions = [
      "ecs:DescribeTaskDefinition",
      "ecs:RegisterTaskDefinition",
    ]
    # Neither action supports resource-level permissions; the PassRole statement below
    # is what stops this role registering a task definition that runs as something else.
    resources = ["*"]
  }

  statement {
    sid    = "UpdateService"
    effect = "Allow"
    actions = [
      "ecs:UpdateService",
      "ecs:DescribeServices",
    ]
    resources = [aws_ecs_service.app.id]
  }

  # A task definition names the role its tasks run with, so registering one is only as
  # safe as the roles this role may pass. It may pass exactly one -- the execution role
  # -- and only to ECS.
  statement {
    sid       = "PassExecutionRole"
    effect    = "Allow"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.task_execution.arn]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "deploy" {
  name   = "${local.name}-deploy"
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy.json
}
