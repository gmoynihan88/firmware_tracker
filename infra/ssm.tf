# Secrets live in Parameter Store and are injected by the execution role at task start,
# so they are never in the task definition, the image or this repository.
#
# **Terraform creates each parameter with a placeholder and then ignores its value.**
# Putting real secrets in a variable would write them into state, which is the thing
# state is worst at holding. Set them once, by hand, and Terraform leaves them alone:
#
#   aws ssm put-parameter --overwrite --type SecureString \
#     --name /firmware-tracker/production/secret_key --value "$(python -m src.auth.hash_password ...)"
#
# `python -m src.auth.hash_password` prints both AUTH_PASSWORD_HASH and SECRET_KEY.

locals {
  parameter_prefix = "/${var.project}/${var.environment}"

  # name -> the environment variable the container reads it as.
  secrets = {
    secret_key         = "SECRET_KEY"
    auth_password_hash = "AUTH_PASSWORD_HASH"
    ntfy_topic         = "NTFY_TOPIC"
    anthropic_api_key  = "ANTHROPIC_API_KEY"
  }
}

resource "aws_ssm_parameter" "secret" {
  for_each = local.secrets

  name  = "${local.parameter_prefix}/${each.key}"
  type  = "SecureString"
  value = "placeholder-set-me-with-put-parameter"

  description = "Read as ${each.value} by the Firmware Tracker task. Set with aws ssm put-parameter --overwrite."

  lifecycle {
    ignore_changes = [value]
  }
}
