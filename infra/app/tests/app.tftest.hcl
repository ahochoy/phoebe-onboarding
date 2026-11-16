# Offline: every AWS call is mocked. Values that the code compares against
# (account id, ARNs, infra/ai outputs) are overridden so they look real.

mock_provider "aws" {
  # The provider validates these as ARNs; random mock strings would fail.
  mock_resource "aws_iam_role" {
    defaults = {
      arn = "arn:aws:iam::123456789012:role/phoebe-staging-mock"
    }
  }

  mock_resource "aws_cloudwatch_log_group" {
    defaults = {
      arn = "arn:aws:logs:us-east-2:123456789012:log-group:/aws/lambda/phoebe-staging-mock"
    }
  }

  mock_resource "aws_s3_bucket" {
    defaults = {
      arn = "arn:aws:s3:::phoebe-staging-mock"
    }
  }

  mock_resource "aws_cloudfront_function" {
    defaults = {
      arn = "arn:aws:cloudfront::123456789012:function/phoebe-staging-spa-router"
    }
  }

  mock_resource "aws_dynamodb_table" {
    defaults = {
      arn = "arn:aws:dynamodb:us-east-2:123456789012:table/phoebe-staging-mock"
    }
  }
}

# Distinct ARNs where a test checks that the right thing is wired together.
override_resource {
  target = aws_lambda_function.this["sweeper"]
  values = {
    arn = "arn:aws:lambda:us-east-2:123456789012:function:phoebe-staging-sweeper"
  }
}

override_resource {
  target = aws_lambda_function.this["budget"]
  values = {
    arn = "arn:aws:lambda:us-east-2:123456789012:function:phoebe-staging-budget"
  }
}

override_resource {
  target = aws_lambda_function.this["worker"]
  values = {
    arn = "arn:aws:lambda:us-east-2:123456789012:function:phoebe-staging-worker"
  }
}

override_resource {
  target = aws_lambda_function.this["dlq"]
  values = {
    arn = "arn:aws:lambda:us-east-2:123456789012:function:phoebe-staging-dlq"
  }
}

override_resource {
  target = aws_lambda_function.this["api"]
  values = {
    arn = "arn:aws:lambda:us-east-2:123456789012:function:phoebe-staging-api"
  }
}

override_resource {
  target = aws_lambda_function.this["ops"]
  values = {
    arn = "arn:aws:lambda:us-east-2:123456789012:function:phoebe-staging-ops"
  }
}

override_resource {
  target = aws_sqs_queue.jobs
  values = {
    arn = "arn:aws:sqs:us-east-2:123456789012:phoebe-staging-jobs"
    url = "https://sqs.us-east-2.amazonaws.com/123456789012/phoebe-staging-jobs"
    id  = "https://sqs.us-east-2.amazonaws.com/123456789012/phoebe-staging-jobs"
  }
}

override_resource {
  target = aws_sqs_queue.jobs_dlq
  values = {
    arn = "arn:aws:sqs:us-east-2:123456789012:phoebe-staging-jobs-dlq"
    url = "https://sqs.us-east-2.amazonaws.com/123456789012/phoebe-staging-jobs-dlq"
    id  = "https://sqs.us-east-2.amazonaws.com/123456789012/phoebe-staging-jobs-dlq"
  }
}

override_resource {
  target = aws_s3_bucket.uploads
  values = {
    arn = "arn:aws:s3:::phoebe-staging-uploads-123456789012"
    id  = "phoebe-staging-uploads-123456789012"
  }
}

override_resource {
  target = aws_s3_bucket.site
  values = {
    arn = "arn:aws:s3:::phoebe-staging-site-123456789012"
    id  = "phoebe-staging-site-123456789012"

    bucket_regional_domain_name = "phoebe-staging-site-123456789012.s3.us-east-2.amazonaws.com"
  }
}

override_resource {
  target = aws_lambda_function_url.api
  values = {
    function_url = "https://abcdefghij0123456789.lambda-url.us-east-2.on.aws/"
  }
}

override_resource {
  target = aws_cloudfront_distribution.main
  values = {
    arn         = "arn:aws:cloudfront::123456789012:distribution/E1ABCDEFGHIJKL"
    domain_name = "d111111abcdef8.cloudfront.net"
  }
}

override_data {
  target = data.aws_caller_identity.current
  values = {
    account_id = "123456789012"
  }
}

override_data {
  target = data.aws_partition.current
  values = {
    partition = "aws"
  }
}

override_data {
  target = data.terraform_remote_state.ai
  values = {
    outputs = {
      guardrail_id      = "gr0abc123def"
      guardrail_version = "1"
      harness_haiku_arn = "arn:aws:bedrock-agentcore:us-east-2:123456789012:harness/PhoebeHaikuHarness-AbCdEf1234"
      harness_nova_arn  = "arn:aws:bedrock-agentcore:us-east-2:123456789012:harness/PhoebeNovaHarness-ZyXwVu9876"
    }
  }
}

