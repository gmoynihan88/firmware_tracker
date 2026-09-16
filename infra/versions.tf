terraform {
  # 1.11 is where S3 native state locking became the supported way to lock, which is
  # what lets this skip the DynamoDB table the older pattern needs -- one less
  # resource to create, pay for and explain.
  required_version = ">= 1.11"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # Partial configuration: the bucket name is account-specific, so it lives in
  # infra/backend.hcl (gitignored) rather than in the repository.
  #
  #   terraform init -backend-config=backend.hcl
  backend "s3" {
    key          = "firmware-tracker/production.tfstate"
    encrypt      = true
    use_lockfile = true
  }
}
