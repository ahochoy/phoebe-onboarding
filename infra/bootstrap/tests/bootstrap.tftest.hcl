# Offline: every AWS call is mocked. The account id and the ARNs that the
# code compares against are overridden so they look real.

mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
    }
  }

  mock_resource "aws_s3_bucket" {
    defaults = {
      arn = "arn:aws:s3:::phoebe-mock"
    }
  }

  mock_resource "aws_cloudwatch_log_group" {
    defaults = {
      arn = "arn:aws:logs:us-east-2:123456789012:log-group:/aws/codebuild/phoebe-mock"
    }
  }

  mock_resource "aws_ecr_repository" {
    defaults = {
      arn            = "arn:aws:ecr:us-east-2:123456789012:repository/phoebe-api"
      repository_url = "123456789012.dkr.ecr.us-east-2.amazonaws.com/phoebe-api"
    }
  }

  mock_resource "aws_codebuild_project" {
    defaults = {
      arn = "arn:aws:codebuild:us-east-2:123456789012:project/phoebe-mock"
    }
  }

  mock_resource "aws_codepipeline" {
    defaults = {
      arn = "arn:aws:codepipeline:us-east-2:123456789012:phoebe-release"
    }
  }
}

override_resource {
  target = aws_iam_policy.boundary
  values = {
    arn = "arn:aws:iam::123456789012:policy/phoebe-boundary"
  }
}

override_resource {
  target = aws_codeconnections_connection.github
  values = {
    arn               = "arn:aws:codeconnections:us-east-2:123456789012:connection/00000000-0000-0000-0000-000000000000"
    connection_status = "PENDING"
  }
}

override_resource {
  target = aws_sns_topic.budget
  values = {
    arn = "arn:aws:sns:us-east-2:123456789012:phoebe-budget"
  }
}

# Distinct role ARNs so "project X uses role Y" is a real check.
override_resource {
  target = aws_iam_role.ci["plan"]
  values = {
    arn = "arn:aws:iam::123456789012:role/phoebe-ci-plan"
  }
}

override_resource {
  target = aws_iam_role.ci["deploy-staging"]
  values = {
    arn = "arn:aws:iam::123456789012:role/phoebe-ci-deploy-staging"
  }
}

override_resource {
  target = aws_iam_role.ci["deploy-production"]
  values = {
    arn = "arn:aws:iam::123456789012:role/phoebe-ci-deploy-production"
  }
}

override_resource {
  target = aws_iam_role.ci["pipeline"]
  values = {
    arn = "arn:aws:iam::123456789012:role/phoebe-ci-pipeline"
  }
}

# A value unlike the committed one, so the tests prove the pattern comes from
# the variable. The connection is authorized, so the webhooks exist.
variables {
  github_owner_id         = "4242"
  github_connection_ready = true
}

# ---- Webhooks (Review Focus 5: a fork PR never starts a build) --------------

