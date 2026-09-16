resource "aws_ecr_repository" "app" {
  name = var.project

  # A tag that can be repointed makes "which image is running?" unanswerable, and the
  # deploy workflow pushes one tag per commit SHA, so nothing needs to move a tag.
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

# The image carries Chromium, so it is large; keeping every build would cost more in
# storage than the rest of this stack. Untagged layers go quickly, tagged images after
# the newest few, which still leaves several deploys to roll back through.
resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after 7 days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep the newest ${var.image_retention_count} tagged images"
        selection = {
          tagStatus      = "tagged"
          tagPatternList = ["*"]
          countType      = "imageCountMoreThan"
          countNumber    = var.image_retention_count
        }
        action = { type = "expire" }
      },
    ]
  })
}
