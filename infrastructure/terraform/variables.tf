variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment (dev or prod)"
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "environment must be dev or prod"
  }
}

variable "project_name" {
  description = "Project name prefix for all resources"
  type        = string
  default     = "alpha-forge"
}

variable "budget_alert_email" {
  description = "Email for AWS Budget alert notifications"
  type        = string
  default     = ""
}

variable "monthly_budget_usd" {
  description = "Monthly AWS budget limit in USD"
  type        = number
  default     = 5
}