override_resource {
  target = aws_rds_cluster.main
  values = {
    arn = "arn:aws:rds:us-east-2:123456789012:cluster:phoebe-staging"
    master_user_secret = [{
      kms_key_id    = "arn:aws:kms:us-east-2:123456789012:key/00000000-0000-0000-0000-000000000000"
      secret_arn    = "arn:aws:secretsmanager:us-east-2:123456789012:secret:rds!cluster-0000-AbCdEf"
      secret_status = "active"
    }]
  }
}

override_resource {
  target = aws_secretsmanager_secret.origin
  values = {
    arn = "arn:aws:secretsmanager:us-east-2:123456789012:secret:phoebe-staging-origin-secret-QwErTy"
  }
}

variables {
  env                      = "staging"
  api_image_digest         = "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
  jobs_image_digest        = "sha256:fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"
  boundary_policy_arn      = "arn:aws:iam::123456789012:policy/phoebe-boundary-staging"
  ai_state_bucket          = "phoebe-tfstate-123456789012"
  budget_topic_arn         = "arn:aws:sns:us-east-2:123456789012:phoebe-budget"
  password_hash_secret_arn = "arn:aws:secretsmanager:us-east-2:123456789012:secret:phoebe-staging-password-hash-AbC123"
}

run "aurora" {
  command = apply

  assert {
    condition     = aws_rds_cluster.main.engine == "aurora-postgresql" && aws_rds_cluster.main.engine_mode == "provisioned"
    error_message = "Aurora must be aurora-postgresql (provisioned mode, Serverless v2)."
  }

  assert {
    condition     = aws_rds_cluster.main.enable_http_endpoint == true
    error_message = "The Data API (enable_http_endpoint) must be on."
  }

  assert {
    condition = (
      aws_rds_cluster.main.serverlessv2_scaling_configuration[0].min_capacity == 0 &&
      aws_rds_cluster.main.serverlessv2_scaling_configuration[0].max_capacity == 2 &&
      aws_rds_cluster.main.serverlessv2_scaling_configuration[0].seconds_until_auto_pause == 300
    )
    error_message = "Serverless v2 scaling must be 0..2 ACU with auto-pause after 300 s."
  }

  assert {
    condition     = aws_rds_cluster.main.storage_encrypted == true
    error_message = "Aurora storage must be encrypted."
  }

  assert {
    condition     = aws_rds_cluster.main.deletion_protection == false
    error_message = "Staging has no deletion protection (deletion_protection == env is production)."
  }

  assert {
    condition     = aws_rds_cluster.main.manage_master_user_password == true
    error_message = "Credentials come from Aurora's managed master-user secret."
  }

  assert {
    condition     = aws_rds_cluster.main.database_name == "phoebe" && aws_rds_cluster.main.cluster_identifier == "phoebe-staging"
    error_message = "Cluster phoebe-staging with database phoebe."
  }

  assert {
    condition     = aws_rds_cluster_instance.main.publicly_accessible == false && aws_rds_cluster_instance.main.instance_class == "db.serverless"
    error_message = "The writer is a private db.serverless instance."
  }
}

