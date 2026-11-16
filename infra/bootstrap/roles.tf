# CI roles. Policies are plain jsonencode (not aws_iam_policy_document) so the
# offline tests can inspect them under mocks. Every role carries the boundary.
#
#   phoebe-ci-plan              phoebe-pr, phoebe-pr-cleanup (read-only + previews)
#   phoebe-ci-deploy-staging    phoebe-staging (build, push, apply staging)
#   phoebe-ci-deploy-production phoebe-release-plan, phoebe-release-apply
#   phoebe-ci-pipeline          the phoebe-release CodePipeline

locals {
  arn_prefix = {
    lambda    = "arn:aws:lambda:${local.region}:${local.account_id}"
    logs      = "arn:aws:logs:${local.region}:${local.account_id}"
    rds       = "arn:aws:rds:${local.region}:${local.account_id}"
    dynamodb  = "arn:aws:dynamodb:${local.region}:${local.account_id}"
    sqs       = "arn:aws:sqs:${local.region}:${local.account_id}"
    secrets   = "arn:aws:secretsmanager:${local.region}:${local.account_id}"
    scheduler = "arn:aws:scheduler:${local.region}:${local.account_id}"
    iam       = "arn:aws:iam::${local.account_id}"
    cf        = "arn:aws:cloudfront::${local.account_id}"
  }

  connection_arns = [
    aws_codeconnections_connection.github.arn,
    replace(aws_codeconnections_connection.github.arn, ":codeconnections:", ":codestar-connections:"),
  ]

  # CodeBuild clones through the connection (both service prefixes are accepted).
  connection_statement = {
    Sid    = "UseGitHubConnection"
    Effect = "Allow"
    Action = [
      "codeconnections:UseConnection", "codeconnections:GetConnection", "codeconnections:GetConnectionToken",
      "codestar-connections:UseConnection", "codestar-connections:GetConnection", "codestar-connections:GetConnectionToken",
    ]
    Resource = local.connection_arns
  }

  build_logs_statement = {
    for role, projects in {
      "plan"              = ["pr", "pr-cleanup"]
      "deploy-staging"    = ["staging"]
      "deploy-production" = ["release-plan", "release-apply"]
      } : role => {
      Sid      = "OwnBuildLogs"
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = [for p in projects : "${local.arn_prefix.logs}:log-group:/aws/codebuild/phoebe-${p}:*"]
    }
  }

  state_keys = {
    staging    = ["app/staging.tfstate", "ai.tfstate"] # staging also applies infra/ai
    production = ["app/production.tfstate"]
  }

  # Metadata reads Terraform refresh needs. Resource "*" because most of these
  # actions are not resource-scopable; none of them return data-plane content
  # (no dynamodb:GetItem, no s3:GetObject, no secret values).
  read_statement = {
    Sid    = "RefreshReads"
    Effect = "Allow"
    Action = [
      "rds:Describe*", "rds:ListTagsForResource",
      "dynamodb:Describe*", "dynamodb:ListTagsOfResource",
      "sqs:GetQueueAttributes", "sqs:GetQueueUrl", "sqs:ListQueueTags",
      "lambda:GetFunction*", "lambda:GetPolicy", "lambda:GetEventSourceMapping",
      "lambda:List*",
      "logs:DescribeLogGroups", "logs:ListTagsForResource", "logs:ListTagsLogGroup",
      "cloudfront:Get*", "cloudfront:List*", "cloudfront:DescribeFunction",
      "scheduler:GetSchedule", "scheduler:ListTagsForResource",
      "secretsmanager:DescribeSecret", "secretsmanager:GetResourcePolicy",
      "iam:GetRole", "iam:GetRolePolicy", "iam:ListRolePolicies", "iam:ListAttachedRolePolicies",
      "iam:GetPolicy", "iam:GetPolicyVersion",
      "sns:GetTopicAttributes", "sns:GetSubscriptionAttributes", "sns:ListSubscriptionsByTopic",
      "ecr:DescribeImages", "ecr:DescribeRepositories",
    ]
    Resource = "*"
  }

  # infra/ai refresh (the staging build re-applies the shared root; any real
  # change there is owner-applied, see README).
  ai_read_statement = {
    Sid      = "AiRootReads"
    Effect   = "Allow"
    Action   = ["bedrock:GetGuardrail", "bedrock:ListTagsForResource", "bedrock-agentcore:Get*", "bedrock-agentcore:List*"]
    Resource = "*"
  }

  # ---- phoebe-ci-plan --------------------------------------------------------

  plan_statements = [
    local.build_logs_statement["plan"],
    local.connection_statement,
    local.read_statement,
    {
      Sid      = "StateList"
      Effect   = "Allow"
      Action   = ["s3:ListBucket"]
      Resource = [local.state_bucket_arn]
    },
    {
      # Plans run with -lock=false: no lock object is written.
      Sid      = "StateRead"
      Effect   = "Allow"
      Action   = ["s3:GetObject"]
      Resource = [for k in local.state_keys.staging : "${local.state_bucket_arn}/${k}"]
    },
    {
      Sid      = "StagingBucketMetadata"
      Effect   = "Allow"
      Action   = ["s3:GetBucket*", "s3:GetEncryptionConfiguration", "s3:GetLifecycleConfiguration", "s3:GetAccelerateConfiguration", "s3:GetReplicationConfiguration", "s3:ListBucket"]
      Resource = ["arn:aws:s3:::phoebe-staging-*-${local.account_id}"]
    },
    {
      # aws_secretsmanager_secret_version refresh reads the value.
      Sid      = "StagingOriginSecret"
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = ["${local.arn_prefix.secrets}:secret:phoebe-staging-origin-secret-*"]
    },
    {
      Sid      = "PreviewObjects"
      Effect   = "Allow"
      Action   = ["s3:PutObject", "s3:DeleteObject"]
      Resource = ["arn:aws:s3:::phoebe-staging-site-${local.account_id}/previews/*"]
    },
    {
      # The distribution id is unknown here; infra/app tags it env=staging.
      Sid       = "InvalidateStaging"
      Effect    = "Allow"
      Action    = ["cloudfront:CreateInvalidation"]
      Resource  = ["${local.arn_prefix.cf}:distribution/*"]
      Condition = { StringEquals = { "aws:ResourceTag/env" = "staging" } }
    },
  ]

  # ---- phoebe-ci-deploy-<env> -------------------------------------------------

  deploy_statements = {
    for env in ["staging", "production"] : env => concat(
      [
        local.build_logs_statement["deploy-${env}"],
        local.read_statement,
        {
          Sid      = "StateList"
          Effect   = "Allow"
          Action   = ["s3:ListBucket"]
          Resource = [local.state_bucket_arn]
        },
        {
          Sid    = "StateReadWrite"
          Effect = "Allow"
          Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
          Resource = flatten([
            for k in local.state_keys[env] : ["${local.state_bucket_arn}/${k}", "${local.state_bucket_arn}/${k}.tflock"]
          ])
        },
        {
          Sid      = "Rds"
          Effect   = "Allow"
          Action   = ["rds:CreateDBCluster", "rds:ModifyDBCluster", "rds:DeleteDBCluster", "rds:CreateDBInstance", "rds:ModifyDBInstance", "rds:DeleteDBInstance", "rds:CreateDBClusterSnapshot", "rds:EnableHttpEndpoint", "rds:DisableHttpEndpoint", "rds:AddTagsToResource", "rds:RemoveTagsFromResource"]
          Resource = ["${local.arn_prefix.rds}:cluster:phoebe-${env}", "${local.arn_prefix.rds}:db:phoebe-${env}-*", "${local.arn_prefix.rds}:cluster-snapshot:phoebe-${env}-*", "${local.arn_prefix.rds}:subgrp:default", "${local.arn_prefix.rds}:cluster-pg:default.*", "${local.arn_prefix.rds}:pg:default.*", "${local.arn_prefix.rds}:og:default:*"]
        },
        {
          Sid       = "RdsServiceLinkedRole"
          Effect    = "Allow"
          Action    = ["iam:CreateServiceLinkedRole"]
          Resource  = [local.rds_slr_arn]
          Condition = { StringEquals = { "iam:AWSServiceName" = "rds.amazonaws.com" } }
        },
        {
          # manage_master_user_password: RDS creates rds!cluster-<uuid> as the caller.
          Sid      = "RdsManagedSecret"
          Effect   = "Allow"
          Action   = ["secretsmanager:CreateSecret", "secretsmanager:TagResource", "secretsmanager:RotateSecret"]
          Resource = ["${local.arn_prefix.secrets}:secret:rds!cluster-*"]
        },
        {
          Sid       = "AwsManagedKeysViaServices"
          Effect    = "Allow"
          Action    = ["kms:DescribeKey", "kms:CreateGrant"]
          Resource  = "*"
          Condition = { StringEquals = { "kms:ViaService" = ["rds.${local.region}.amazonaws.com", "secretsmanager.${local.region}.amazonaws.com"] } }
        },
        {
          Sid      = "DynamoDb"
          Effect   = "Allow"
          Action   = ["dynamodb:CreateTable", "dynamodb:DeleteTable", "dynamodb:UpdateTable", "dynamodb:UpdateTimeToLive", "dynamodb:UpdateContinuousBackups", "dynamodb:TagResource", "dynamodb:UntagResource"]
          Resource = ["${local.arn_prefix.dynamodb}:table/phoebe-${env}-*"]
        },
        {
          Sid      = "Sqs"
          Effect   = "Allow"
          Action   = ["sqs:CreateQueue", "sqs:DeleteQueue", "sqs:SetQueueAttributes", "sqs:TagQueue", "sqs:UntagQueue"]
          Resource = ["${local.arn_prefix.sqs}:phoebe-${env}-*"]
        },
        {
          Sid      = "Buckets"
          Effect   = "Allow"
          Action   = ["s3:CreateBucket", "s3:DeleteBucket", "s3:PutBucket*", "s3:DeleteBucketPolicy", "s3:PutEncryptionConfiguration", "s3:PutLifecycleConfiguration", "s3:GetBucket*", "s3:GetEncryptionConfiguration", "s3:GetLifecycleConfiguration", "s3:GetAccelerateConfiguration", "s3:GetReplicationConfiguration", "s3:ListBucket"]
          Resource = ["arn:aws:s3:::phoebe-${env}-*-${local.account_id}"]
        },
        {
          Sid      = "SiteObjects"
          Effect   = "Allow"
          Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
          Resource = ["arn:aws:s3:::phoebe-${env}-site-${local.account_id}/*"]
        },
        {
          Sid      = "Functions"
          Effect   = "Allow"
          Action   = ["lambda:CreateFunction", "lambda:DeleteFunction", "lambda:UpdateFunctionCode", "lambda:UpdateFunctionConfiguration", "lambda:PublishVersion", "lambda:CreateFunctionUrlConfig", "lambda:UpdateFunctionUrlConfig", "lambda:DeleteFunctionUrlConfig", "lambda:PutFunctionConcurrency", "lambda:DeleteFunctionConcurrency", "lambda:AddPermission", "lambda:RemovePermission", "lambda:TagResource", "lambda:UntagResource"]
          Resource = ["${local.arn_prefix.lambda}:function:phoebe-${env}-*"]
        },
        {
          Sid       = "EventSourceMappings"
          Effect    = "Allow"
          Action    = ["lambda:CreateEventSourceMapping", "lambda:UpdateEventSourceMapping", "lambda:DeleteEventSourceMapping", "lambda:TagResource", "lambda:UntagResource"]
          Resource  = ["${local.arn_prefix.lambda}:event-source-mapping:*"]
          Condition = { ArnLike = { "lambda:FunctionArn" = "${local.arn_prefix.lambda}:function:phoebe-${env}-*" } }
        },
        {
          Sid      = "InvokeOps"
          Effect   = "Allow"
          Action   = ["lambda:InvokeFunction"]
          Resource = ["${local.arn_prefix.lambda}:function:phoebe-${env}-ops"]
        },
        {
          Sid      = "LambdaLogGroups"
          Effect   = "Allow"
          Action   = ["logs:CreateLogGroup", "logs:DeleteLogGroup", "logs:PutRetentionPolicy", "logs:DeleteRetentionPolicy", "logs:TagResource", "logs:UntagResource", "logs:TagLogGroup", "logs:UntagLogGroup"]
          Resource = ["${local.arn_prefix.logs}:log-group:/aws/lambda/phoebe-${env}-*"]
        },
        {
          Sid      = "OriginSecret"
          Effect   = "Allow"
          Action   = ["secretsmanager:CreateSecret", "secretsmanager:DeleteSecret", "secretsmanager:PutSecretValue", "secretsmanager:UpdateSecret", "secretsmanager:GetSecretValue", "secretsmanager:TagResource", "secretsmanager:UntagResource"]
          Resource = ["${local.arn_prefix.secrets}:secret:phoebe-${env}-origin-secret-*"]
        },
        {
          # Distribution ids are unknown, so writes key on the env tag that
          # infra/app's default_tags set. IfExists lets the create (no tag yet) through.
          Sid      = "Distribution"
          Effect   = "Allow"
          Action   = ["cloudfront:CreateDistribution", "cloudfront:UpdateDistribution", "cloudfront:DeleteDistribution", "cloudfront:CreateInvalidation", "cloudfront:TagResource", "cloudfront:UntagResource"]
          Resource = ["${local.arn_prefix.cf}:distribution/*"]
          Condition = {
            StringEqualsIfExists = { "aws:ResourceTag/env" = env, "aws:RequestTag/env" = env }
          }
        },
        {
          Sid      = "EdgeFunction"
          Effect   = "Allow"
          Action   = ["cloudfront:CreateFunction", "cloudfront:UpdateFunction", "cloudfront:DeleteFunction", "cloudfront:PublishFunction", "cloudfront:TagResource", "cloudfront:UntagResource"]
          Resource = ["${local.arn_prefix.cf}:function/phoebe-${env}-*"]
        },
        {
          # OAC and response-headers policies have id-only ARNs and no tag keys.
          Sid      = "EdgePolicies"
          Effect   = "Allow"
          Action   = ["cloudfront:CreateOriginAccessControl", "cloudfront:UpdateOriginAccessControl", "cloudfront:DeleteOriginAccessControl", "cloudfront:CreateResponseHeadersPolicy", "cloudfront:UpdateResponseHeadersPolicy", "cloudfront:DeleteResponseHeadersPolicy"]
          Resource = ["${local.arn_prefix.cf}:origin-access-control/*", "${local.arn_prefix.cf}:response-headers-policy/*"]
        },
        {
          Sid      = "Schedule"
          Effect   = "Allow"
          Action   = ["scheduler:CreateSchedule", "scheduler:UpdateSchedule", "scheduler:DeleteSchedule", "scheduler:TagResource", "scheduler:UntagResource"]
          Resource = ["${local.arn_prefix.scheduler}:schedule/default/phoebe-${env}-*"]
        },
        {
          Sid      = "BudgetSubscription"
          Effect   = "Allow"
          Action   = ["sns:Subscribe", "sns:Unsubscribe", "sns:SetSubscriptionAttributes"]
          Resource = [aws_sns_topic.budget.arn, "${aws_sns_topic.budget.arn}:*"]
        },
        {
          Sid       = "CreateBoundedRoles"
          Effect    = "Allow"
          Action    = ["iam:CreateRole", "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:PutRolePermissionsBoundary"]
          Resource  = ["${local.arn_prefix.iam}:role/phoebe-${env}-*"]
          Condition = { StringEquals = { "iam:PermissionsBoundary" = local.boundary_arn } }
        },
        {
          Sid      = "ManageRoles"
          Effect   = "Allow"
          Action   = ["iam:DeleteRole", "iam:UpdateRole", "iam:UpdateRoleDescription", "iam:UpdateAssumeRolePolicy", "iam:TagRole", "iam:UntagRole", "iam:ListInstanceProfilesForRole"]
          Resource = ["${local.arn_prefix.iam}:role/phoebe-${env}-*"]
        },
        {
          Sid       = "PassAppRoles"
          Effect    = "Allow"
          Action    = ["iam:PassRole"]
          Resource  = ["${local.arn_prefix.iam}:role/phoebe-${env}-*"]
          Condition = { StringEquals = { "iam:PassedToService" = ["lambda.amazonaws.com", "scheduler.amazonaws.com"] } }
        },
        {
          # Lambda checks the creator can pull the image it pins.
          Sid      = "PullImages"
          Effect   = "Allow"
          Action   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
          Resource = [aws_ecr_repository.api.arn]
        },
      ],
      [for st in local.deploy_extra_statements.staging : st if env == "staging"],
      [for st in local.deploy_extra_statements.production : st if env == "production"],
    )
  }

  # Statements only one deploy role gets.
  deploy_extra_statements = {
    staging = [
      local.connection_statement,
      local.ai_read_statement,
      {
        Sid      = "EcrLogin"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Sid      = "PushImages"
        Effect   = "Allow"
        Action   = ["ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage"]
        Resource = [aws_ecr_repository.api.arn]
      },
    ]
    production = [
      {
        # Release: source zip in, saved plan out, saved plan back in.
        Sid      = "PipelineArtifacts"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject"]
        Resource = ["${local.artifacts_bucket_arn}/*"]
      },
      {
        Sid      = "PipelineArtifactsBucket"
        Effect   = "Allow"
        Action   = ["s3:GetBucketAcl", "s3:GetBucketLocation"]
        Resource = [local.artifacts_bucket_arn]
      },
      {
        Sid      = "AiStateRead"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = ["${local.state_bucket_arn}/ai.tfstate"]
      },
    ]
  }

  # ---- phoebe-ci-pipeline -------------------------------------------------------

  pipeline_statements = [
    local.connection_statement,
    {
      Sid      = "Artifacts"
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:GetObjectVersion", "s3:PutObject"]
      Resource = ["${local.artifacts_bucket_arn}/*"]
    },
    {
      Sid      = "ArtifactsBucket"
      Effect   = "Allow"
      Action   = ["s3:GetBucketVersioning", "s3:GetBucketLocation", "s3:ListBucket"]
      Resource = [local.artifacts_bucket_arn]
    },
    {
      Sid      = "RunReleaseBuilds"
      Effect   = "Allow"
      Action   = ["codebuild:StartBuild", "codebuild:BatchGetBuilds"]
      Resource = [for k in ["release-plan", "release-apply"] : "arn:aws:codebuild:${local.region}:${local.account_id}:project/phoebe-${k}"]
    },
  ]

  ci_roles = {
    "plan" = {
      description = "Read-only plans and PR previews (phoebe-pr, phoebe-pr-cleanup)"
      service     = "codebuild.amazonaws.com"
      projects    = ["pr", "pr-cleanup"]
      statements  = local.plan_statements
    }
    "deploy-staging" = {
      description = "Builds, pushes and deploys staging (phoebe-staging)"
      service     = "codebuild.amazonaws.com"
      projects    = ["staging"]
      statements  = local.deploy_statements["staging"]
    }
    "deploy-production" = {
      description = "Plans and applies production by digest (phoebe-release-plan, phoebe-release-apply)"
      service     = "codebuild.amazonaws.com"
      projects    = ["release-plan", "release-apply"]
      statements  = local.deploy_statements["production"]
    }
    "pipeline" = {
      description = "Runs the phoebe-release CodePipeline"
      service     = "codepipeline.amazonaws.com"
      projects    = []
      statements  = local.pipeline_statements
    }
  }
}

resource "aws_iam_role" "ci" {
  for_each = local.ci_roles

  name                 = "phoebe-ci-${each.key}"
  description          = each.value.description
  permissions_boundary = aws_iam_policy.boundary.arn

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = each.value.service }
      Condition = merge(
        { StringEquals = { "aws:SourceAccount" = local.account_id } },
        length(each.value.projects) > 0 ? {
          ArnLike = { "aws:SourceArn" = [for p in each.value.projects : "arn:aws:codebuild:${local.region}:${local.account_id}:project/phoebe-${p}"] }
        } : {},
      )
    }]
  })
}

resource "aws_iam_role_policy" "ci" {
  for_each = local.ci_roles

  name = "phoebe-ci-${each.key}"
  role = aws_iam_role.ci[each.key].id

  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = each.value.statements
  })
}