run "webhooks" {
  command = apply

  assert {
    condition     = toset(keys(aws_codebuild_webhook.this)) == toset(["pr", "pr-cleanup", "staging"])
    error_message = "Webhooks exist for phoebe-pr, phoebe-pr-cleanup and phoebe-staging only (release starts from the pipeline)."
  }

  assert {
    condition = alltrue([
      for w in values(aws_codebuild_webhook.this) :
      length(w.filter_group) > 0 && alltrue([
        for g in w.filter_group : anytrue([
          for f in g.filter :
          f.type == "ACTOR_ACCOUNT_ID" && f.pattern == "^4242$" && !coalesce(f.exclude_matched_pattern, false)
        ])
      ])
    ])
    error_message = "Every webhook filter group must include ACTOR_ACCOUNT_ID ^<github_owner_id>$ (not excluded)."
  }

  assert {
    condition = alltrue([
      for g in aws_codebuild_webhook.this["pr"].filter_group : alltrue([
        for f in g.filter : (
          f.type != "EVENT" ||
          toset([for e in split(",", f.pattern) : trimspace(e)]) == toset(["PULL_REQUEST_CREATED", "PULL_REQUEST_UPDATED", "PULL_REQUEST_REOPENED"])
        )
      ]) && anytrue([for f in g.filter : f.type == "EVENT"])
    ])
    error_message = "phoebe-pr groups trigger on PULL_REQUEST_CREATED, UPDATED and REOPENED only."
  }

  assert {
    condition = alltrue([
      for g in aws_codebuild_webhook.this["pr-cleanup"].filter_group : alltrue([
        for f in g.filter : (
          f.type != "EVENT" ||
          toset([for e in split(",", f.pattern) : trimspace(e)]) == toset(["PULL_REQUEST_CLOSED", "PULL_REQUEST_MERGED"])
        )
      ]) && anytrue([for f in g.filter : f.type == "EVENT"])
    ])
    error_message = "phoebe-pr-cleanup groups trigger on PULL_REQUEST_CLOSED and MERGED only."
  }

  assert {
    condition = alltrue([
      for g in aws_codebuild_webhook.this["staging"].filter_group :
      anytrue([for f in g.filter : f.type == "EVENT" && trimspace(f.pattern) == "PUSH"]) &&
      anytrue([for f in g.filter : f.type == "HEAD_REF" && f.pattern == "^refs/heads/main$" && !coalesce(f.exclude_matched_pattern, false)]) &&
      alltrue([for f in g.filter : f.type != "EVENT" || trimspace(f.pattern) == "PUSH"])
    ])
    error_message = "phoebe-staging triggers on PUSH with HEAD_REF ^refs/heads/main$ only."
  }

  assert {
    condition = alltrue([
      for k in ["pr", "pr-cleanup"] :
      aws_codebuild_webhook.this[k].pull_request_build_policy[0].requires_comment_approval == "FORK_PULL_REQUESTS"
    ])
    error_message = "PR webhooks also require maintainer comment approval for fork PRs (defence in depth)."
  }
}

run "webhooks_wait_for_connection" {
  command = plan

  variables {
    github_connection_ready = false
  }

  assert {
    condition     = length(aws_codebuild_webhook.this) == 0
    error_message = "Webhooks need an AVAILABLE connection, so they are created only once github_connection_ready = true."
  }
}

run "committed_owner_id" {
  command = plan

  # terraform.tfvars is committed with the owner's public GitHub id.
  variables {
    github_owner_id = "952024"
  }

  assert {
    condition = alltrue(flatten([
      for w in values(aws_codebuild_webhook.this) : [
        for g in w.filter_group : anytrue([for f in g.filter : f.type == "ACTOR_ACCOUNT_ID" && f.pattern == "^952024$"])
      ]
    ]))
    error_message = "The actor filter pattern follows github_owner_id."
  }
}

# ---- Connection, projects and builds ----------------------------------------

