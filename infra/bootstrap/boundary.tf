# Permissions boundaries (ruling R14). Effective permissions are the
# intersection of a role's own policy and its boundary.
#
#   phoebe-boundary-staging     every infra/app role in staging
#   phoebe-boundary-production  every infra/app role in production
#   phoebe-boundary-ci          the phoebe-ci-* roles
#
# An env boundary allows only that env's phoebe-<env>-* data-plane resources,
# so a role a staging deploy creates can never reach production, whatever
# inline policy it is given. Each deploy role may create roles only with its
# own env's boundary.

locals {
  envs = ["staging", "production"]

  boundary_arns = {
    for k in ["staging", "production", "ci"] : k => "arn:aws:iam::${local.account_id}:policy/phoebe-boundary-${k}"
  }

  ci_roles_arn = "arn:aws:iam::${local.account_id}:role/phoebe-ci-*"
  # RDS creates this on the first Aurora cluster in the account.
  rds_slr_arn = "arn:aws:iam::${local.account_id}:role/aws-service-role/rds.amazonaws.com/AWSServiceRoleForRDS"

  # Ruling R24: RDS places the cluster in the default VPC using these reads.
  rds_vpc_read_actions = [
    "ec2:DescribeVpcs", "ec2:DescribeSubnets", "ec2:DescribeSecurityGroups",
    "ec2:DescribeAccountAttributes", "ec2:DescribeAvailabilityZones",
  ]

  # Every IAM verb that changes something.
  iam_write_actions = [
    "iam:Create*", "iam:Put*", "iam:Attach*", "iam:Delete*", "iam:Detach*",
    "iam:Update*", "iam:Tag*", "iam:Untag*", "iam:Add*", "iam:Remove*",
    "iam:Set*", "iam:Upload*", "iam:Change*", "iam:Enable*", "iam:Deactivate*",
    "iam:Reset*", "iam:Resync*", "iam:PassRole",
  ]

  # Global services are exempt. A `us.` inference profile called in us-east-2
  # also authorizes the routed foundation model in the destination Region;
  # bedrock:InferenceProfileArn is set only for that evaluation, so it exempts
  # the routing and nothing else (the profile call itself carries us-east-2).
  region_deny = {
    Sid       = "DenyOtherRegions"
    Effect    = "Deny"
    NotAction = ["cloudfront:*", "iam:*", "sts:*", "budgets:*"]
    Resource  = "*"
    Condition = {
      StringNotEquals = { "aws:RequestedRegion" = ["us-east-2"] }
      ArnNotLike      = { "bedrock:InferenceProfileArn" = "arn:aws:bedrock:us-east-2:${local.account_id}:inference-profile/us.*" }
    }
  }

  org_deny = {
    Sid      = "DenyOrgAndAccount"
    Effect   = "Deny"
    Action   = ["organizations:*", "account:*"]
    Resource = "*"
  }

  # ---- phoebe-boundary-<env>: app roles (Lambdas, scheduler) -------------------

  env_boundary_statements = {
    for env in local.envs : env => [
      {
        Sid    = "EnvData"
        Effect = "Allow"
        Action = ["s3:*", "dynamodb:*", "sqs:*", "rds-data:*", "lambda:InvokeFunction", "logs:CreateLogStream", "logs:PutLogEvents", "secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
        Resource = [
          "arn:aws:s3:::phoebe-${env}-*-${local.account_id}",
          "arn:aws:s3:::phoebe-${env}-*-${local.account_id}/*",
          "arn:aws:dynamodb:${local.region}:${local.account_id}:table/phoebe-${env}-*",
          "arn:aws:sqs:${local.region}:${local.account_id}:phoebe-${env}-*",
          "arn:aws:rds:${local.region}:${local.account_id}:cluster:phoebe-${env}",
          "arn:aws:lambda:${local.region}:${local.account_id}:function:phoebe-${env}-*",
          "arn:aws:logs:${local.region}:${local.account_id}:log-group:/aws/lambda/phoebe-${env}-*",
          "arn:aws:secretsmanager:${local.region}:${local.account_id}:secret:phoebe-${env}-*",
        ]
      },
      {
        # The Aurora master secret's name is rds!cluster-<uuid>, so it is
        # scoped by the cluster tag RDS puts on it. Fail closed: an untagged
        # or differently tagged secret is not allowed. The tag key is not in
        # the AWS docs I could find; Task 9 confirms it with describe-secret,
        # and if it differs the app's first DB call fails loudly.
        Sid      = "EnvDbSecret"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = ["arn:aws:secretsmanager:${local.region}:${local.account_id}:secret:rds!cluster-*"]
        Condition = {
          StringEquals = { "secretsmanager:ResourceTag/aws:rds:primaryDBClusterArn" = "arn:aws:rds:${local.region}:${local.account_id}:cluster:phoebe-${env}" }
        }
      },
      {
        # Shared, env-agnostic AI resources (models, the guardrail, harnesses).
        Sid      = "SharedAi"
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock:Converse", "bedrock:ConverseStream", "bedrock:ApplyGuardrail", "bedrock-agentcore:InvokeHarness", "bedrock-agentcore:InvokeAgentRuntime"]
        Resource = "*"
      },
      local.region_deny,
      local.org_deny,
      {
        Sid         = "DenyIamOutsideEnvRoles"
        Effect      = "Deny"
        Action      = local.iam_write_actions
        NotResource = ["arn:aws:iam::${local.account_id}:role/phoebe-${env}-*"]
      },
    ]
  }

  # ---- phoebe-boundary-ci: the CI roles ---------------------------------------

  ci_boundary_statements = [
    {
      Sid    = "AllowCiServices"
      Effect = "Allow"
      Action = [for s in [
        "cloudfront", "codebuild", "codeconnections", "codestar-connections", "dynamodb",
        "ecr", "iam", "kms", "lambda", "logs", "rds", "s3", "scheduler", "secretsmanager",
        "sns", "sqs", "sts",
      ] : "${s}:*"]
      Resource = "*"
    },
    {
      # Only the five read-only EC2 calls RDS default-VPC placement needs (R24).
      Sid      = "AllowRdsVpcReads"
      Effect   = "Allow"
      Action   = local.rds_vpc_read_actions
      Resource = "*"
    },
    local.region_deny,
    local.org_deny,
    {
      Sid         = "DenyIamOutsideAppRoles"
      Effect      = "Deny"
      Action      = local.iam_write_actions
      NotResource = concat([for env in local.envs : "arn:aws:iam::${local.account_id}:role/phoebe-${env}-*"], [local.rds_slr_arn])
    },
    {
      Sid      = "DenyCiRoleChanges"
      Effect   = "Deny"
      Action   = local.iam_write_actions
      Resource = [local.ci_roles_arn]
    },
    {
      # A role CI creates or edits must carry one of the env boundaries.
      Sid    = "DenyUnboundedRoles"
      Effect = "Deny"
      Action = [
        "iam:CreateRole", "iam:PutRolePermissionsBoundary", "iam:PutRolePolicy",
        "iam:DeleteRolePolicy", "iam:AttachRolePolicy", "iam:DetachRolePolicy",
      ]
      Resource  = "*"
      Condition = { StringNotEquals = { "iam:PermissionsBoundary" = [for env in local.envs : local.boundary_arns[env]] } }
    },
    {
      Sid      = "DenyBoundaryRemoval"
      Effect   = "Deny"
      Action   = ["iam:DeleteRolePermissionsBoundary"]
      Resource = "*"
    },
    {
      # No CI role hops into another role.
      Sid      = "DenyAssumeRole"
      Effect   = "Deny"
      Action   = ["sts:AssumeRole"]
      Resource = "*"
    },
  ]

  boundary_statements = merge(local.env_boundary_statements, { ci = local.ci_boundary_statements })
}

resource "aws_iam_policy" "boundary" {
  for_each = local.boundary_arns

  name        = "phoebe-boundary-${each.key}"
  description = each.key == "ci" ? "Permissions boundary for the phoebe-ci-* roles" : "Permissions boundary for every ${each.key} infra/app role"
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = local.boundary_statements[each.key]
  })
}
