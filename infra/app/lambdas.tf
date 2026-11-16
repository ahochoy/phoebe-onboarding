# Ruling R9: two images from one Dockerfile, both in ECR repo phoebe-api and
# pinned by digest. The API runs the `api` target (Lambda Web Adapter extension,
# uvicorn CMD). Every other Lambda runs the `jobs` target, which has no adapter
# and ENTRYPOINT `python -m awslambdaric`; the Lambda passes only the handler.

locals {
  image_repo     = "${local.account_id}.dkr.ecr.${local.region}.amazonaws.com/phoebe-api"
  api_image_uri  = "${local.image_repo}@${var.api_image_digest}"
  jobs_image_uri = "${local.image_repo}@${var.jobs_image_digest}"

  # Every Data API-backed handler builds the same deps as the API (runtime.deps),
  # so they share one backend configuration.
  app_env = {
    PHOEBE_AWS_REGION        = local.region
    PHOEBE_LOG_LEVEL         = var.log_level
    PHOEBE_DB_BACKEND        = "data_api"
    PHOEBE_DB_CLUSTER_ARN    = aws_rds_cluster.main.arn
    PHOEBE_DB_SECRET_ARN     = local.db_secret_arn
    PHOEBE_DB_NAME           = local.db_name
    PHOEBE_BLOB_BACKEND      = "s3"
    PHOEBE_UPLOADS_BUCKET    = aws_s3_bucket.uploads.bucket
    PHOEBE_JOB_BACKEND       = "sqs"
    PHOEBE_JOBS_QUEUE_URL    = aws_sqs_queue.jobs.url
    PHOEBE_SESSION_BACKEND   = "dynamodb"
    PHOEBE_SESSIONS_TABLE    = aws_dynamodb_table.sessions.name
    PHOEBE_LIMITS_BACKEND    = "dynamodb"
    PHOEBE_CONTROL_BACKEND   = "dynamodb"
    PHOEBE_STATE_TABLE       = aws_dynamodb_table.state.name
    PHOEBE_EMBEDDER          = "titan"
    PHOEBE_ANSWER_BACKEND    = "harness"
    PHOEBE_HARNESS_ARN       = local.harness_arn
    PHOEBE_REWRITER_BACKEND  = "bedrock"
    PHOEBE_GUARDRAIL_ID      = local.ai.guardrail_id
    PHOEBE_GUARDRAIL_VERSION = local.ai.guardrail_version
  }

  # Ruling R1: secrets reach the API only as ARNs, resolved once at startup.
  api_env = merge(local.app_env, {
    AWS_LWA_INVOKE_MODE             = "response_stream"
    PHOEBE_CLIENT_IP_HEADER         = "cloudfront-viewer-address"
    PHOEBE_ORIGIN_SECRET_ARN        = aws_secretsmanager_secret.origin.arn
    PHOEBE_PASSWORD_HASH_SECRET_ARN = var.password_hash_secret_arn
  })

  budget_env = {
    PHOEBE_AWS_REGION      = local.region
    PHOEBE_LOG_LEVEL       = var.log_level
    PHOEBE_CONTROL_BACKEND = "dynamodb"
    PHOEBE_STATE_TABLE     = aws_dynamodb_table.state.name
  }

  functions = {
    api = {
      handler     = null
      timeout     = 90
      memory      = 1024
      reserved    = 5
      environment = local.api_env
    }
    worker = {
      handler     = "phoebe.lambdas.worker.handler"
      timeout     = local.worker_timeout_s
      memory      = 1024
      reserved    = 2
      environment = local.app_env
    }
    dlq = {
      handler     = "phoebe.lambdas.dlq.handler"
      timeout     = local.dlq_handler_timeout_s
      memory      = 512
      reserved    = null
      environment = local.app_env
    }
    sweeper = {
      handler     = "phoebe.lambdas.sweeper.handler"
      timeout     = 300
      memory      = 512
      reserved    = null
      environment = local.app_env
    }
    ops = {
      handler     = "phoebe.lambdas.ops.handler"
      timeout     = 900
      memory      = 1024
      reserved    = null
      environment = local.app_env
    }
    budget = {
      handler     = "phoebe.lambdas.budget.handler"
      timeout     = 30
      memory      = 256
      reserved    = null
      environment = local.budget_env
    }
  }
}

resource "aws_cloudwatch_log_group" "lambda" {
  for_each = local.functions

  name              = "/aws/lambda/${local.prefix}-${each.key}"
  retention_in_days = local.production ? 30 : 14
}

resource "aws_lambda_function" "this" {
  for_each = local.functions

  function_name = "${local.prefix}-${each.key}"
  role          = aws_iam_role.lambda[each.key].arn
  package_type  = "Image"
  image_uri     = each.value.handler == null ? local.api_image_uri : local.jobs_image_uri
  architectures = ["arm64"]
  timeout       = each.value.timeout
  memory_size   = each.value.memory

  reserved_concurrent_executions = each.value.reserved

  dynamic "image_config" {
    for_each = each.value.handler == null ? [] : [each.value.handler]
    content {
      command = [image_config.value]
    }
  }

  environment {
    variables = each.value.environment
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.lambda[each.key].name
  }

  # The API reads the origin secret at startup, so its value must exist first.
  depends_on = [aws_iam_role_policy.lambda, aws_secretsmanager_secret_version.origin]
}

# ---- Function URL, locked to CloudFront by the origin secret ---------------
# Auth NONE: the API's origin guard (Task 2) rejects any request without the
# X-Phoebe-Origin header CloudFront adds (Task 6), except /api/health. The
# provider adds the public InvokeFunctionUrl/InvokeFunction permissions.

resource "aws_lambda_function_url" "api" {
  function_name      = aws_lambda_function.this["api"].function_name
  authorization_type = "NONE"
  invoke_mode        = "RESPONSE_STREAM"
}

resource "random_password" "origin" {
  length  = 48
  special = false
}

resource "aws_secretsmanager_secret" "origin" {
  name                    = "${local.prefix}-origin-secret"
  description             = "X-Phoebe-Origin header value that CloudFront sends to the API function URL."
  recovery_window_in_days = local.production ? 30 : 0
}

resource "aws_secretsmanager_secret_version" "origin" {
  secret_id     = aws_secretsmanager_secret.origin.id
  secret_string = random_password.origin.result
}
