# Hourly sweep (SWEEP_INTERVAL in backend/src/phoebe/lambdas/timings.py).
resource "aws_scheduler_schedule" "sweeper" {
  name                = "${local.prefix}-sweeper"
  description         = "Expired sandboxes and stuck indexing jobs"
  schedule_expression = "rate(1 hour)"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.this["sweeper"].arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({})

    retry_policy {
      maximum_retry_attempts = 0 # the next hourly run is the retry
    }
  }
}
