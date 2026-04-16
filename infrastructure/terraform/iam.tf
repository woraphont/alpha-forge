# ───── IAM POLICY — Lambda SSM access ─────
resource "aws_iam_policy" "lambda_ssm" {
  name        = "${local.name_prefix}-lambda-ssm"
  description = "Allow Lambda to read AlphaForge secrets from SSM"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"]
      Resource = "arn:aws:ssm:${var.aws_region}:*:parameter/alpha-forge/*"
    }]
  })
}

# ───── AWS BUDGET ALERT ─────
resource "aws_budgets_budget" "monthly" {
  name              = "${local.name_prefix}-monthly"
  budget_type       = "COST"
  limit_amount      = tostring(var.monthly_budget_usd)
  limit_unit        = "USD"
  time_unit         = "MONTHLY"

  # Alert at 80% of budget (forecast)
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = var.budget_alert_email != "" ? [var.budget_alert_email] : []
  }

  # Alert when actual exceeds $3
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 3
    threshold_type             = "ABSOLUTE_VALUE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = var.budget_alert_email != "" ? [var.budget_alert_email] : []
  }
}
