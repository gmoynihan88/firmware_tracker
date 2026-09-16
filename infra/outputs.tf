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

output "cluster_name" {
  description = "ECS cluster, for the deploy workflow's update-service call."
  value       = aws_ecs_cluster.main.name
}

output "service_name" {
  description = "ECS service, for the deploy workflow's update-service call."
  value       = aws_ecs_service.app.name
}

output "task_definition_family" {
  description = "Task definition family the deploy workflow registers revisions against."
  value       = aws_ecs_task_definition.app.family
}

output "cloud_map_service_arn" {
  description = "What the API Gateway VPC Link integration points at."
  value       = aws_service_discovery_service.app.arn
}

output "efs_file_system_id" {
  description = "Where the database lives; the backup script reads it through the same access point."
  value       = aws_efs_file_system.data.id
}

output "log_group" {
  description = "CloudWatch log group carrying the task's output."
  value       = aws_cloudwatch_log_group.app.name
}

output "deploy_role_arn" {
  description = "Set as the AWS_DEPLOY_ROLE_ARN variable on the repository's production environment."
  value       = aws_iam_role.deploy.arn
}

output "secret_parameter_names" {
  description = "Set each of these with: aws ssm put-parameter --overwrite --type SecureString --name <name> --value <secret>"
  value       = [for parameter in aws_ssm_parameter.secret : parameter.name]
}
