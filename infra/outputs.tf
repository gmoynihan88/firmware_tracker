output "vpc_id" {
  description = "VPC the task and the VPC Link share."
  value       = aws_vpc.main.id
}

output "public_subnet_ids" {
  description = "Subnets the ECS service runs in."
  value       = aws_subnet.public[*].id
}

output "app_security_group_id" {
  description = "Security group for the task; the VPC Link's rule attaches to this."
  value       = aws_security_group.app.id
}

output "ecr_repository_url" {
  description = "Push target for the deploy workflow."
  value       = aws_ecr_repository.app.repository_url
}
