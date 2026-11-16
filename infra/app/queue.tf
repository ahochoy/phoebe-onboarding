# Timings are pinned in backend/src/phoebe/lambdas/timings.py (ruling R8);
# keep these numbers identical to it.
locals {
  worker_timeout_s           = 120 # WORKER_TIMEOUT_S
  queue_visibility_timeout_s = 720 # QUEUE_VISIBILITY_TIMEOUT_S (6x the worker timeout)
  max_receive_count          = 3   # MAX_RECEIVE_COUNT
  dlq_handler_timeout_s      = 60
}

resource "aws_sqs_queue" "jobs_dlq" {
  name                       = "${local.prefix}-jobs-dlq"
  message_retention_seconds  = 1209600 # 14 days
  visibility_timeout_seconds = 6 * local.dlq_handler_timeout_s
  sqs_managed_sse_enabled    = true
}

resource "aws_sqs_queue" "jobs" {
  name                       = "${local.prefix}-jobs"
  visibility_timeout_seconds = local.queue_visibility_timeout_s
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.jobs_dlq.arn
    maxReceiveCount     = local.max_receive_count
  })
}

resource "aws_sqs_queue_redrive_allow_policy" "jobs_dlq" {
  queue_url = aws_sqs_queue.jobs_dlq.id

  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.jobs.arn]
  })
}

# Both handlers return {"batchItemFailures": [...]}.
resource "aws_lambda_event_source_mapping" "worker" {
  event_source_arn        = aws_sqs_queue.jobs.arn
  function_name           = aws_lambda_function.this["worker"].arn
  batch_size              = 1
  function_response_types = ["ReportBatchItemFailures"]

  scaling_config {
    maximum_concurrency = 2 # matches the worker's reserved concurrency
  }
}

resource "aws_lambda_event_source_mapping" "dlq" {
  event_source_arn        = aws_sqs_queue.jobs_dlq.arn
  function_name           = aws_lambda_function.this["dlq"].arn
  batch_size              = 10
  function_response_types = ["ReportBatchItemFailures"]

  scaling_config {
    maximum_concurrency = 2
  }
}
