# CI roles. Policies are plain jsonencode (not aws_iam_policy_document) so the
# offline tests can inspect them under mocks. Every CI role carries
# phoebe-boundary-ci.
#
#   phoebe-ci-plan               phoebe-pr: read-only staging plan + PR preview
#   phoebe-ci-pr-cleanup         phoebe-pr-cleanup: delete one preview, invalidate
#   phoebe-ci-deploy-staging     phoebe-staging: build, push, apply staging
#   phoebe-ci-plan-production    phoebe-release-plan: read-only production plan (before approval)
#   phoebe-ci-deploy-production  phoebe-release-apply: apply the approved plan
#   phoebe-ci-pipeline           the phoebe-release CodePipeline

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

  staging_site_bucket = "phoebe-staging-site-${local.account_id}"

  # CodeBuild clones through the connection (both service prefixes are accepted).
  connection_statement = {
    Sid    = "UseGitHubConnection"
    Effect = "Allow"
    Action = [
      "codeconnections:UseConnection", "codeconnections:GetConnection", "codeconnections:GetConnectionToken",
      "codestar-connections:UseConnection", "codestar-connections:GetConnection", "codestar-connections:GetConnectionToken",
    ]
    Resource = [
      aws_codeconnections_connection.github.arn,
      replace(aws_codeconnections_connection.github.arn, ":codeconnections:", ":codestar-connections:"),
    ]
  }

  # The release Source action hands CodeBuild a CODEBUILD_CLONE_REF
  # (a git clone through the connection), so release-plan can read the tag
  # with git. Only the documented actions: codeconnections UseConnection and
  # GetConnectionToken, plus codestar-connections:UseConnection (CodePipeline
  # "full clone" tutorial).
  release_clone_statement = {
    Sid    = "CloneReleaseSource"
    Effect = "Allow"
    Action = [
      "codeconnections:UseConnection", "codeconnections:GetConnectionToken",
      "codestar-connections:UseConnection",
    ]
    Resource = [
      aws_codeconnections_connection.github.arn,
      replace(aws_codeconnections_connection.github.arn, ":codeconnections:", ":codestar-connections:"),
    ]
  }

  build_logs_statement = {
    for role, projects in {
      "plan"              = ["pr"]
      "pr-cleanup"        = ["pr-cleanup"]
      "deploy-staging"    = ["staging"]
      "plan-production"   = ["release-plan"]
      "deploy-production" = ["release-apply"]
      } : role => {
      Sid      = "OwnBuildLogs"
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = [for p in projects : "${local.arn_prefix.logs}:log-group:/aws/codebuild/phoebe-${p}:*"]
    }
  }

  # infra/ai is owner-applied locally; CI only reads its outputs
  # through terraform_remote_state.
  ai_state_read_statement = {
    Sid      = "AiStateRead"
    Effect   = "Allow"
    Action   = ["s3:GetObject"]
    Resource = ["${local.state_bucket_arn}/ai.tfstate"]
  }

  state_list_statement = {
    Sid      = "StateList"
    Effect   = "Allow"
    Action   = ["s3:ListBucket"]
    Resource = [local.state_bucket_arn]
  }

  # Terraform refresh reads for one env, as the managed policy
  # phoebe-ci-reads-<env> (inline space per role is capped at 10,240 chars). CloudFront and Lambda
  # configs carry the origin secret header and env vars, so those are scoped
  # to the env by tag or name. The account-wide rest is metadata only.
  env_read_statements = {
    for env in local.envs : env => [
      {
        Sid    = "MetadataReads"
        Effect = "Allow"
        Action = [
          "rds:Describe*", "rds:ListTagsForResource",
          "logs:DescribeLogGroups", "logs:ListTagsForResource", "logs:ListTagsLogGroup",
          "secretsmanager:DescribeSecret", "secretsmanager:GetResourcePolicy",
          "iam:GetRole", "iam:GetRolePolicy", "iam:ListRolePolicies", "iam:ListAttachedRolePolicies",
          "ecr:DescribeImages", "ecr:DescribeRepositories",
          "lambda:GetEventSourceMapping", "lambda:ListEventSourceMappings",
        ]
        Resource = "*"
      },
      {
        # Only this env's budget topic and its subscriptions.
        Sid      = "OwnBudgetTopicReads"
        Effect   = "Allow"
        Action   = ["sns:GetTopicAttributes", "sns:ListSubscriptionsByTopic", "sns:ListTagsForResource", "sns:GetSubscriptionAttributes"]
        Resource = [local.budget_topic_arns[env], "${local.budget_topic_arns[env]}:*"]
      },
      {
        Sid    = "EnvResourceReads"
        Effect = "Allow"
        Action = [
          "lambda:Get*", "lambda:List*", "dynamodb:Describe*", "dynamodb:ListTagsOfResource",
          "sqs:GetQueueAttributes", "sqs:GetQueueUrl", "sqs:ListQueueTags",
          "scheduler:GetSchedule", "scheduler:ListTagsForResource",
          "s3:GetBucket*", "s3:GetEncryptionConfiguration", "s3:GetLifecycleConfiguration",
          "s3:GetAccelerateConfiguration", "s3:GetReplicationConfiguration", "s3:ListBucket",
          "cloudfront:GetFunction", "cloudfront:DescribeFunction", "cloudfront:ListTagsForResource",
        ]
        Resource = [
          "${local.arn_prefix.lambda}:function:phoebe-${env}-*",
          "${local.arn_prefix.dynamodb}:table/phoebe-${env}-*",
          "${local.arn_prefix.sqs}:phoebe-${env}-*",
          "${local.arn_prefix.scheduler}:schedule/default/phoebe-${env}-*",
          "arn:aws:s3:::phoebe-${env}-*-${local.account_id}",
          "${local.arn_prefix.cf}:function/phoebe-${env}-*",
        ]
      },
      {
        Sid       = "EnvDistributionReads"
        Effect    = "Allow"
        Action    = ["cloudfront:GetDistribution", "cloudfront:GetDistributionConfig", "cloudfront:GetInvalidation", "cloudfront:ListTagsForResource"]
        Resource  = ["${local.arn_prefix.cf}:distribution/*"]
        Condition = { StringEquals = { "aws:ResourceTag/env" = env } }
      },
      {
        # Mappings have random ids; the refresh reads their tags. Only this env's.
        Sid       = "EnvEventSourceMappingTagReads"
        Effect    = "Allow"
        Action    = ["lambda:ListTags"]
        Resource  = ["${local.arn_prefix.lambda}:event-source-mapping:*"]
        Condition = { StringEquals = { "aws:ResourceTag/env" = env } }
      },
      {
        # Id-only ARNs, no tag keys; these hold no secrets.
        Sid      = "EdgePolicyReads"
        Effect   = "Allow"
        Action   = ["cloudfront:GetOriginAccessControl", "cloudfront:GetOriginAccessControlConfig", "cloudfront:GetResponseHeadersPolicy", "cloudfront:GetResponseHeadersPolicyConfig"]
        Resource = ["${local.arn_prefix.cf}:origin-access-control/*", "${local.arn_prefix.cf}:response-headers-policy/*"]
      },
      {
        # aws_secretsmanager_secret_version refresh reads the value.
        Sid      = "OriginSecretRead"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = ["${local.arn_prefix.secrets}:secret:phoebe-${env}-origin-secret-*"]
      },
      local.state_list_statement,
      local.ai_state_read_statement,
    ]
  }

  invalidate_staging_statement = {
    # The distribution id is unknown here; infra/app tags it env=staging.
    Sid       = "InvalidateStaging"
    Effect    = "Allow"
    Action    = ["cloudfront:CreateInvalidation"]
    Resource  = ["${local.arn_prefix.cf}:distribution/*"]
    Condition = { StringEquals = { "aws:ResourceTag/env" = "staging" } }
  }

  # ---- phoebe-ci-plan (phoebe-pr) -------------------------------------------------

  plan_statements = [
    local.build_logs_statement["plan"],
    local.connection_statement,
    {
      # Plans run with -lock=false: no lock object is written.
      Sid      = "StateRead"
      Effect   = "Allow"
      Action   = ["s3:GetObject"]
      Resource = ["${local.state_bucket_arn}/app/staging.tfstate"]
    },
    {
      Sid      = "PreviewObjects"
      Effect   = "Allow"
      Action   = ["s3:PutObject", "s3:DeleteObject"]
      Resource = ["arn:aws:s3:::${local.staging_site_bucket}/previews/*"]
    },
    local.invalidate_staging_statement,
  ]

  # ---- phoebe-ci-pr-cleanup ------------------------------------------------------
  # Its buildspec is inline (no repo code runs); it clones only because a
  # webhook needs a GitHub source. No state, no secrets.

  pr_cleanup_statements = [
    local.build_logs_statement["pr-cleanup"],
    local.connection_statement,
    {
      Sid       = "ListPreviews"
      Effect    = "Allow"
      Action    = ["s3:ListBucket"]
      Resource  = ["arn:aws:s3:::${local.staging_site_bucket}"]
      Condition = { StringLike = { "s3:prefix" = ["previews/pr-*"] } }
    },
    {
      Sid      = "DeletePreviews"
      Effect   = "Allow"
      Action   = ["s3:DeleteObject"]
      Resource = ["arn:aws:s3:::${local.staging_site_bucket}/previews/*"]
    },
    local.invalidate_staging_statement,
  ]

  # ---- phoebe-ci-plan-production (phoebe-release-plan, before approval) ----------

  artifacts_bucket_statement = {
    Sid      = "PipelineArtifactsBucket"
    Effect   = "Allow"
    Action   = ["s3:GetBucketAcl", "s3:GetBucketLocation"]
    Resource = [local.artifacts_bucket_arn]
  }

  plan_production_statements = [
    local.build_logs_statement["plan-production"],
    local.release_clone_statement,
    {
      # Plans run with -lock=false; the saved plan is only applied after approval.
      Sid      = "StateRead"
      Effect   = "Allow"
      Action   = ["s3:GetObject"]
      Resource = ["${local.state_bucket_arn}/app/production.tfstate"]
    },
    {
      # Source zip in, saved plan out.
      Sid      = "PipelineArtifacts"
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:PutObject"]
      Resource = ["${local.artifacts_bucket_arn}/*"]
    },
    local.artifacts_bucket_statement,
    {
      # Resolve phoebe-api:<sha> and <sha>-jobs to digests.
      Sid      = "ResolveImages"
      Effect   = "Allow"
      Action   = ["ecr:BatchGetImage"]
      Resource = [aws_ecr_repository.api.arn]
    },
  ]

  # ---- phoebe-ci-deploy-<env> ------------------------------------------------------

  deploy_statements = {
    for env in local.envs : env => concat(
      [
        local.build_logs_statement["deploy-${env}"],
        {
          Sid      = "StateReadWrite"
          Effect   = "Allow"
          Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
          Resource = ["${local.state_bucket_arn}/app/${env}.tfstate", "${local.state_bucket_arn}/app/${env}.tfstate.tflock"]
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
          # manage_master_user_password: RDS creates rds!cluster-<uuid> as the
          # caller, which needs exactly kms:DescribeKey, CreateSecret and
          # TagResource (Aurora user guide). No RotateSecret. TagResource cannot
          # forge the aws:rds:* tags the env boundary keys on: aws:-prefixed
          # tag keys are reserved for AWS.
          Sid      = "RdsManagedSecret"
          Effect   = "Allow"
          Action   = ["secretsmanager:CreateSecret", "secretsmanager:TagResource"]
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
          Action   = ["s3:CreateBucket", "s3:DeleteBucket", "s3:PutBucket*", "s3:DeleteBucketPolicy", "s3:PutEncryptionConfiguration", "s3:PutLifecycleConfiguration"]
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
          # CreateEventSourceMapping supports no resource ARN (the
          # mapping has none yet), so it is granted on "*", still limited to
          # this env's functions by lambda:FunctionArn.
          Sid       = "CreateEventSourceMappings"
          Effect    = "Allow"
          Action    = ["lambda:CreateEventSourceMapping"]
          Resource  = "*"
          Condition = { ArnLike = { "lambda:FunctionArn" = "${local.arn_prefix.lambda}:function:phoebe-${env}-*" } }
        },
        {
          Sid       = "EventSourceMappings"
          Effect    = "Allow"
          Action    = ["lambda:UpdateEventSourceMapping", "lambda:DeleteEventSourceMapping", "lambda:TagResource", "lambda:UntagResource"]
          Resource  = ["${local.arn_prefix.lambda}:event-source-mapping:*"]
          Condition = { ArnLike = { "lambda:FunctionArn" = "${local.arn_prefix.lambda}:function:phoebe-${env}-*" } }
        },
        {
          # CreateEventSourceMapping with tags also authorizes lambda:TagResource
          # on event-source-mapping:*, where lambda:FunctionArn is absent. Allow
          # it only when the request tags the mapping with this env (default_tags),
          # only with the default_tags keys, and never on a mapping already
          # tagged for another env (a new mapping has no resource tags yet).
          Sid      = "TagNewEventSourceMappings"
          Effect   = "Allow"
          Action   = ["lambda:TagResource"]
          Resource = ["${local.arn_prefix.lambda}:event-source-mapping:*"]
          Condition = {
            StringEquals                = { "aws:RequestTag/env" = env }
            StringEqualsIfExists        = { "aws:ResourceTag/env" = env }
            "ForAllValues:StringEquals" = { "aws:TagKeys" = ["project", "env"] }
          }
        },
        {
          # CreateDBCluster/Instance with no subnet group places the
          # cluster in the default VPC, which RDS resolves with the caller's ec2
          # describes. Read-only; EC2 describes support no resource scoping.
          Sid      = "RdsDefaultVpcReads"
          Effect   = "Allow"
          Action   = local.rds_vpc_read_actions
          Resource = "*"
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
          Action   = ["secretsmanager:CreateSecret", "secretsmanager:DeleteSecret", "secretsmanager:PutSecretValue", "secretsmanager:UpdateSecret", "secretsmanager:TagResource", "secretsmanager:UntagResource"]
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
          # Subscribe only this env's budget Lambda to this env's topic.
          Sid      = "BudgetSubscribe"
          Effect   = "Allow"
          Action   = ["sns:Subscribe"]
          Resource = [local.budget_topic_arns[env]]
          Condition = {
            StringEquals = {
              "sns:Endpoint" = "${local.arn_prefix.lambda}:function:phoebe-${env}-budget"
              "sns:Protocol" = "lambda"
            }
          }
        },
        {
          Sid      = "BudgetUnsubscribe"
          Effect   = "Allow"
          Action   = ["sns:Unsubscribe"]
          Resource = ["${local.budget_topic_arns[env]}:*"]
        },
        {
          # "*" in an ARN crosses "/", so role/phoebe-<env>-* would also match a
          # role under the path /phoebe-<env>-x/. Role names cannot contain
          # "/", so any ARN with two "/" is pathed: refuse it.
          Sid      = "DenyPathedRoles"
          Effect   = "Deny"
          Action   = ["iam:CreateRole"]
          Resource = ["${local.arn_prefix.iam}:role/*/*"]
        },
        {
          Sid       = "CreateBoundedRoles"
          Effect    = "Allow"
          Action    = ["iam:CreateRole", "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:PutRolePermissionsBoundary"]
          Resource  = ["${local.arn_prefix.iam}:role/phoebe-${env}-*"]
          Condition = { StringEquals = { "iam:PermissionsBoundary" = local.boundary_arns[env] } }
        },
        {
          # UpdateAssumeRolePolicy is accepted: see README ("Accepted risks").
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
      local.release_clone_statement,
      {
        # Approved saved plan and source in; nothing written back.
        Sid      = "PipelineArtifacts"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = ["${local.artifacts_bucket_arn}/*"]
      },
      local.artifacts_bucket_statement,
      {
        # Add release-<git tag> / release-<git tag>-jobs to the
        # promoted digests (BatchGetImage reads the manifest, PutImage re-puts
        # it under the new tag; IMMUTABLE only forbids moving an existing tag).
        Sid      = "TagReleaseImages"
        Effect   = "Allow"
        Action   = ["ecr:PutImage"]
        Resource = [aws_ecr_repository.api.arn]
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
      description = "Read-only staging plan and PR previews (phoebe-pr)"
      service     = "codebuild.amazonaws.com"
      projects    = ["pr"]
      statements  = local.plan_statements
    }
    "pr-cleanup" = {
      description = "Deletes a closed PR's preview (phoebe-pr-cleanup, inline buildspec)"
      service     = "codebuild.amazonaws.com"
      projects    = ["pr-cleanup"]
      statements  = local.pr_cleanup_statements
    }
    "deploy-staging" = {
      description = "Builds, pushes and deploys staging (phoebe-staging)"
      service     = "codebuild.amazonaws.com"
      projects    = ["staging"]
      statements  = local.deploy_statements["staging"]
    }
    "plan-production" = {
      description = "Read-only production plan before approval (phoebe-release-plan)"
      service     = "codebuild.amazonaws.com"
      projects    = ["release-plan"]
      statements  = local.plan_production_statements
    }
    "deploy-production" = {
      description = "Applies the approved production plan by digest (phoebe-release-apply)"
      service     = "codebuild.amazonaws.com"
      projects    = ["release-apply"]
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
  permissions_boundary = aws_iam_policy.boundary["ci"].arn

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

resource "aws_iam_policy" "ci_reads" {
  for_each = toset(local.envs)

  name        = "phoebe-ci-reads-${each.key}"
  description = "Terraform refresh reads for ${each.key}, scoped to phoebe-${each.key}-* where config carries secrets"
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = local.env_read_statements[each.key]
  })
}

# Which CI roles read which env.
resource "aws_iam_role_policy_attachment" "ci_reads" {
  for_each = {
    "plan"              = "staging"
    "deploy-staging"    = "staging"
    "plan-production"   = "production"
    "deploy-production" = "production"
  }

  role       = aws_iam_role.ci[each.key].name
  policy_arn = aws_iam_policy.ci_reads[each.value].arn
}
