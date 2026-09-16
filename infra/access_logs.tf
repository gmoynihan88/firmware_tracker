# CloudFront access logs, delivered the way that does not need bucket ACLs.
#
# The familiar way to turn these on is `logging_config` on the distribution, which
# writes to S3 as the awslogsdelivery canonical user and therefore needs ACLs enabled on
# the bucket. Buckets created now have ACLs disabled by default, and re-enabling them to
# collect logs trades a real security property for a nice-to-have. The delivery
# resources below are the supported replacement: the service writes as itself, allowed
# by the bucket policy, and the bucket keeps object ownership enforced.
#
# At roughly 300 requests a day this is a few megabytes a month. The lifecycle rule is
# what keeps it that way: logs nobody deletes cost nothing right up until they do.

resource "aws_s3_bucket" "access_logs" {
  # Bucket names are globally unique. The account id supplies that without another
  # account-specific value to keep in a gitignored file, which is what the state bucket
  # needs only because it is applied before this stack exists to ask.
  bucket = "${local.name}-access-logs-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# SSE-S3, for the reason the state bucket gives: encrypted at rest without a customer
# managed key to pay for monthly and get the key policy wrong on.
resource "aws_s3_bucket_server_side_encryption_configuration" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

# Two years, which is a retention decision rather than a cost one. At roughly 300
# requests a day that is around 200MB by the time the oldest objects start expiring --
# pennies a month, and the traffic would have to grow a hundredfold before the bill was
# worth a thought.
#
# What argues for a shorter window is that access logs record visitor IP addresses, and
# thirty to ninety days is the usual retention for that reason rather than for storage.
# Two years is deliberate here: this is a personal site, and the question worth asking of
# it -- did anyone actually visit after the link was shared months ago -- is one a short
# window cannot answer. Shorten it if the site ever carries someone else's visitors.
resource "aws_s3_bucket_lifecycle_configuration" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id

  rule {
    id     = "expire-access-logs"
    status = "Enabled"

    filter {}

    expiration {
      days = var.access_log_retention_days
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

resource "aws_s3_bucket_policy" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id
  policy = data.aws_iam_policy_document.access_logs.json
}

data "aws_iam_policy_document" "access_logs" {
  # Both conditions matter. Without them this bucket would accept writes the delivery
  # service was asked to make on some other account's behalf, which is the confused
  # deputy the SourceAccount and SourceArn keys exist for.
  statement {
    sid    = "AWSLogDeliveryWrite"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["delivery.logs.amazonaws.com"]
    }

    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.access_logs.arn}/*"]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      # us-east-1 because that is where the delivery source below has to live.
      values = ["arn:aws:logs:us-east-1:${data.aws_caller_identity.current.account_id}:delivery-source:*"]
    }
  }

  statement {
    sid    = "AWSLogDeliveryAclCheck"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["delivery.logs.amazonaws.com"]
    }

    actions   = ["s3:GetBucketAcl"]
    resources = [aws_s3_bucket.access_logs.arn]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }

  # The same rule the state bucket carries: a bucket should not accept a plaintext
  # request at all.
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]

    resources = [
      aws_s3_bucket.access_logs.arn,
      "${aws_s3_bucket.access_logs.arn}/*",
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

# CloudFront is global and its logs originate in us-east-1, so the delivery source has
# to be created there -- the same reason the certificate will be, and why providers.tf
# already carries the alias. The bucket itself stays in var.region with everything else.
resource "aws_cloudwatch_log_delivery_source" "cloudfront" {
  provider = aws.us_east_1

  name         = "${local.name}-cloudfront"
  log_type     = "ACCESS_LOGS"
  resource_arn = aws_cloudfront_distribution.main.arn
}

resource "aws_cloudwatch_log_delivery_destination" "access_logs" {
  provider = aws.us_east_1

  name = "${local.name}-access-logs"

  # JSON rather than parquet: these get read by eye and by grep, and parquet only pays
  # for itself with a table definition in front of it that nothing here has.
  output_format = "json"

  delivery_destination_configuration {
    destination_resource_arn = aws_s3_bucket.access_logs.arn
  }
}

resource "aws_cloudwatch_log_delivery" "cloudfront_access_logs" {
  provider = aws.us_east_1

  delivery_source_name     = aws_cloudwatch_log_delivery_source.cloudfront.name
  delivery_destination_arn = aws_cloudwatch_log_delivery_destination.access_logs.arn

  # record_fields is deliberately unset. The default is every field CloudFront offers,
  # and at this volume naming a subset would save megabytes a year while risking a
  # field name that does not exist -- which fails at apply, not at review.
}