run "builds" {
  command = apply

  assert {
    condition     = aws_codeconnections_connection.github.name == "phoebe-github" && aws_codeconnections_connection.github.provider_type == "GitHub"
    error_message = "Connection phoebe-github, provider GitHub (created PENDING; the owner authorizes it)."
  }

  assert {
    condition = (
      toset([for p in values(aws_codebuild_project.this) : p.name]) ==
      toset(["phoebe-pr", "phoebe-pr-cleanup", "phoebe-staging", "phoebe-release-plan", "phoebe-release-apply"])
    )
    error_message = "Exactly the five CodeBuild projects."
  }

  assert {
    condition = alltrue([
      for p in values(aws_codebuild_project.this) :
      p.environment[0].type == "ARM_CONTAINER" &&
      can(regex("^aws/codebuild/amazonlinux-aarch64-standard:", p.environment[0].image))
    ])
    error_message = "Every project runs ARM_CONTAINER on an amazonlinux-aarch64-standard image."
  }

  assert {
    condition = alltrue([
      for k, p in aws_codebuild_project.this : p.environment[0].privileged_mode == (k == "staging")
    ])
    error_message = "Privileged mode only on phoebe-staging (the only Docker build)."
  }

  assert {
    condition = alltrue([
      for k in ["staging", "release-plan", "release-apply"] : aws_codebuild_project.this[k].concurrent_build_limit == 1
    ])
    error_message = "Staging and release builds run one at a time."
  }

  assert {
    condition = alltrue([
      for k, f in {
        "pr"            = "ci/buildspec-pr.yml"
        "pr-cleanup"    = "ci/buildspec-pr-cleanup.yml"
        "staging"       = "ci/buildspec-staging.yml"
        "release-plan"  = "ci/buildspec-release-plan.yml"
        "release-apply" = "ci/buildspec-release-apply.yml"
      } : aws_codebuild_project.this[k].source[0].buildspec == f
    ])
    error_message = "Each project points at its buildspec path."
  }

  assert {
    condition = alltrue([
      for k in ["pr", "pr-cleanup", "staging"] :
      aws_codebuild_project.this[k].source[0].type == "GITHUB" &&
      aws_codebuild_project.this[k].source[0].location == "https://github.com/ahochoy/phoebe-onboarding.git" &&
      aws_codebuild_project.this[k].source[0].auth[0].type == "CODECONNECTIONS" &&
      aws_codebuild_project.this[k].source[0].auth[0].resource == aws_codeconnections_connection.github.arn
    ])
    error_message = "Webhook projects read GitHub through the phoebe-github connection."
  }

  assert {
    condition = alltrue([
      for k in ["release-plan", "release-apply"] :
      aws_codebuild_project.this[k].source[0].type == "CODEPIPELINE" &&
      aws_codebuild_project.this[k].artifacts[0].type == "CODEPIPELINE"
    ])
    error_message = "Release projects take their source from, and return artifacts to, the pipeline."
  }

  assert {
    condition = alltrue([
      for p in values(aws_codebuild_project.this) :
      p.logs_config[0].cloudwatch_logs[0].group_name == "/aws/codebuild/${p.name}"
    ])
    error_message = "Each project logs to its own pre-created log group."
  }
}

# ---- Project roles ------------------------------------------------------------

run "project_roles" {
  command = apply

  assert {
    condition = alltrue([
      aws_codebuild_project.this["pr"].service_role == "arn:aws:iam::123456789012:role/phoebe-ci-plan",
      aws_codebuild_project.this["pr-cleanup"].service_role == "arn:aws:iam::123456789012:role/phoebe-ci-plan",
      aws_codebuild_project.this["staging"].service_role == "arn:aws:iam::123456789012:role/phoebe-ci-deploy-staging",
      aws_codebuild_project.this["release-plan"].service_role == "arn:aws:iam::123456789012:role/phoebe-ci-deploy-production",
      aws_codebuild_project.this["release-apply"].service_role == "arn:aws:iam::123456789012:role/phoebe-ci-deploy-production",
    ])
    error_message = "pr/pr-cleanup use phoebe-ci-plan; staging and release use their own deploy roles."
  }

  assert {
    condition = alltrue([
      for k, r in aws_iam_role.ci :
      r.name == "phoebe-ci-${k}" && r.permissions_boundary == "arn:aws:iam::123456789012:policy/phoebe-boundary"
    ])
    error_message = "CI roles are phoebe-ci-<name> and carry the boundary themselves."
  }

  # phoebe-ci-plan: only Get/List/Describe, plus exactly the preview writes,
  # the staging invalidation, its own build logs and the connection.
  assert {
    condition = alltrue(flatten([
      for s in jsondecode(aws_iam_role_policy.ci["plan"].policy).Statement : [
        for a in flatten([s.Action]) : (
          can(regex("^[a-z0-9-]+:(Get|List|Describe|BatchGet)[A-Za-z]*\\*?$", a)) ||
          (contains(["s3:PutObject", "s3:DeleteObject"], a) &&
          jsonencode(flatten([s.Resource])) == jsonencode(["arn:aws:s3:::phoebe-staging-site-123456789012/previews/*"])) ||
          (a == "cloudfront:CreateInvalidation" &&
            jsonencode(flatten([s.Resource])) == jsonencode(["arn:aws:cloudfront::123456789012:distribution/*"]) &&
          try(s.Condition.StringEquals["aws:ResourceTag/env"], "") == "staging") ||
          (contains(["logs:CreateLogStream", "logs:PutLogEvents"], a) &&
            alltrue([for r in flatten([s.Resource]) :
          startswith(r, "arn:aws:logs:us-east-2:123456789012:log-group:/aws/codebuild/phoebe-pr")])) ||
          (contains(["codeconnections:UseConnection", "codestar-connections:UseConnection"], a) &&
            alltrue([for r in flatten([s.Resource]) :
          can(regex("^arn:aws:(codeconnections|codestar-connections):us-east-2:123456789012:connection/", r))]))
        )
      ] if s.Effect == "Allow"
    ]))
    error_message = "phoebe-ci-plan has no Create/Put/Delete/Update (or other write) actions beyond the preview objects, the staging invalidation, its build logs and the connection."
  }

  assert {
    condition = anytrue([
      for s in jsondecode(aws_iam_role_policy.ci["plan"].policy).Statement :
      contains(flatten([s.Action]), "s3:PutObject") && contains(flatten([s.Action]), "s3:DeleteObject")
    ])
    error_message = "phoebe-ci-plan can publish and remove previews."
  }

  assert {
    condition = alltrue(flatten([
      for s in jsondecode(aws_iam_role_policy.ci["plan"].policy).Statement : [
        for a in flatten([s.Action]) : a != "*" && !endswith(a, ":*")
      ]
    ]))
    error_message = "No service-wide wildcards on the plan role."
  }

  assert {
    condition = alltrue([
      for k, p in aws_iam_role_policy.ci : length(p.policy) <= 10240
    ])
    error_message = "Inline policies must fit IAM's 10,240-character per-role limit."
  }
}