run "lambdas" {
  command = apply

  assert {
    condition     = length(aws_lambda_function.this) == 6
    error_message = "Six Lambdas: api, worker, dlq, sweeper, ops, budget."
  }

  assert {
    condition = alltrue([
      for f in values(aws_lambda_function.this) :
      f.package_type == "Image" && length(f.architectures) == 1 && f.architectures[0] == "arm64"
    ])
    error_message = "Every Lambda is an arm64 container image."
  }

  # Ruling R9: the API runs the `api` image (with the Lambda Web Adapter); every
  # other Lambda runs the `jobs` image (awslambdaric, no adapter).
  assert {
    condition     = aws_lambda_function.this["api"].image_uri == "123456789012.dkr.ecr.us-east-2.amazonaws.com/phoebe-api@${var.api_image_digest}"
    error_message = "The API Lambda runs the api image pinned by digest."
  }

  assert {
    condition = alltrue([
      for k, f in aws_lambda_function.this :
      f.image_uri == "123456789012.dkr.ecr.us-east-2.amazonaws.com/phoebe-api@${var.jobs_image_digest}"
      if k != "api"
    ]) && length([for k, f in aws_lambda_function.this : k if k != "api"]) == 5
    error_message = "Worker, DLQ, sweeper, ops and budget run the jobs image pinned by digest."
  }

  assert {
    condition = alltrue([
      for k, f in aws_lambda_function.this :
      !endswith(f.image_uri, "@${var.api_image_digest}") if k != "api"
    ])
    error_message = "No jobs Lambda may run the api image (its adapter extension would hijack the runtime)."
  }

  assert {
    condition = alltrue([
      for k, f in aws_lambda_function.this : f.function_name == "phoebe-staging-${k}"
    ])
    error_message = "Lambda names are phoebe-<env>-<role>."
  }

  assert {
    condition = (
      aws_lambda_function.this["api"].reserved_concurrent_executions == 5 &&
      aws_lambda_function.this["worker"].reserved_concurrent_executions == 2
    )
    error_message = "API reserved concurrency 5, worker 2."
  }

  assert {
    condition     = aws_lambda_function.this["worker"].timeout == 120
    error_message = "Worker timeout is WORKER_TIMEOUT_S = 120 (timings.py)."
  }

  assert {
    condition     = length(aws_lambda_function.this["api"].image_config) == 0
    error_message = "The API keeps the image CMD (uvicorn under the Lambda Web Adapter)."
  }

  assert {
    condition = alltrue([
      for k, h in {
        worker  = "phoebe.lambdas.worker.handler"
        dlq     = "phoebe.lambdas.dlq.handler"
        sweeper = "phoebe.lambdas.sweeper.handler"
        ops     = "phoebe.lambdas.ops.handler"
        budget  = "phoebe.lambdas.budget.handler"
      } :
      length(aws_lambda_function.this[k].image_config[0].command) == 1 &&
      aws_lambda_function.this[k].image_config[0].command[0] == h &&
      length(coalesce(aws_lambda_function.this[k].image_config[0].entry_point, [])) == 0
    ])
    error_message = "Jobs Lambdas pass only the handler; the jobs image's ENTRYPOINT is python -m awslambdaric."
  }

  assert {
    condition = (
      aws_lambda_function_url.api.function_name == aws_lambda_function.this["api"].function_name &&
      aws_lambda_function_url.api.invoke_mode == "RESPONSE_STREAM" &&
      aws_lambda_function_url.api.authorization_type == "NONE"
    )
    error_message = "The API function URL streams and has auth NONE (guarded by the origin secret)."
  }

  assert {
    condition = alltrue([
      for k, v in {
        AWS_LWA_INVOKE_MODE             = "response_stream"
        PHOEBE_DB_BACKEND               = "data_api"
        PHOEBE_BLOB_BACKEND             = "s3"
        PHOEBE_JOB_BACKEND              = "sqs"
        PHOEBE_SESSION_BACKEND          = "dynamodb"
        PHOEBE_LIMITS_BACKEND           = "dynamodb"
        PHOEBE_CONTROL_BACKEND          = "dynamodb"
        PHOEBE_EMBEDDER                 = "titan"
        PHOEBE_ANSWER_BACKEND           = "harness"
        PHOEBE_REWRITER_BACKEND         = "bedrock"
        PHOEBE_CLIENT_IP_HEADER         = "cloudfront-viewer-address"
        PHOEBE_GUARDRAIL_ID             = "gr0abc123def"
        PHOEBE_GUARDRAIL_VERSION        = "1"
        PHOEBE_HARNESS_ARN              = "arn:aws:bedrock-agentcore:us-east-2:123456789012:harness/PhoebeHaikuHarness-AbCdEf1234"
        PHOEBE_AWS_REGION               = "us-east-2"
        PHOEBE_DB_NAME                  = "phoebe"
        PHOEBE_SESSIONS_TABLE           = "phoebe-staging-sessions"
        PHOEBE_STATE_TABLE              = "phoebe-staging-state"
        PHOEBE_UPLOADS_BUCKET           = "phoebe-staging-uploads-123456789012"
        PHOEBE_DB_CLUSTER_ARN           = "arn:aws:rds:us-east-2:123456789012:cluster:phoebe-staging"
        PHOEBE_DB_SECRET_ARN            = "arn:aws:secretsmanager:us-east-2:123456789012:secret:rds!cluster-0000-AbCdEf"
        PHOEBE_ORIGIN_SECRET_ARN        = "arn:aws:secretsmanager:us-east-2:123456789012:secret:phoebe-staging-origin-secret-QwErTy"
        PHOEBE_PASSWORD_HASH_SECRET_ARN = "arn:aws:secretsmanager:us-east-2:123456789012:secret:phoebe-staging-password-hash-AbC123"
      } :
      lookup(aws_lambda_function.this["api"].environment[0].variables, k, null) == v
    ])
    error_message = "The API environment is missing a backend setting or carries the wrong value."
  }

  assert {
    condition     = aws_lambda_function.this["api"].environment[0].variables["PHOEBE_JOBS_QUEUE_URL"] == aws_sqs_queue.jobs.url
    error_message = "The API enqueues to the jobs queue."
  }

  assert {
    condition = alltrue([
      for k in ["worker", "dlq", "sweeper", "ops"] :
      aws_lambda_function.this[k].environment[0].variables["PHOEBE_DB_BACKEND"] == "data_api" &&
      aws_lambda_function.this[k].environment[0].variables["PHOEBE_DB_SECRET_ARN"] == aws_rds_cluster.main.master_user_secret[0].secret_arn &&
      !contains(keys(aws_lambda_function.this[k].environment[0].variables), "PHOEBE_ORIGIN_SECRET_ARN") &&
      !contains(keys(aws_lambda_function.this[k].environment[0].variables), "PHOEBE_PASSWORD_HASH_SECRET_ARN")
    ])
    error_message = "Background Lambdas use the Data API and never get the API-only secret ARNs."
  }

  assert {
    condition = (
      aws_lambda_function.this["budget"].environment[0].variables["PHOEBE_STATE_TABLE"] == "phoebe-staging-state" &&
      !contains(keys(aws_lambda_function.this["budget"].environment[0].variables), "PHOEBE_DB_SECRET_ARN")
    )
    error_message = "The budget Lambda only needs the state table."
  }

  # Ruling R1: secrets reach Lambdas only as ARNs, resolved at startup.
  assert {
    condition = alltrue([
      for f in values(aws_lambda_function.this) :
      !contains(keys(f.environment[0].variables), "PHOEBE_ORIGIN_SECRET") &&
      !contains(keys(f.environment[0].variables), "PHOEBE_PASSWORD_HASH") &&
      !contains(keys(f.environment[0].variables), "PHOEBE_DATABASE_URL") &&
      !contains(nonsensitive([for v in values(f.environment[0].variables) : v == random_password.origin.result]), true)
    ])
    error_message = "No secret value may appear in a Lambda environment."
  }

  assert {
    condition     = aws_secretsmanager_secret.origin.name == "phoebe-staging-origin-secret"
    error_message = "The origin secret is phoebe-<env>-origin-secret."
  }

  assert {
    condition = alltrue([
      for k, g in aws_cloudwatch_log_group.lambda :
      g.name == "/aws/lambda/phoebe-staging-${k}" && g.retention_in_days > 0
    ])
    error_message = "Each Lambda has its own log group with a retention."
  }
}

