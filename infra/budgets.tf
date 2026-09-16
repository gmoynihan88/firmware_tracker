# Cost alarms.
#
# Three, because they catch different failures. A monthly budget catches drift -- the
# realistic failure here is not a sudden $50 but $9 quietly becoming $25 while nobody
# looks. A daily budget catches a spike, and is set near the run rate rather than far
# above it, because a threshold at five times normal only ever fires for a disaster and
# lets a steady doubling through. Anomaly detection catches the shape of a change that no
# fixed number would describe.
#
# Both budgets read Cost Explorer, which refreshes about three times a day and lags 8-24
# hours, so the monthly one also alerts on *forecast*: that fires hours earlier than
# actual spend crossing the line. Daily budgets have no forecast -- there is not enough
# history in a day -- so the daily one is actual-only and inherently the slower signal.
#
# The first two budgets on an account are free; after that they are $0.02 a day each.

variable "alert_email" {
  description = "Where cost alerts go. Account-specific, so it belongs in terraform.tfvars (gitignored), not in this repository."
  type        = string
}

variable "monthly_budget_usd" {
  description = "Monthly ceiling. Steady state is about $9, so this is roughly 1.5x: high enough not to nag, low enough to notice drift."
  type        = number
  default     = 15
}

variable "daily_budget_usd" {
  description = "Daily ceiling. The run rate is about $0.30, so this is roughly 3x -- a deploy day costs more than a quiet one and should not page anyone."
  type        = number
  default     = 1
}

variable "anomaly_monitor_arn" {
  description = "ARN of the existing AWS-managed cost anomaly monitor. Empty means no anomaly subscription is created. Account-specific: keep it in terraform.tfvars."
  type        = string
  default     = ""
}

variable "anomaly_alert_usd" {
  description = "Only report anomalies whose total impact is at least this many dollars, so a few cents of noise stays quiet."
  type        = number
  default     = 5
}

resource "aws_budgets_budget" "monthly" {
  name         = "${local.name}-monthly"
  budget_type  = "COST"
  limit_amount = var.monthly_budget_usd
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  # 80% of actual: early enough to act before the month closes.
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }

  # Forecast to exceed the whole budget. This is the one that arrives in time to matter.
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}

resource "aws_budgets_budget" "daily" {
  name         = "${local.name}-daily"
  budget_type  = "COST"
  limit_amount = var.daily_budget_usd
  limit_unit   = "USD"
  time_unit    = "DAILY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }
}

# The account already has an AWS-managed monitor watching every service, and a default
# subscription on the same address -- but that one only fires at $100 **and** 40% impact
# together, which on a $9/month account is never. This subscribes to the same monitor at
# $5 absolute, a threshold this account can actually reach. A daily digest rather than
# immediate: immediate delivery requires SNS, and a cost anomaly is never a page-me-now
# event.
resource "aws_ce_anomaly_subscription" "alerts" {
  count = var.anomaly_monitor_arn == "" ? 0 : 1

  name             = "${local.name}-anomalies"
  frequency        = "DAILY"
  monitor_arn_list = [var.anomaly_monitor_arn]

  subscriber {
    type    = "EMAIL"
    address = var.alert_email
  }

  threshold_expression {
    dimension {
      key           = "ANOMALY_TOTAL_IMPACT_ABSOLUTE"
      match_options = ["GREATER_THAN_OR_EQUAL"]
      values        = [tostring(var.anomaly_alert_usd)]
    }
  }
}
