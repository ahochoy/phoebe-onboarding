# One account cost budget, two topics. Each env's budget Lambda
# subscribes only to its own topic from infra/app, so a staging deploy can
# never unsubscribe or redirect production's kill switch. A Budgets
# notification takes only one SNS subscriber, so there are two identical
# account-wide budgets, `phoebe-monthly-<env>`, each notifying its own topic.
#
# Budgets is a global API that the provider reaches from this us-east-2
# provider (aws_budgets_budget takes no region), so no us-east-1 provider is
# needed. Both topics live in us-east-2.

locals {
  budget_topic_arns = {
    for env in local.envs : env => "arn:aws:sns:${local.region}:${local.account_id}:phoebe-budget-${env}"
  }
}

# Unencrypted on purpose: Budgets cannot publish to a topic encrypted with the
# AWS managed SNS key, and alerts carry only amounts, no app data.
resource "aws_sns_topic" "budget" {
  for_each = toset(local.envs)

  name = "phoebe-budget-${each.key}"
}

resource "aws_sns_topic_policy" "budget" {
  for_each = toset(local.envs)

  arn = aws_sns_topic.budget[each.key].arn

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "BudgetsPublish"
      Effect    = "Allow"
      Principal = { Service = "budgets.amazonaws.com" }
      Action    = "SNS:Publish"
      Resource  = aws_sns_topic.budget[each.key].arn
      Condition = {
        StringEquals = { "aws:SourceAccount" = local.account_id }
        ArnLike      = { "aws:SourceArn" = "arn:aws:budgets::${local.account_id}:*" }
      }
    }]
  })
}

resource "aws_budgets_budget" "account" {
  for_each = toset(local.envs)

  name         = "phoebe-monthly-${each.key}"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator       = "GREATER_THAN"
    threshold                 = 70
    threshold_type            = "PERCENTAGE"
    notification_type         = "ACTUAL"
    subscriber_sns_topic_arns = [aws_sns_topic.budget[each.key].arn]
    # Both budgets trip together; one email is enough.
    subscriber_email_addresses = each.key == "production" && var.alert_email != null ? [var.alert_email] : null
  }

  depends_on = [aws_sns_topic_policy.budget]
}