# ---- Deploy roles ---------------------------------------------------------------

run "deploy_roles" {
  command = apply

  assert {
    condition = alltrue(flatten([
      for k in ["deploy-staging", "deploy-production"] : [
        for s in jsondecode(aws_iam_role_policy.ci[k].policy).Statement : (
          !contains(flatten([s.Action]), "iam:CreateRole") ||
          try(s.Condition.StringEquals["iam:PermissionsBoundary"], "") == "arn:aws:iam::123456789012:policy/phoebe-boundary"
        )
      ]
    ]))
    error_message = "Deploy roles may create roles only with iam:PermissionsBoundary = the boundary ARN."
  }

  assert {
    condition = alltrue([
      for k in ["deploy-staging", "deploy-production"] : anytrue([
        for s in jsondecode(aws_iam_role_policy.ci[k].policy).Statement : contains(flatten([s.Action]), "iam:CreateRole")
      ])
    ])
    error_message = "Deploy roles can create the infra/app roles."
  }

  assert {
    condition = alltrue(flatten([
      for k in keys(aws_iam_role_policy.ci) : [
        for s in jsondecode(aws_iam_role_policy.ci[k].policy).Statement : [
          for a in flatten([s.Action]) : a != "*" && !endswith(a, ":*") && !startswith(a, "iam:*")
        ]
      ]
    ]))
    error_message = "No CI role gets * or service:* actions."
  }

  # Each deploy role manages only its own env's phoebe-<env>-* IAM roles.
  assert {
    condition = alltrue(flatten([
      for env in ["staging", "production"] : [
        for s in jsondecode(aws_iam_role_policy.ci["deploy-${env}"].policy).Statement : [
          for r in flatten([s.Resource]) : (
            !startswith(r, "arn:aws:iam::") ||
            r == "arn:aws:iam::123456789012:role/phoebe-${env}-*" ||
            r == "arn:aws:iam::123456789012:role/aws-service-role/rds.amazonaws.com/AWSServiceRoleForRDS" ||
            (env == "staging" && r == "arn:aws:iam::123456789012:role/PhoebeAgentCoreHarnessExecutionRole")
          )
        ] if s.Effect == "Allow"
      ]
    ]))
    error_message = "Deploy roles touch only role/phoebe-<own env>-* (plus the RDS service-linked role, and infra/ai's harness role read by staging)."
  }

  assert {
    condition = alltrue([
      for env in ["staging", "production"] : anytrue([
        for s in jsondecode(aws_iam_role_policy.ci["deploy-${env}"].policy).Statement :
        contains(flatten([s.Action]), "lambda:InvokeFunction") &&
        jsonencode(flatten([s.Resource])) == jsonencode(["arn:aws:lambda:us-east-2:123456789012:function:phoebe-${env}-ops"])
      ])
    ])
    error_message = "Each deploy role invokes only its own env's ops function."
  }

  assert {
    condition = (
      anytrue([for s in jsondecode(aws_iam_role_policy.ci["deploy-staging"].policy).Statement : contains(flatten([s.Action]), "ecr:PutImage")]) &&
      !anytrue([for s in jsondecode(aws_iam_role_policy.ci["deploy-production"].policy).Statement : contains(flatten([s.Action]), "ecr:PutImage")])
    )
    error_message = "Staging pushes images; production only pulls and describes (promotes by digest)."
  }

  # State: each role writes only its own keys; nobody in CI touches bootstrap.tfstate.
  assert {
    condition = alltrue(flatten([
      for k in keys(aws_iam_role_policy.ci) : [
        for s in jsondecode(aws_iam_role_policy.ci[k].policy).Statement : [
          for r in flatten([s.Resource]) : !strcontains(r, "bootstrap.tfstate") && r != "arn:aws:s3:::phoebe-tfstate-123456789012/*"
        ]
      ]
    ]))
    error_message = "No CI role can read or write bootstrap.tfstate or the whole state bucket."
  }

  assert {
    condition = (
      !anytrue([
        for s in jsondecode(aws_iam_role_policy.ci["deploy-production"].policy).Statement :
        contains(flatten([s.Action]), "s3:PutObject") && contains(flatten([s.Resource]), "arn:aws:s3:::phoebe-tfstate-123456789012/app/staging.tfstate")
      ]) &&
      !anytrue([
        for s in jsondecode(aws_iam_role_policy.ci["deploy-staging"].policy).Statement :
        contains(flatten([s.Action]), "s3:PutObject") && contains(flatten([s.Resource]), "arn:aws:s3:::phoebe-tfstate-123456789012/app/production.tfstate")
      ])
    )
    error_message = "A deploy role cannot write the other env's state."
  }
}

