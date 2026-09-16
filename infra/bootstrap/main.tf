# The state backend itself, which cannot live in the state it stores. Applied once,
# by hand, with local state -- the chicken-and-egg every Terraform setup has.
#
#   cd infra/bootstrap
#   terraform init && terraform apply -var state_bucket_name=<globally-unique-name>
#
# Its own terraform.tfstate stays on the machine that ran it and is gitignored. Losing
# it costs nothing: the bucket and its contents survive, and a second run can import.

terraform {
  required_version = ">= 1.11"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = var.project
      ManagedBy = "terraform"
      Component = "tfstate"
    }
  }
}

resource "aws_s3_bucket" "state" {
  bucket = var.state_bucket_name

  # Deleting this bucket destroys every version of the state for every environment.
  lifecycle {
    prevent_destroy = true
  }
}

# State is the one file where "recover the version from before that apply" is the
# whole recovery plan, so versions are kept.
resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id

  versioning_configuration {
    status = "Enabled"
  }
}

# SSE-S3 rather than KMS: state holds secrets, so it is encrypted, but a customer
# managed key costs $1/month plus per-request charges and adds a key policy to get
# wrong. Swap to KMS if compliance ever asks for it.
resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket = aws_s3_bucket.state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Old versions are worth keeping long enough to recover from a bad apply, not
# forever; every apply writes another copy of the whole file.
resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    id     = "expire-noncurrent-state"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 90
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# TLS in transit, because a bucket holding state should not accept a plaintext
# request at all.
resource "aws_s3_bucket_policy" "state" {
  bucket = aws_s3_bucket.state.id
  policy = data.aws_iam_policy_document.state.json
}

data "aws_iam_policy_document" "state" {
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]

    resources = [
      aws_s3_bucket.state.arn,
      "${aws_s3_bucket.state.arn}/*",
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}