run "iam" {
  command = apply

  assert {
    condition = alltrue(concat(
      [for r in values(aws_iam_role.lambda) : r.permissions_boundary == var.boundary_policy_arn],
      [aws_iam_role.scheduler.permissions_boundary == var.boundary_policy_arn],
    ))
    error_message = "Every IAM role sets the bootstrap permissions boundary."
  }

  assert {
    condition = alltrue(concat(
      [for r in values(aws_iam_role.lambda) : startswith(r.name, "phoebe-staging-")],
      [startswith(aws_iam_role.scheduler.name, "phoebe-staging-")],
    ))
    error_message = "Roles are named phoebe-<env>-*."
  }

  # Bedrock: only Titan, Nova Micro, Haiku, the infra/ai harness and guardrail.
  assert {
    condition = alltrue(flatten([
      for st in jsondecode(aws_iam_role_policy.lambda["api"].policy).Statement : [
        for r in flatten([st.Resource]) : contains([
          "arn:aws:bedrock:us-east-2::foundation-model/amazon.titan-embed-text-v2:0",
          "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-micro-v1:0",
          "arn:aws:bedrock:us-east-2::foundation-model/amazon.nova-micro-v1:0",
          "arn:aws:bedrock:us-west-2::foundation-model/amazon.nova-micro-v1:0",
          "arn:aws:bedrock:us-east-2:123456789012:inference-profile/us.amazon.nova-micro-v1:0",
          "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
          "arn:aws:bedrock:us-east-2::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
          "arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
          "arn:aws:bedrock:us-east-2:123456789012:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0",
          "arn:aws:bedrock:us-east-2:123456789012:guardrail/gr0abc123def",
          "arn:aws:bedrock-agentcore:us-east-2:123456789012:harness/PhoebeHaikuHarness-AbCdEf1234",
        ], r)
      ] if anytrue([for a in flatten([st.Action]) : startswith(a, "bedrock")])
    ]))
    error_message = "The API role may call Bedrock only on the pinned model, harness and guardrail ARNs."
  }

  assert {
    condition = alltrue([
      for r in [
        "arn:aws:bedrock:us-east-2::foundation-model/amazon.titan-embed-text-v2:0",
        "arn:aws:bedrock:us-east-2:123456789012:inference-profile/us.amazon.nova-micro-v1:0",
        "arn:aws:bedrock:us-east-2:123456789012:guardrail/gr0abc123def",
        "arn:aws:bedrock-agentcore:us-east-2:123456789012:harness/PhoebeHaikuHarness-AbCdEf1234",
      ] :
      contains(flatten([for st in jsondecode(aws_iam_role_policy.lambda["api"].policy).Statement : flatten([st.Resource])]), r)
    ])
    error_message = "The API role needs Titan (query embeddings), Nova Micro (rewriter), the guardrail and the harness."
  }

  assert {
    condition = alltrue([
      for st in jsondecode(aws_iam_role_policy.lambda["api"].policy).Statement :
      flatten([st.Resource]) == [aws_rds_cluster.main.arn]
      if anytrue([for a in flatten([st.Action]) : startswith(a, "rds-data:")])
      ]) && anytrue([
      for st in jsondecode(aws_iam_role_policy.lambda["api"].policy).Statement :
      contains(flatten([st.Action]), "rds-data:ExecuteStatement")
    ])
    error_message = "The API role gets rds-data only on its own cluster."
  }

  assert {
    condition = alltrue(flatten([
      for st in jsondecode(aws_iam_role_policy.lambda["api"].policy).Statement : [
        for r in flatten([st.Resource]) : contains([
          aws_rds_cluster.main.master_user_secret[0].secret_arn,
          aws_secretsmanager_secret.origin.arn,
          var.password_hash_secret_arn,
        ], r)
      ] if anytrue([for a in flatten([st.Action]) : startswith(a, "secretsmanager:")])
    ]))
    error_message = "The API role reads only its own DB, origin and password-hash secrets."
  }

  assert {
    condition = alltrue(flatten([
      for p in values(aws_iam_role_policy.lambda) : [
        for st in jsondecode(p.policy).Statement : !contains(flatten([st.Resource]), "*")
      ]
    ]))
    error_message = "No Lambda policy grants on Resource \"*\"."
  }

  # Task 2/3 carry plus ruling R10: an unconditioned bucket-level ListBucket so a
  # missing key is NoSuchKey. The 404-vs-403 check carries no s3:prefix, so a
  # prefix condition would never match.
  assert {
    condition = alltrue([
      for k in ["api", "worker"] : anytrue([
        for st in jsondecode(aws_iam_role_policy.lambda[k].policy).Statement :
        flatten([st.Action]) == ["s3:ListBucket"] &&
        flatten([st.Resource]) == [aws_s3_bucket.uploads.arn] &&
        try(st.Condition, null) == null
      ])
    ])
    error_message = "API and worker roles need an unconditioned s3:ListBucket on the uploads bucket."
  }

  assert {
    condition = alltrue(flatten([
      for k, p in aws_iam_role_policy.lambda : [
        for st in jsondecode(p.policy).Statement : !contains(flatten([st.Action]), "s3:ListBucket")
      ] if !contains(["api", "worker"], k)
    ]))
    error_message = "Only the API and worker roles may list the uploads bucket."
  }

  assert {
    condition = alltrue([
      for st in jsondecode(aws_iam_role_policy.lambda["api"].policy).Statement :
      flatten([st.Action]) == ["bedrock-agentcore:InvokeHarness"]
      if anytrue([for a in flatten([st.Action]) : startswith(a, "bedrock-agentcore:")])
    ])
    error_message = "The API role gets only bedrock-agentcore:InvokeHarness (the one call the code makes)."
  }

  assert {
    condition = alltrue(flatten([
      for p in values(aws_iam_role_policy.lambda) : [
        for st in jsondecode(p.policy).Statement : !contains(flatten([st.Action]), "rds-data:BatchExecuteStatement")
      ]
    ]))
    error_message = "db_data_api.py never batches, so no role gets rds-data:BatchExecuteStatement."
  }

  assert {
    condition = (
      length(aws_iam_role_policy.lambda) == 6 &&
      jsondecode(aws_iam_role_policy.scheduler.policy).Statement[0].Resource == aws_lambda_function.this["sweeper"].arn
    )
    error_message = "Each Lambda has its policy; the scheduler may invoke only the sweeper."
  }
}

