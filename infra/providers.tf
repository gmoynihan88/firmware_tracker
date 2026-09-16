provider "aws" {
  region = var.region

  default_tags {
    tags = local.tags
  }
}

# CloudFront reads its certificate from us-east-1 and nowhere else, so the edge
# resources need a provider pinned there even though the app runs in var.region.
# Declared now so adding the certificate later is not a provider change.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"

  default_tags {
    tags = local.tags
  }
}
