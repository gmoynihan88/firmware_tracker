# The app logs one line per manufacturer per scrape at INFO, so a month of retention is
# a few MB and enough to answer "when did this vendor last change?". Logs are the only
# view into a task with no shell: ECS Exec needs a task role, and this task deliberately
# has none.
resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${local.name}"
  retention_in_days = var.log_retention_days
}