run "storage" {
  command = apply

  assert {
    condition = (
      aws_s3_bucket.uploads.bucket == "phoebe-staging-uploads-123456789012" &&
      aws_s3_bucket.site.bucket == "phoebe-staging-site-123456789012"
    )
    error_message = "Bucket names follow ruling R2."
  }

  assert {
    condition = alltrue([
      for b in [aws_s3_bucket_public_access_block.uploads, aws_s3_bucket_public_access_block.site] :
      b.block_public_acls && b.block_public_policy && b.ignore_public_acls && b.restrict_public_buckets
    ])
    error_message = "Every public-access block is on for both buckets."
  }

  assert {
    condition = (
      aws_s3_bucket_public_access_block.uploads.bucket == aws_s3_bucket.uploads.id &&
      aws_s3_bucket_public_access_block.site.bucket == aws_s3_bucket.site.id
    )
    error_message = "The public-access blocks attach to the right buckets."
  }

  assert {
    condition = alltrue([
      for c in [aws_s3_bucket_server_side_encryption_configuration.uploads, aws_s3_bucket_server_side_encryption_configuration.site] :
      length(c.rule) == 1 && alltrue([
        for r in c.rule : alltrue([for d in r.apply_server_side_encryption_by_default : d.sse_algorithm == "AES256"])
      ])
    ])
    error_message = "Both buckets have SSE."
  }

  assert {
    condition = anytrue([
      for r in aws_s3_bucket_lifecycle_configuration.uploads.rule :
      r.status == "Enabled" && r.expiration[0].days == 2
    ])
    error_message = "Uploaded objects expire after 2 days (sandboxes live at most 24 h)."
  }

  assert {
    condition = alltrue([
      for t in [aws_dynamodb_table.sessions, aws_dynamodb_table.state] :
      t.billing_mode == "PAY_PER_REQUEST" && t.hash_key == "pk" &&
      one(t.ttl).attribute_name == "expires_at" && one(t.ttl).enabled
    ])
    error_message = "DynamoDB tables are on-demand, keyed by pk, with TTL on expires_at."
  }

  assert {
    condition = (
      aws_dynamodb_table.sessions.name == "phoebe-staging-sessions" &&
      aws_dynamodb_table.state.name == "phoebe-staging-state"
    )
    error_message = "Table names are phoebe-<env>-sessions and phoebe-<env>-state."
  }
}

