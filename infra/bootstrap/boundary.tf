# phoebe-boundary: the permissions boundary on every role CI creates or runs as
# (the CI roles here and every infra/app role). Effective permissions are the
# intersection of a role's own policy and this one, so it caps what a deploy
# role, or a role a deploy role creates, can ever do.

locals {
  boundary_name = "phoebe-boundary"
  boundary_arn  = "arn:aws:iam::${local.account_id}:policy/${local.boundary_name}"

  phoebe_roles_arn = "arn:aws:iam::${local.account_id}:role/phoebe-*"
  ci_roles_arn     = "arn:aws:iam::${local.account_id}:role/phoebe-ci-*"
  # RDS creates this on the first Aurora cluster in the account.
  rds_slr_arn = "arn:aws:iam::${local.account_id}:role/aws-service-role/rds.amazonaws.com/AWSServiceRoleForRDS"

  # Every IAM verb that changes something.
  iam_write_actions = [
    "iam:Create*", "iam:Put*", "iam:Attach*", "iam:Delete*", "iam:Detach*",
    "iam:Update*", "iam:Tag*", "iam:Untag*", "iam:Add*", "iam:Remove*",
    "iam:Set*", "iam:Upload*", "iam:Change*", "iam:Enable*", "iam:Deactivate*",
    "iam:Reset*", "iam:Resync*", "iam:PassRole",
  ]

  # Services the app's Lambdas and the CI roles use. Anything else is out.
  boundary_services = [
    "bedrock", "bedrock-agentcore", "cloudfront", "codebuild", "codeconnections",
    "codestar-connections", "dynamodb", "ecr", "iam", "kms", "lambda", "logs",
    "rds", "rds-data", "s3", "scheduler", "secretsmanager", "sns", "sqs", "sts",
  ]

  boundary_statements = [
    {
      Sid      = "AllowPhoebeServices"
      Effect   = "Allow"
      Action   = [for s in local.boundary_services : "${s}:*"]
      Resource = "*"
    },
    {
      # Global services are exempt. A `us.` inference profile called in
      # us-east-2 also authorizes the routed foundation model in the
      # destination Region; bedrock:InferenceProfileArn is set only for that
      # evaluation, so it exempts the routing and nothing else (the profile
      # call itself still carries us-east-2).
      Sid       = "DenyOtherRegions"
      Effect    = "Deny"
      NotAction = ["cloudfront:*", "iam:*", "sts:*", "budgets:*"]
      Resource  = "*"
      Condition = {
        StringNotEquals = { "aws:RequestedRegion" = ["us-east-2"] }
        ArnNotLike      = { "bedrock:InferenceProfileArn" = "arn:aws:bedrock:us-east-2:${local.account_id}:inference-profile/us.*" }
      }
    },
    {
      Sid      = "DenyOrgAndAccount"
      Effect   = "Deny"
      Action   = ["organizations:*", "account:*"]
      Resource = "*"
    },
    {
      Sid         = "DenyIamOutsidePhoebeRoles"
      Effect      = "Deny"
      Action      = local.iam_write_actions
      NotResource = [local.phoebe_roles_arn, local.rds_slr_arn]
    },
    {
      Sid      = "DenyCiRoleChanges"
      Effect   = "Deny"
      Action   = local.iam_write_actions
      Resource = [local.ci_roles_arn]
    },
    {
      Sid    = "DenyUnboundedRoles"
      Effect = "Deny"
      Action = [
        "iam:CreateRole", "iam:PutRolePermissionsBoundary", "iam:PutRolePolicy",
        "iam:DeleteRolePolicy", "iam:AttachRolePolicy", "iam:DetachRolePolicy",
      ]
      Resource  = "*"
      Condition = { StringNotEquals = { "iam:PermissionsBoundary" = local.boundary_arn } }
    },
    {
      Sid      = "DenyBoundaryRemoval"
      Effect   = "Deny"
      Action   = ["iam:DeleteRolePermissionsBoundary"]
      Resource = "*"
    },
    {
      # No bounded role hops into another role.
      Sid      = "DenyAssumeRole"
      Effect   = "Deny"
      Action   = ["sts:AssumeRole"]
      Resource = "*"
    },
    {
      # Only CI roles reach state and pipeline artifacts (plans hold secrets).
      Sid    = "DenyDeliveryBucketsToApp"
      Effect = "Deny"
      Action = ["s3:*"]
      Resource = [
        local.state_bucket_arn, "${local.state_bucket_arn}/*",
        local.artifacts_bucket_arn, "${local.artifacts_bucket_arn}/*",
      ]
      Condition = { ArnNotLike = { "aws:PrincipalArn" = local.ci_roles_arn } }
    },
  ]
}

resource "aws_iam_policy" "boundary" {
  name        = local.boundary_name
  description = "Permissions boundary for every Phoebe CI and app role"
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = local.boundary_statements
  })
}
