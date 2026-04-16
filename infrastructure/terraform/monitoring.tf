# ───── CLOUDWATCH DASHBOARD ─────
resource "aws_cloudwatch_dashboard" "alpha_forge" {
  dashboard_name = "AlphaForge-${var.environment}"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        width  = 12
        height = 6
        properties = {
          title   = "Lambda Invocations"
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", "alpha-forge-analyzer-${var.environment}"],
            ["AWS/Lambda", "Invocations", "FunctionName", "alpha-forge-api-${var.environment}"]
          ]
          period = 300
          stat   = "Sum"
        }
      },
      {
        type   = "metric"
        width  = 12
        height = 6
        properties = {
          title   = "Lambda Errors + Duration"
          metrics = [
            ["AWS/Lambda", "Errors", "FunctionName", "alpha-forge-analyzer-${var.environment}"],
            ["AWS/Lambda", "Duration", "FunctionName", "alpha-forge-analyzer-${var.environment}"]
          ]
          period = 300
        }
      },
      {
        type   = "metric"
        width  = 8
        height = 6
        properties = {
          title   = "DynamoDB Read/Write"
          metrics = [
            ["AWS/DynamoDB", "ConsumedReadCapacityUnits", "TableName", "alpha-signals-${var.environment}"],
            ["AWS/DynamoDB", "ConsumedWriteCapacityUnits", "TableName", "alpha-signals-${var.environment}"]
          ]
          period = 3600
          stat   = "Sum"
        }
      }
    ]
  })
}

# ───── CLOUDWATCH ALARM — Lambda errors ─────
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "${local.name_prefix}-lambda-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 3
  alarm_description   = "AlphaForge analyzer lambda error rate too high"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = "alpha-forge-analyzer-${var.environment}"
  }
}