# ---- Boundary ---------------------------------------------------------------------

run "boundary" {
  command = apply

  assert {
    condition     = aws_iam_policy.boundary.name == "phoebe-boundary"
    error_message = "Boundary policy name is phoebe-boundary (infra/app validates the ARN)."
  }

  assert {
    condition = anytrue([
      for s in jsondecode(aws_iam_policy.boundary.policy).Statement :
      s.Effect == "Deny" &&
      length(setsubtract(["iam:Create*", "iam:Put*", "iam:Attach*", "iam:Delete*"], flatten([s.Action]))) == 0 &&
      contains(flatten([try(s.NotResource, [])]), "arn:aws:iam::123456789012:role/phoebe-*") &&
      alltrue([
        for r in flatten([try(s.NotResource, [])]) : contains([
          "arn:aws:iam::123456789012:role/phoebe-*",
          "arn:aws:iam::123456789012:role/aws-service-role/rds.amazonaws.com/AWSServiceRoleForRDS",
        ], r)
      ])
    ])
    error_message = "The boundary denies iam:Create*/Put*/Attach*/Delete* unless the target is role/phoebe-* (or the RDS service-linked role)."
  }

  assert {
    condition = anytrue([
      for s in jsondecode(aws_iam_policy.boundary.policy).Statement :
      s.Effect == "Deny" &&
      toset(flatten([try(s.NotAction, [])])) == toset(["cloudfront:*", "iam:*", "sts:*", "budgets:*"]) &&
      jsonencode(flatten([try(s.Condition.StringNotEquals["aws:RequestedRegion"], [])])) == jsonencode(["us-east-2"])
    ])
    error_message = "The boundary denies every action outside us-east-2 except CloudFront, IAM, STS and Budgets."
  }

  assert {
    condition = alltrue([
      for svc in ["organizations:*", "account:*"] : anytrue([
        for s in jsondecode(aws_iam_policy.boundary.policy).Statement :
        s.Effect == "Deny" && contains(flatten([try(s.Action, [])]), svc)
      ])
    ])
    error_message = "The boundary denies organizations:* and account:*."
  }

  assert {
    condition = anytrue([
      for s in jsondecode(aws_iam_policy.boundary.policy).Statement :
      s.Effect == "Deny" && contains(flatten([try(s.Action, [])]), "iam:DeleteRolePermissionsBoundary")
    ])
    error_message = "Nobody under the boundary may strip a role's boundary."
  }

  assert {
    condition = anytrue([
      for s in jsondecode(aws_iam_policy.boundary.policy).Statement :
      s.Effect == "Deny" &&
      contains(flatten([try(s.Action, [])]), "iam:CreateRole") &&
      try(s.Condition.StringNotEquals["iam:PermissionsBoundary"], "") == "arn:aws:iam::123456789012:policy/phoebe-boundary"
    ])
    error_message = "The boundary itself refuses role creation without the boundary attached."
  }

  assert {
    condition = anytrue([
      for s in jsondecode(aws_iam_policy.boundary.policy).Statement :
      s.Effect == "Deny" && contains(flatten([try(s.Resource, [])]), "arn:aws:iam::123456789012:role/phoebe-ci-*")
    ])
    error_message = "Bounded principals cannot modify the CI roles themselves (no self-escalation)."
  }

  assert {
    condition     = length(replace(aws_iam_policy.boundary.policy, "/\\s/", "")) <= 6144
    error_message = "Managed policies must fit IAM's 6,144-character limit."
  }
}

