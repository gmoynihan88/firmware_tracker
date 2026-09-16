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

variable "image_tag" {
  description = "Image tag the service runs. The deploy workflow pushes one tag per commit SHA and updates the service; this is only the starting point."
  type        = string
  default     = "latest"
}

variable "container_port" {
  description = "Port uvicorn listens on inside the task."
  type        = number
  default     = 8000
}

variable "task_cpu" {
  description = "Fargate CPU units. 512 is 0.5 vCPU, which Chromium needs to render pages in reasonable time."
  type        = number
  default     = 512
}

variable "task_memory" {
  description = "Fargate memory in MB. 1024 leaves room for Chromium; 512 risks the task being killed mid-render."
  type        = number
  default     = 1024
}

variable "github_repository" {
  description = "owner/name of the repository allowed to assume the deploy role. Half of the OIDC trust condition."
  type        = string
  default     = "gmoynihan88/firmware_tracker"
}

variable "cpu_architecture" {
  description = "X86_64 or ARM64. ARM64 is cheaper but needs an arm64 image; GitHub's default runners build x86_64."
  type        = string
  default     = "X86_64"
}

variable "use_spot" {
  description = "Run on Fargate Spot, at roughly a third of the price. An interruption gives two minutes' notice and costs a restart, not data: the database is on EFS."
  type        = bool
  default     = true
}

variable "desired_count" {
  description = "Tasks to run. Must stay 1: SQLite on EFS allows one writer and the scheduler runs in-process."
  type        = number
  default     = 1

  validation {
    condition     = var.desired_count == 1
    error_message = "desired_count must be 1: a second task would corrupt the database and double every scrape."
  }
}

variable "log_retention_days" {
  description = "CloudWatch log retention."
  type        = number
  default     = 30
}

variable "log_level" {
  description = "LOG_LEVEL for the app. INFO is one line per manufacturer per scrape."
  type        = string
  default     = "INFO"
}

variable "notify_transport" {
  description = "NOTIFY_TRANSPORT for the app: none, or ntfy once the topic parameter is set."
  type        = string
  default     = "none"
}

variable "scrape_interval_hours" {
  description = "How often the in-process scheduler scrapes every manufacturer."
  type        = number
  default     = 24
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
