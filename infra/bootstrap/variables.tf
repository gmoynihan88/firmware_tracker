variable "state_bucket_name" {
  description = "Globally unique S3 bucket for Terraform state, e.g. firmware-tracker-tfstate-<something random>."
  type        = string
}

variable "region" {
  description = "Region for the state bucket. Keep it with the rest of the stack."
  type        = string
  default     = "us-west-2"
}

variable "project" {
  description = "Tag applied to everything this configuration creates."
  type        = string
  default     = "firmware-tracker"
}
