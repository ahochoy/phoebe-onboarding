# One account cost budget. Budgets is a global API that the provider reaches
# from this us-east-2 provider (aws_budgets_budget takes no region), so no
# us-east-1 provider is needed. The topic lives in us-east-2; each env's
# budget Lambda subscribes to it from infra/app and pauses chat.

locals {
  budget_name = "phoebe-monthly"
}

# Unencrypted on purpose: Budgets cannot publish to a topic encrypted with the
# AWS managed SNS key, and alerts carry only amounts, no app data.
resource "aws_sns_topic" "budget" {
  name = "phoebe-budget"
}

resource "aws_sns_topic_policy" "budget" {
  arn = aws_sns_topic.budget.arn

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "BudgetsPublish"
      Effect    = "Allow"
      Principal = { Service = "budgets.amazonaws.com" }
      Action    = "SNS:Publish"
      Resource  = aws_sns_topic.budget.arn
      Condition = {
        StringEquals = { "aws:SourceAccount" = local.account_id }
        ArnLike      = { "aws:SourceArn" = "arn:aws:budgets::${local.account_id}:*" }
      }
    }]
  })
}

resource "aws_budgets_budget" "account" {
  name         = local.budget_name
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator       = "GREATER_THAN"
    threshold                 = 80
    threshold_type            = "PERCENTAGE"
    notification_type         = "ACTUAL"
    subscriber_sns_topic_arns = [aws_sns_topic.budget.arn]
  }

  depends_on = [aws_sns_topic_policy.budget]
}