# ---- Pipeline ----------------------------------------------------------------------

run "pipeline" {
  command = apply

  assert {
    condition     = aws_codepipeline.release.name == "phoebe-release" && aws_codepipeline.release.pipeline_type == "V2"
    error_message = "Pipeline phoebe-release is a V2 pipeline."
  }

  assert {
    condition     = jsonencode([for s in aws_codepipeline.release.stage : s.name]) == jsonencode(["Source", "Plan", "Approve", "Apply"])
    error_message = "Stages are exactly Source, Plan, Approve, Apply, in that order."
  }

  assert {
    condition = (
      aws_codepipeline.release.stage[2].action[0].category == "Approval" &&
      aws_codepipeline.release.stage[2].action[0].provider == "Manual"
    )
    error_message = "Approve is a manual approval action."
  }

  assert {
    condition = (
      aws_codepipeline.release.stage[0].action[0].provider == "CodeStarSourceConnection" &&
      aws_codepipeline.release.stage[0].action[0].configuration["ConnectionArn"] == aws_codeconnections_connection.github.arn &&
      aws_codepipeline.release.stage[0].action[0].configuration["FullRepositoryId"] == "ahochoy/phoebe-onboarding"
    )
    error_message = "Source reads the repo through the phoebe-github connection."
  }

  assert {
    condition = anytrue([
      for t in aws_codepipeline.release.trigger :
      t.provider_type == "CodeStarSourceConnection" &&
      t.git_configuration[0].source_action_name == "Source" &&
      contains(t.git_configuration[0].push[0].tags[0].includes, "v*")
    ])
    error_message = "The pipeline triggers on pushed tags v*."
  }

  assert {
    condition = (
      aws_codepipeline.release.stage[1].action[0].configuration["ProjectName"] == "phoebe-release-plan" &&
      aws_codepipeline.release.stage[3].action[0].configuration["ProjectName"] == "phoebe-release-apply" &&
      contains(aws_codepipeline.release.stage[3].action[0].input_artifacts, "plan")
    )
    error_message = "Plan runs phoebe-release-plan; Apply runs phoebe-release-apply on the saved plan."
  }

  assert {
    condition     = aws_codepipeline.release.role_arn == "arn:aws:iam::123456789012:role/phoebe-ci-pipeline"
    error_message = "The pipeline runs as phoebe-ci-pipeline."
  }
}