run "queue" {
  command = apply

  # Ruling R8: the numbers in backend/src/phoebe/lambdas/timings.py.
  assert {
    condition = (
      aws_sqs_queue.jobs.visibility_timeout_seconds == 720 &&
      aws_sqs_queue.jobs.visibility_timeout_seconds >= 6 * aws_lambda_function.this["worker"].timeout
    )
    error_message = "Visibility timeout is 720 s (6x the worker timeout)."
  }

  assert {
    condition = (
      jsondecode(aws_sqs_queue.jobs.redrive_policy).maxReceiveCount == 3 &&
      jsondecode(aws_sqs_queue.jobs.redrive_policy).deadLetterTargetArn == aws_sqs_queue.jobs_dlq.arn
    )
    error_message = "The jobs queue redrives to the DLQ after 3 receives."
  }

  assert {
    condition     = aws_sqs_queue.jobs_dlq.message_retention_seconds == 1209600
    error_message = "The DLQ keeps messages for 14 days."
  }

  assert {
    condition = (
      aws_lambda_event_source_mapping.worker.event_source_arn == aws_sqs_queue.jobs.arn &&
      aws_lambda_event_source_mapping.worker.function_name == aws_lambda_function.this["worker"].arn &&
      contains(aws_lambda_event_source_mapping.worker.function_response_types, "ReportBatchItemFailures")
    )
    error_message = "The worker reads the jobs queue and reports batch item failures."
  }

  assert {
    condition = (
      aws_lambda_event_source_mapping.dlq.event_source_arn == aws_sqs_queue.jobs_dlq.arn &&
      aws_lambda_event_source_mapping.dlq.function_name == aws_lambda_function.this["dlq"].arn &&
      contains(aws_lambda_event_source_mapping.dlq.function_response_types, "ReportBatchItemFailures")
    )
    error_message = "The DLQ handler reads the DLQ and reports batch item failures."
  }

  assert {
    condition     = aws_sqs_queue.jobs_dlq.visibility_timeout_seconds >= aws_lambda_function.this["dlq"].timeout
    error_message = "SQS requires the DLQ visibility timeout to cover the DLQ handler's timeout."
  }
}

run "schedule" {
  command = apply

  assert {
    condition = (
      aws_scheduler_schedule.sweeper.schedule_expression == "rate(1 hour)" &&
      aws_scheduler_schedule.sweeper.target[0].arn == aws_lambda_function.this["sweeper"].arn &&
      aws_scheduler_schedule.sweeper.target[0].role_arn == aws_iam_role.scheduler.arn
    )
    error_message = "EventBridge Scheduler runs the sweeper hourly."
  }
}

run "budget" {
  command = apply

  assert {
    condition = (
      aws_sns_topic_subscription.budget.topic_arn == var.budget_topic_arn &&
      aws_sns_topic_subscription.budget.protocol == "lambda" &&
      aws_sns_topic_subscription.budget.endpoint == aws_lambda_function.this["budget"].arn
    )
    error_message = "The env's budget Lambda subscribes to the budget topic."
  }

  assert {
    condition = (
      aws_lambda_permission.budget_sns.principal == "sns.amazonaws.com" &&
      aws_lambda_permission.budget_sns.source_arn == var.budget_topic_arn &&
      aws_lambda_permission.budget_sns.function_name == aws_lambda_function.this["budget"].function_name
    )
    error_message = "Only the budget topic may invoke the budget Lambda."
  }
}

run "outputs" {
  command = apply

  assert {
    condition = (
      output.api_function_url == aws_lambda_function_url.api.function_url &&
      output.site_bucket == "phoebe-staging-site-123456789012" &&
      output.ops_function_name == "phoebe-staging-ops" &&
      output.cluster_arn == aws_rds_cluster.main.arn &&
      output.db_secret_arn == aws_rds_cluster.main.master_user_secret[0].secret_arn &&
      output.origin_secret_arn == aws_secretsmanager_secret.origin.arn &&
      output.api_role_arn == aws_iam_role.lambda["api"].arn
    )
    error_message = "Outputs for Task 6."
  }
}

run "production" {
  command = apply

  variables {
    env                      = "production"
    password_hash_secret_arn = "arn:aws:secretsmanager:us-east-2:123456789012:secret:phoebe-production-password-hash-XyZ789"
    boundary_policy_arn      = "arn:aws:iam::123456789012:policy/phoebe-boundary-production"
  }

  assert {
    condition     = aws_rds_cluster.main.deletion_protection == true && aws_rds_cluster.main.skip_final_snapshot == false
    error_message = "Production keeps deletion protection and a final snapshot."
  }

  assert {
    condition     = aws_s3_bucket.uploads.bucket == "phoebe-production-uploads-123456789012" && aws_dynamodb_table.state.name == "phoebe-production-state"
    error_message = "Production names use the production prefix."
  }
}

run "rejects_unknown_env" {
  command = plan

  variables {
    env = "dev"
  }

  expect_failures = [var.env]
}

run "rejects_tag_instead_of_api_digest" {
  command = plan

  variables {
    api_image_digest = "latest"
  }

  expect_failures = [var.api_image_digest]
}

