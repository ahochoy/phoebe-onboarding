# The account budget and its SNS topic (phoebe-budget, us-east-2) live in
# infra/bootstrap. Each env subscribes its own budget Lambda, which pauses chat.

resource "aws_lambda_permission" "budget_sns" {
  statement_id  = "AllowBudgetTopic"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.this["budget"].function_name
  principal     = "sns.amazonaws.com"
  source_arn    = var.budget_topic_arn
}

resource "aws_sns_topic_subscription" "budget" {
  topic_arn = var.budget_topic_arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.this["budget"].arn

  depends_on = [aws_lambda_permission.budget_sns]
}
