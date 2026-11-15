data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

locals {
  region     = "us-east-2"
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition

  haiku_profile_id = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
  haiku_model_id   = "anthropic.claude-haiku-4-5-20251001-v1:0"
  nova_profile_id  = "us.amazon.nova-micro-v1:0"
  nova_model_id    = "amazon.nova-micro-v1:0"

  # The `us.` profiles route across these Regions.
  profile_regions = ["us-east-1", "us-east-2", "us-west-2"]

  inference_profile_arns = [
    for id in [local.haiku_profile_id, local.nova_profile_id] :
    "arn:${local.partition}:bedrock:${local.region}:${local.account_id}:inference-profile/${id}"
  ]

  foundation_model_arns = flatten([
    for model in [local.haiku_model_id, local.nova_model_id] : [
      for r in local.profile_regions :
      "arn:${local.partition}:bedrock:${r}::foundation-model/${model}"
    ]
  ])

  answer_prompt = file("${path.module}/../../backend/prompts/answer.txt")
}

# ---- Guardrail --------------------------------------------------------------

resource "aws_bedrock_guardrail" "answers" {
  name                      = "phoebe-answers"
  description               = "Input and output safety filters for Phoebe chat answers."
  blocked_input_messaging   = "Phoebe can't help with that one."
  blocked_outputs_messaging = "Phoebe can't help with that one."

  content_policy_config {
    dynamic "filters_config" {
      for_each = ["HATE", "INSULTS", "SEXUAL", "VIOLENCE", "MISCONDUCT"]
      content {
        type            = filters_config.value
        input_strength  = "MEDIUM"
        output_strength = "MEDIUM"
      }
    }

    # Prompt-attack filtering is input-only; the API requires output NONE.
    filters_config {
      type            = "PROMPT_ATTACK"
      input_strength  = "HIGH"
      output_strength = "NONE"
    }
  }
}

resource "aws_bedrock_guardrail_version" "answers" {
  guardrail_arn = aws_bedrock_guardrail.answers.guardrail_arn
  description   = "Phoebe answers v1"
}

# ---- Execution role (shared by both harnesses) -----------------------------

data "aws_iam_policy_document" "harness_assume_role" {
  statement {
    sid     = "AllowAgentCoreHarness"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${local.partition}:bedrock-agentcore:${local.region}:${local.account_id}:*"]
    }
  }
}

resource "aws_iam_role" "harness_execution" {
  name               = "PhoebeAgentCoreHarnessExecutionRole"
  description        = "Execution role for the Phoebe AgentCore Harnesses"
  assume_role_policy = data.aws_iam_policy_document.harness_assume_role.json
}

data "aws_iam_policy_document" "harness_execution" {
  statement {
    sid    = "InvokeAnswerModels"
    effect = "Allow"

    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
    ]

    resources = concat(
      local.inference_profile_arns,
      local.foundation_model_arns,
    )
  }

  statement {
    sid       = "PullAgentCoreManagedImage"
    effect    = "Allow"
    actions   = ["ecr-public:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid       = "GetECRPublicBearerToken"
    effect    = "Allow"
    actions   = ["sts:GetServiceBearerToken"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "sts:AWSServiceName"
      values   = ["ecr-public.amazonaws.com"]
    }
  }

  statement {
    sid    = "WriteAgentCoreTraces"
    effect = "Allow"

    actions = [
      "xray:PutTraceSegments",
      "xray:PutTelemetryRecords",
      "xray:GetSamplingRules",
      "xray:GetSamplingTargets",
    ]

    resources = ["*"]
  }

  statement {
    sid    = "ManageAgentCoreRuntimeLogs"
    effect = "Allow"

    actions = [
      "logs:CreateLogGroup",
      "logs:DescribeLogStreams",
    ]

    resources = [
      "arn:${local.partition}:logs:${local.region}:${local.account_id}:log-group:/aws/bedrock-agentcore/runtimes/*"
    ]
  }

  statement {
    sid    = "WriteAgentCoreRuntimeLogs"
    effect = "Allow"

    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]

    resources = [
      "arn:${local.partition}:logs:${local.region}:${local.account_id}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*"
    ]
  }

  statement {
    sid       = "DescribeLogGroups"
    effect    = "Allow"
    actions   = ["logs:DescribeLogGroups"]
    resources = ["arn:${local.partition}:logs:${local.region}:${local.account_id}:log-group:*"]
  }

  statement {
    sid       = "PublishAgentCoreMetrics"
    effect    = "Allow"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = ["bedrock-agentcore"]
    }
  }
}

resource "aws_iam_role_policy" "harness_execution" {
  name   = "PhoebeAgentCoreHarnessExecution"
  role   = aws_iam_role.harness_execution.id
  policy = data.aws_iam_policy_document.harness_execution.json
}

# ---- Harnesses --------------------------------------------------------------

resource "aws_bedrockagentcore_harness" "haiku" {
  harness_name          = "PhoebeHaikuHarness"
  execution_role_arn    = aws_iam_role.harness_execution.arn
  environment_variables = {}

  model {
    bedrock_model_config {
      model_id   = local.haiku_profile_id
      api_format = "converse_stream"

      max_tokens  = 700
      temperature = 0.1
    }
  }

  system_prompt {
    text = local.answer_prompt
  }

  max_iterations  = 1
  max_tokens      = 1024
  timeout_seconds = 60

  memory {
    disabled {}
  }

  environment {
    agentcore_runtime_environment {
      lifecycle_configuration {
        idle_runtime_session_timeout = 1800
        max_lifetime                 = 14400
      }

      network_configuration {
        network_mode = "PUBLIC"
      }
    }
  }

  depends_on = [
    aws_iam_role_policy.harness_execution,
  ]
}

resource "aws_bedrockagentcore_harness" "nova" {
  harness_name          = "PhoebeNovaHarness"
  execution_role_arn    = aws_iam_role.harness_execution.arn
  environment_variables = {}

  model {
    bedrock_model_config {
      model_id   = local.nova_profile_id
      api_format = "converse_stream"

      max_tokens  = 700
      temperature = 0.1
    }
  }

  system_prompt {
    text = local.answer_prompt
  }

  max_iterations  = 1
  max_tokens      = 1024
  timeout_seconds = 60

  memory {
    disabled {}
  }

  environment {
    agentcore_runtime_environment {
      lifecycle_configuration {
        idle_runtime_session_timeout = 1800
        max_lifetime                 = 14400
      }

      network_configuration {
        network_mode = "PUBLIC"
      }
    }
  }

  depends_on = [
    aws_iam_role_policy.harness_execution,
  ]
}