# ---- State, ECR, budget -------------------------------------------------------------

run "state_ecr_budget" {
  command = apply

  assert {
    condition     = aws_s3_bucket.state.bucket == "phoebe-tfstate-123456789012"
    error_message = "State bucket is phoebe-tfstate-<account_id>."
  }

  assert {
    condition     = aws_s3_bucket_versioning.state.versioning_configuration[0].status == "Enabled"
    error_message = "State bucket is versioned."
  }

  assert {
    condition = alltrue([
      for r in one(aws_s3_bucket_server_side_encryption_configuration.state.rule[*].apply_server_side_encryption_by_default) :
      r.sse_algorithm == "AES256"
    ])
    error_message = "State bucket uses SSE."
  }

  assert {
    condition = alltrue([
      for b in [aws_s3_bucket_public_access_block.state, aws_s3_bucket_public_access_block.artifacts] :
      b.block_public_acls && b.block_public_policy && b.ignore_public_acls && b.restrict_public_buckets
    ])
    error_message = "Every public-access block is on (state and pipeline artifacts)."
  }

  assert {
    condition = alltrue([
      for p in [aws_s3_bucket_policy.state, aws_s3_bucket_policy.artifacts] : anytrue([
        for s in jsondecode(p.policy).Statement :
        s.Effect == "Deny" && try(s.Condition.Bool["aws:SecureTransport"], "") == "false"
      ])
    ])
    error_message = "State and artifact buckets are TLS-only."
  }

  assert {
    condition = (
      aws_ecr_repository.api.name == "phoebe-api" &&
      aws_ecr_repository.api.image_tag_mutability == "IMMUTABLE" &&
      aws_ecr_repository.api.image_scanning_configuration[0].scan_on_push
    )
    error_message = "ECR phoebe-api: immutable tags, scan on push."
  }

  assert {
    condition = (
      jsondecode(aws_ecr_lifecycle_policy.api.policy).rules[0].selection.countType == "imageCountMoreThan" &&
      jsondecode(aws_ecr_lifecycle_policy.api.policy).rules[0].selection.countNumber == 60
    )
    error_message = "Lifecycle keeps the last 60 images (30 commits x api + jobs, ruling R9)."
  }

  assert {
    condition = (
      aws_sns_topic.budget.name == "phoebe-budget" &&
      aws_budgets_budget.account.budget_type == "COST" &&
      aws_budgets_budget.account.time_unit == "MONTHLY" &&
      tonumber(aws_budgets_budget.account.limit_amount) == 20 &&
      aws_budgets_budget.account.limit_unit == "USD"
    )
    error_message = "One monthly account cost budget at monthly_budget_usd (default 20)."
  }

  assert {
    condition = anytrue([
      for n in aws_budgets_budget.account.notification :
      n.threshold == 80 && n.threshold_type == "PERCENTAGE" && n.notification_type == "ACTUAL" &&
      n.comparison_operator == "GREATER_THAN" &&
      toset(n.subscriber_sns_topic_arns) == toset(["arn:aws:sns:us-east-2:123456789012:phoebe-budget"]) &&
      try(length(n.subscriber_email_addresses), 0) == 0
    ])
    error_message = "Alert at 80% actual to the phoebe-budget topic only (no email addresses)."
  }

  assert {
    condition = anytrue([
      for s in jsondecode(aws_sns_topic_policy.budget.policy).Statement :
      s.Effect == "Allow" && s.Principal.Service == "budgets.amazonaws.com" &&
      contains(flatten([s.Action]), "SNS:Publish") &&
      s.Condition.StringEquals["aws:SourceAccount"] == "123456789012"
    ])
    error_message = "Budgets may publish to the topic, scoped by aws:SourceAccount."
  }
}
