# Spend-limit mode (Plan 5 item 1). When the project's spend limit (or anyone)
# stops an env's Aurora cluster, RDS emits RDS-EVENT-0150 ("DB cluster
# stopped"). A rule per env sends it to:
# - that env's budget Lambda (created by infra/app, which grants the invoke),
#   which closes the demo so nothing reaches the stopped database;
# - phoebe-alerts, which emails the owner how to restart.
# Nothing here starts the cluster or reopens the demo: only `make db-start`.

locals {
  db_stopped_rule_arns = [
    for env in local.envs : "arn:aws:events:${local.region}:${local.account_id}:rule/phoebe-${env}-db-stopped"
  ]
}

# Unencrypted like the budget topics: messages carry only the env and event id.
resource "aws_sns_topic" "alerts" {
  name = "phoebe-alerts"
}

resource "aws_sns_topic_policy" "alerts" {
  arn = aws_sns_topic.alerts.arn

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DbStoppedRulesPublish"
      Effect    = "Allow"
      Principal = { Service = "events.amazonaws.com" }
      Action    = "SNS:Publish"
      Resource  = aws_sns_topic.alerts.arn
      Condition = {
        ArnEquals = { "aws:SourceArn" = local.db_stopped_rule_arns }
      }
    }]
  })
}

# The owner confirms the subscription from the email AWS sends.
resource "aws_sns_topic_subscription" "alert_email" {
  count = var.alert_email == null ? 0 : 1

  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_event_rule" "db_stopped" {
  for_each = toset(local.envs)

  name        = "phoebe-${each.key}-db-stopped"
  description = "phoebe-${each.key} Aurora cluster stopped: close the demo and email the owner."
  event_pattern = jsonencode({
    source        = ["aws.rds"]
    "detail-type" = ["RDS DB Cluster Event"]
    detail = {
      EventID          = ["RDS-EVENT-0150"]
      SourceIdentifier = ["phoebe-${each.key}"]
    }
  })
}

resource "aws_cloudwatch_event_target" "db_stopped_lambda" {
  for_each = toset(local.envs)

  rule = aws_cloudwatch_event_rule.db_stopped[each.key].name
  arn  = "arn:aws:lambda:${local.region}:${local.account_id}:function:phoebe-${each.key}-budget"
}

resource "aws_cloudwatch_event_target" "db_stopped_email" {
  for_each = toset(local.envs)

  rule = aws_cloudwatch_event_rule.db_stopped[each.key].name
  arn  = aws_sns_topic.alerts.arn

  # Only the env and event id reach the email, never the raw event.
  input_transformer {
    input_paths    = { event = "$.detail.EventID" }
    input_template = "\"Phoebe ${each.key}: database stopped (<event>). The demo is closed. When the spend limit allows, run: make db-start ENV=${each.key}\""
  }

  depends_on = [aws_sns_topic_policy.alerts]
}
