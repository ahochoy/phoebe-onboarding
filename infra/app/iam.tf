# One least-privilege role per Lambda. Policies are plain jsonencode (not
# aws_iam_policy_document) so the offline tests can inspect them under mocks.
# Every role carries the bootstrap permissions boundary.

locals {
  titan_model_id   = "amazon.titan-embed-text-v2:0"
  nova_profile_id  = "us.amazon.nova-micro-v1:0" # PHOEBE_REWRITE_MODEL_ID default
  nova_model_id    = "amazon.nova-micro-v1:0"
  haiku_profile_id = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
  haiku_model_id   = "anthropic.claude-haiku-4-5-20251001-v1:0"

  # The `us.` profiles route across these Regions (same pattern as infra/ai).
  profile_regions = ["us-east-1", "us-east-2", "us-west-2"]

  titan_arns = ["arn:${local.partition}:bedrock:${local.region}::foundation-model/${local.titan_model_id}"]

  # Query rewriting calls Converse on the Nova Micro inference profile. Haiku is
  # reached only through the harness, whose own role invokes the model.
  rewriter_arns = concat(
    ["arn:${local.partition}:bedrock:${local.region}:${local.account_id}:inference-profile/${local.nova_profile_id}"],
    [for r in local.profile_regions : "arn:${local.partition}:bedrock:${r}::foundation-model/${local.nova_model_id}"],
  )

  log_statement = {
    for k in keys(local.functions) : k => {
      Sid      = "WriteOwnLogs"
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = ["${aws_cloudwatch_log_group.lambda[k].arn}:*"]
    }
  }

  data_api_statements = [
    {
      Sid    = "DataApi"
      Effect = "Allow"
      Action = [
        "rds-data:ExecuteStatement",
        "rds-data:BeginTransaction",
        "rds-data:CommitTransaction",
        "rds-data:RollbackTransaction",
      ]
      Resource = [aws_rds_cluster.main.arn]
    },
    {
      Sid      = "DbSecret"
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = [local.db_secret_arn]
    },
  ]

  # Ruling R10: GetObject on a missing key returns NoSuchKey (404) only when
  # the caller has s3:ListBucket on the bucket. That check carries no s3:prefix
  # context, so the grant must be bucket-level with no condition, or S3
  # returns AccessDenied and the worker retries a permanent miss to the DLQ.
  # Only the API and worker read blobs, so only they get it.
  list_uploads_statement = {
    Sid      = "ListUploads"
    Effect   = "Allow"
    Action   = ["s3:ListBucket"]
    Resource = [aws_s3_bucket.uploads.arn]
  }

  uploads_objects = ["${aws_s3_bucket.uploads.arn}/uploads/*"]

  embed_statement = {
    Sid      = "EmbedTitan"
    Effect   = "Allow"
    Action   = ["bedrock:InvokeModel"]
    Resource = local.titan_arns
  }

  policy_statements = {
    api = concat(local.data_api_statements, [
      local.log_statement["api"],
      {
        Sid      = "AppSecrets"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = [aws_secretsmanager_secret.origin.arn, var.password_hash_secret_arn]
      },
      {
        Sid      = "UploadObjects"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = local.uploads_objects
      },
      local.list_uploads_statement,
      {
        Sid      = "EnqueueJobs"
        Effect   = "Allow"
        Action   = ["sqs:SendMessage"]
        Resource = [aws_sqs_queue.jobs.arn]
      },
      {
        Sid      = "SessionsAndState"
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"]
        Resource = [aws_dynamodb_table.sessions.arn, aws_dynamodb_table.state.arn]
      },
      local.embed_statement,
      {
        Sid      = "RewriteNovaMicro"
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel"]
        Resource = local.rewriter_arns
      },
      {
        Sid      = "Guardrail"
        Effect   = "Allow"
        Action   = ["bedrock:ApplyGuardrail"]
        Resource = [local.guardrail_arn]
      },
      {
        Sid      = "AnswerHarness"
        Effect   = "Allow"
        Action   = ["bedrock-agentcore:InvokeHarness"] # botocore bedrock-agentcore: operation InvokeHarness
        Resource = [local.harness_arn]
      },
    ])

    worker = concat(local.data_api_statements, [
      local.log_statement["worker"],
      {
        Sid      = "ReadUploads"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = local.uploads_objects
      },
      local.list_uploads_statement,
      {
        Sid      = "ConsumeJobs"
        Effect   = "Allow"
        Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:ChangeMessageVisibility"]
        Resource = [aws_sqs_queue.jobs.arn]
      },
      local.embed_statement,
    ])

    dlq = concat(local.data_api_statements, [
      local.log_statement["dlq"],
      {
        Sid      = "ConsumeDeadLetters"
        Effect   = "Allow"
        Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:ChangeMessageVisibility"]
        Resource = [aws_sqs_queue.jobs_dlq.arn]
      },
    ])

    sweeper = concat(local.data_api_statements, [
      local.log_statement["sweeper"],
      {
        Sid      = "DeleteUploads"
        Effect   = "Allow"
        Action   = ["s3:DeleteObject"]
        Resource = local.uploads_objects
      },
      {
        # Ruling R26: reads activity#last / sweep#last_started to skip the
        # DB when nothing is owed, and writes sweep#last_started after a
        # completed sweep. Only those keys.
        Sid      = "IdleState"
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem"]
        Resource = [aws_dynamodb_table.state.arn]
        Condition = {
          "ForAllValues:StringEquals" = {
            "dynamodb:LeadingKeys" = ["activity#last", "sweep#last_started"]
          }
        }
      },
    ])

    # migrate / seed_if_empty (seeding embeds with Titan) / status.
    ops = concat(local.data_api_statements, [
      local.log_statement["ops"],
      local.embed_statement,
    ])

    budget = [
      local.log_statement["budget"],
      {
        Sid      = "KillSwitch"
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem"]
        Resource = [aws_dynamodb_table.state.arn]
      },
    ]
  }
}

resource "aws_iam_role" "lambda" {
  for_each = local.functions

  name                 = "${local.prefix}-${each.key}"
  description          = "Execution role for the ${local.prefix}-${each.key} Lambda"
  permissions_boundary = var.boundary_policy_arn

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "lambda.amazonaws.com" }
      Condition = {
        StringEquals = { "aws:SourceAccount" = local.account_id }
      }
    }]
  })
}

resource "aws_iam_role_policy" "lambda" {
  for_each = local.functions

  name = "${local.prefix}-${each.key}"
  role = aws_iam_role.lambda[each.key].id

  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = local.policy_statements[each.key]
  })
}

# ---- EventBridge Scheduler -> sweeper ---------------------------------------

resource "aws_iam_role" "scheduler" {
  name                 = "${local.prefix}-scheduler"
  description          = "Lets EventBridge Scheduler invoke the ${local.prefix} sweeper"
  permissions_boundary = var.boundary_policy_arn

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "scheduler.amazonaws.com" }
      Condition = {
        StringEquals = { "aws:SourceAccount" = local.account_id }
      }
    }]
  })
}

resource "aws_iam_role_policy" "scheduler" {
  name = "${local.prefix}-scheduler"
  role = aws_iam_role.scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "InvokeSweeper"
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = aws_lambda_function.this["sweeper"].arn
    }]
  })
}