run "rejects_tag_instead_of_jobs_digest" {
  command = plan

  variables {
    jobs_image_digest = "abc123-jobs"
  }

  expect_failures = [var.jobs_image_digest]
}

run "rejects_other_envs_password_secret" {
  command = plan

  variables {
    env                 = "production"
    boundary_policy_arn = "arn:aws:iam::123456789012:policy/phoebe-boundary-production"
  }

  expect_failures = [var.password_hash_secret_arn]
}

# R14: a staging role must never carry the production boundary, or vice versa.
run "rejects_other_envs_boundary" {
  command = plan

  variables {
    env                      = "production"
    password_hash_secret_arn = "arn:aws:secretsmanager:us-east-2:123456789012:secret:phoebe-production-password-hash-XyZ789"
  }

  expect_failures = [var.boundary_policy_arn]
}

# A partial ARN (no random suffix) would only fail at GetSecretValue time.
run "rejects_password_secret_without_suffix" {
  command = plan

  variables {
    password_hash_secret_arn = "arn:aws:secretsmanager:us-east-2:123456789012:secret:phoebe-staging-password-hash"
  }

  expect_failures = [var.password_hash_secret_arn]
}

run "edge" {
  command = apply

  # Default behaviour: the private S3 site bucket through OAC, with the SPA/preview router.
  assert {
    condition = (
      aws_cloudfront_distribution.main.default_cache_behavior[0].target_origin_id == "site" &&
      length(aws_cloudfront_distribution.main.default_cache_behavior[0].function_association) == 1 &&
      one(aws_cloudfront_distribution.main.default_cache_behavior[0].function_association).event_type == "viewer-request" &&
      one(aws_cloudfront_distribution.main.default_cache_behavior[0].function_association).function_arn == aws_cloudfront_function.spa_router.arn
    )
    error_message = "The default (S3) behaviour runs the spa_router CloudFront Function on viewer-request."
  }

  assert {
    condition = (
      aws_cloudfront_function.spa_router.runtime == "cloudfront-js-2.0" &&
      aws_cloudfront_function.spa_router.publish == true &&
      aws_cloudfront_function.spa_router.name == "phoebe-staging-spa-router"
    )
    error_message = "spa_router is a published cloudfront-js-2.0 function named phoebe-<env>-spa-router (no Lambda@Edge)."
  }

  assert {
    condition = (
      aws_cloudfront_origin_access_control.site.origin_access_control_origin_type == "s3" &&
      aws_cloudfront_origin_access_control.site.signing_behavior == "always" &&
      aws_cloudfront_origin_access_control.site.signing_protocol == "sigv4" &&
      one([for o in aws_cloudfront_distribution.main.origin : o.origin_access_control_id if o.origin_id == "site"]) == aws_cloudfront_origin_access_control.site.id
    )
    error_message = "The site origin uses a sigv4 S3 origin access control."
  }

  # /api/*: function URL origin, secret header, no cache, all methods, no compression (SSE).
  assert {
    condition     = length(aws_cloudfront_distribution.main.ordered_cache_behavior) == 1 && aws_cloudfront_distribution.main.ordered_cache_behavior[0].path_pattern == "/api/*"
    error_message = "Exactly one ordered behaviour: /api/*."
  }

  assert {
    condition = (
      aws_cloudfront_distribution.main.ordered_cache_behavior[0].target_origin_id == "api" &&
      one([for o in aws_cloudfront_distribution.main.origin : o.domain_name if o.origin_id == "api"]) == trimsuffix(trimprefix(aws_lambda_function_url.api.function_url, "https://"), "/")
    )
    error_message = "/api/* targets the API function URL origin."
  }

  assert {
    condition = (
      length(flatten([for o in aws_cloudfront_distribution.main.origin : [for h in o.custom_header : h] if o.origin_id == "api"])) == 1 &&
      flatten([for o in aws_cloudfront_distribution.main.origin : [for h in o.custom_header : h.name] if o.origin_id == "api"])[0] == "X-Phoebe-Origin" &&
      nonsensitive(flatten([for o in aws_cloudfront_distribution.main.origin : [for h in o.custom_header : h.value] if o.origin_id == "api"])[0]) == nonsensitive(random_password.origin.result)
    )
    error_message = "The API origin sends X-Phoebe-Origin with the origin secret's value."
  }

  assert {
    condition = (
      one([for o in aws_cloudfront_distribution.main.origin : o.custom_origin_config[0].origin_protocol_policy if o.origin_id == "api"]) == "https-only" &&
      !contains(
        flatten(one([for o in aws_cloudfront_distribution.main.origin : o.custom_origin_config[0].origin_ssl_protocols if o.origin_id == "api"])),
        "SSLv3",
      )
    )
    error_message = "The API origin is reached over HTTPS only."
  }

  assert {
    condition = (
      aws_cloudfront_distribution.main.ordered_cache_behavior[0].cache_policy_id == "4135ea2d-6df8-47a0-9b3a-6c3fd7bf9d80" &&
      aws_cloudfront_distribution.main.ordered_cache_behavior[0].origin_request_policy_id == "b689b0a8-53d0-40ab-baf2-68738e2966ac"
    )
    error_message = "/api/* uses the managed CachingDisabled cache policy and AllViewerExceptHostHeader origin request policy."
  }

  assert {
    condition = (
      toset(aws_cloudfront_distribution.main.ordered_cache_behavior[0].allowed_methods) == toset(["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]) &&
      aws_cloudfront_distribution.main.ordered_cache_behavior[0].compress == false
    )
    error_message = "/api/* allows all methods and sets compress = false so SSE is not buffered."
  }

  assert {
    condition     = length(aws_cloudfront_distribution.main.ordered_cache_behavior[0].function_association) == 0
    error_message = "The router must not run on /api/*."
  }

  # Viewer-facing settings.
  assert {
    condition = (
      aws_cloudfront_distribution.main.default_cache_behavior[0].viewer_protocol_policy == "redirect-to-https" &&
      aws_cloudfront_distribution.main.ordered_cache_behavior[0].viewer_protocol_policy == "redirect-to-https"
    )
    error_message = "Every behaviour redirects HTTP to HTTPS."
  }

  assert {
    condition = (
      aws_cloudfront_distribution.main.price_class == "PriceClass_100" &&
      aws_cloudfront_distribution.main.enabled == true &&
      aws_cloudfront_distribution.main.is_ipv6_enabled == true &&
      aws_cloudfront_distribution.main.default_root_object == "index.html"
    )
    error_message = "Enabled, IPv6, PriceClass_100, default root object index.html."
  }

  assert {
    condition = (
      length(coalesce(aws_cloudfront_distribution.main.aliases, [])) == 0 &&
      aws_cloudfront_distribution.main.viewer_certificate[0].cloudfront_default_certificate == true &&
      aws_cloudfront_distribution.main.viewer_certificate[0].acm_certificate_arn == null
    )
    error_message = "No custom domain: no aliases, the default *.cloudfront.net certificate, no ACM."
  }

  assert {
    condition     = aws_cloudfront_distribution.main.logging_config == null || length(aws_cloudfront_distribution.main.logging_config) == 0
    error_message = "No CloudFront access logging (metadata-only logs live in the Lambda)."
  }

  # Security headers on both behaviours.
  assert {
    condition = (
      aws_cloudfront_distribution.main.default_cache_behavior[0].response_headers_policy_id == aws_cloudfront_response_headers_policy.security.id &&
      aws_cloudfront_distribution.main.ordered_cache_behavior[0].response_headers_policy_id == aws_cloudfront_response_headers_policy.security.id
    )
    error_message = "Both behaviours attach the security headers policy."
  }

  assert {
    condition = (
      aws_cloudfront_response_headers_policy.security.security_headers_config[0].content_security_policy[0].content_security_policy == "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'" &&
      aws_cloudfront_response_headers_policy.security.security_headers_config[0].content_security_policy[0].override == true
    )
    error_message = "The CSP is exactly the agreed policy."
  }

  assert {
    condition = (
      aws_cloudfront_response_headers_policy.security.security_headers_config[0].strict_transport_security[0].access_control_max_age_sec == 31536000 &&
      aws_cloudfront_response_headers_policy.security.security_headers_config[0].strict_transport_security[0].override == true &&
      aws_cloudfront_response_headers_policy.security.security_headers_config[0].content_type_options[0].override == true &&
      aws_cloudfront_response_headers_policy.security.security_headers_config[0].referrer_policy[0].referrer_policy == "strict-origin-when-cross-origin" &&
      aws_cloudfront_response_headers_policy.security.security_headers_config[0].referrer_policy[0].override == true
    )
    error_message = "HSTS for one year, nosniff, and Referrer-Policy strict-origin-when-cross-origin."
  }

  # Site bucket policy: only this distribution, via the CloudFront service principal.
  assert {
    condition     = aws_s3_bucket_policy.site.bucket == aws_s3_bucket.site.id
    error_message = "The bucket policy is on the site bucket."
  }

  assert {
    condition = (
      length(jsondecode(aws_s3_bucket_policy.site.policy).Statement) == 1 &&
      jsondecode(aws_s3_bucket_policy.site.policy).Statement[0].Effect == "Allow" &&
      jsondecode(aws_s3_bucket_policy.site.policy).Statement[0].Action == "s3:GetObject" &&
      jsondecode(aws_s3_bucket_policy.site.policy).Statement[0].Principal.Service == "cloudfront.amazonaws.com" &&
      jsondecode(aws_s3_bucket_policy.site.policy).Statement[0].Resource == "${aws_s3_bucket.site.arn}/*" &&
      jsondecode(aws_s3_bucket_policy.site.policy).Statement[0].Condition.StringEquals["AWS:SourceArn"] == aws_cloudfront_distribution.main.arn
    )
    error_message = "The site bucket allows only s3:GetObject to cloudfront.amazonaws.com, scoped to this distribution's ARN."
  }

  assert {
    condition     = output.site_url == "https://${aws_cloudfront_distribution.main.domain_name}"
    error_message = "site_url is https://<distribution>.cloudfront.net."
  }
}
