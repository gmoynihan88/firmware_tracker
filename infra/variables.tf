variable "project" {
  description = "Name prefix and Project tag for every resource."
  type        = string
  default     = "firmware-tracker"
}

variable "environment" {
  description = "Environment name, used in resource names and tags."
  type        = string
  default     = "production"
}

variable "region" {
  description = "Region the app runs in. us-west-2 is closest to the operator; CloudFront's certificate still has to be in us-east-1."
  type        = string
  default     = "us-west-2"
}

variable "vpc_cidr" {
  description = "Address range for the VPC. /16 is more than this needs and costs nothing."
  type        = string
  default     = "10.20.0.0/16"
}

variable "image_retention_count" {
  description = "Tagged images kept in ECR before the oldest are expired."
  type        = number
  default     = 10
}

locals {
  name = "${var.project}-${var.environment}"

  tags = {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "terraform"
    Repository  = "github.com/gmoynihan88/firmware_tracker"
  }
}
