# One account cost budget, two topics (ruling R16). Each env's budget Lambda
# subscribes only to its own topic from infra/app, so a staging deploy can
# never unsubscribe or redirect production's kill switch. The budget notifies
# both topics.
#
# Budgets is a global API that the provider reaches from this us-east-2
# provider (aws_budgets_budget takes no region), so no us-east-1 provider is
# needed. Both topics live in us-east-2.

locals {
  budget_name = "phoebe-monthly"

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
    subscriber_sns_topic_arns = [for env in local.envs : aws_sns_topic.budget[env].arn]
  }

  depends_on = [aws_sns_topic_policy.budget]
}
