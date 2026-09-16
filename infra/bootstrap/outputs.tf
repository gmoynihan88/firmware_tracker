output "state_bucket" {
  description = "Put this in infra/backend.hcl as `bucket`."
  value       = aws_s3_bucket.state.id
}

output "region" {
  description = "Put this in infra/backend.hcl as `region`."
  value       = var.region
}
