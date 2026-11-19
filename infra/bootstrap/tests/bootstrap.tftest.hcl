# Offline: every AWS call is mocked. The account id and the ARNs that the
# code compares against are overridden so they look real.

mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
    }
  }

  mock_resource "aws_iam_policy" {
    defaults = {
      arn = "arn:aws:iam::123456789012:policy/phoebe-mock"
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
  target = aws_iam_policy.boundary["staging"]
  values = {
    arn = "arn:aws:iam::123456789012:policy/phoebe-boundary-staging"
  }
}

override_resource {
  target = aws_iam_policy.boundary["production"]
  values = {
    arn = "arn:aws:iam::123456789012:policy/phoebe-boundary-production"
  }
}

override_resource {
  target = aws_iam_policy.boundary["ci"]
  values = {
    arn = "arn:aws:iam::123456789012:policy/phoebe-boundary-ci"
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
  target = aws_sns_topic.budget["staging"]
  values = {
    arn = "arn:aws:sns:us-east-2:123456789012:phoebe-budget-staging"
  }
}

override_resource {
  target = aws_sns_topic.alerts
  values = {
    arn = "arn:aws:sns:us-east-2:123456789012:phoebe-alerts"
  }
}

override_resource {
  target = aws_sns_topic.budget["production"]
  values = {
    arn = "arn:aws:sns:us-east-2:123456789012:phoebe-budget-production"
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
  target = aws_iam_role.ci["pr-cleanup"]
  values = {
    arn = "arn:aws:iam::123456789012:role/phoebe-ci-pr-cleanup"
  }
}

override_resource {
  target = aws_iam_role.ci["deploy-staging"]
  values = {
    arn = "arn:aws:iam::123456789012:role/phoebe-ci-deploy-staging"
  }
}

override_resource {
  target = aws_iam_role.ci["plan-production"]
  values = {
    arn = "arn:aws:iam::123456789012:role/phoebe-ci-plan-production"
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

# ---- Webhooks (a fork PR never starts a build) -----------------------------------

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
        "staging"       = "ci/buildspec-staging.yml"
        "release-plan"  = "ci/buildspec-release-plan.yml"
        "release-apply" = "ci/buildspec-release-apply.yml"
      } : aws_codebuild_project.this[k].source[0].buildspec == f
    ])
    error_message = "Staging and release projects point at their repo buildspec paths."
  }

  # R15: PR builds never take their steps from the PR checkout.
  assert {
    condition = alltrue([
      for k in ["pr", "pr-cleanup"] :
      startswith(aws_codebuild_project.this[k].source[0].buildspec, "version: 0.2") &&
      !strcontains(aws_codebuild_project.this[k].source[0].buildspec, "ci/buildspec")
    ])
    error_message = "phoebe-pr and phoebe-pr-cleanup use inline buildspecs from infra/bootstrap."
  }

  assert {
    condition = (
      strcontains(aws_codebuild_project.this["pr-cleanup"].source[0].buildspec, "*[!0-9]*") &&
      strcontains(aws_codebuild_project.this["pr-cleanup"].source[0].buildspec, "s3://$SITE_BUCKET/previews/pr-$N/") &&
      strcontains(aws_codebuild_project.this["pr-cleanup"].source[0].buildspec, "SITE_BUCKET: \"phoebe-staging-site-123456789012\"") &&
      !strcontains(aws_codebuild_project.this["pr-cleanup"].source[0].buildspec, "npm") &&
      !strcontains(aws_codebuild_project.this["pr-cleanup"].source[0].buildspec, "terraform ")
    )
    error_message = "The cleanup spec only validates N as digits and removes previews/pr-$N/ from the staging site bucket; it runs no repo code."
  }

  assert {
    condition = (
      strcontains(aws_codebuild_project.this["pr"].source[0].buildspec, "*[!0-9]*") &&
      strcontains(aws_codebuild_project.this["pr"].source[0].buildspec, "PHOEBE_BASE=\"/pr-$N/\"") &&
      strcontains(aws_codebuild_project.this["pr"].source[0].buildspec, "-lock=false")
    )
    error_message = "The PR spec validates N, builds the preview under /pr-$N/ and plans without a lock."
  }

  # R11: the preview follows the site caching contract.
  assert {
    condition = (
      strcontains(aws_codebuild_project.this["pr"].source[0].buildspec, "P=\"s3://$SITE_BUCKET/previews/pr-$N\"") &&
      strcontains(aws_codebuild_project.this["pr"].source[0].buildspec,
      "aws s3 sync dist/assets/ \"$P/assets/\" --only-show-errors --cache-control \"public, max-age=31536000, immutable\"") &&
      strcontains(aws_codebuild_project.this["pr"].source[0].buildspec,
      "aws s3 sync dist/ \"$P/\" --only-show-errors --exclude \"assets/*\" --cache-control \"no-cache\"") &&
      strcontains(aws_codebuild_project.this["pr"].source[0].buildspec,
      "aws s3 sync dist/ \"$P/\" --only-show-errors --delete --size-only")
    )
    error_message = "R11: preview assets/ are immutable for a year, root files are no-cache, and the prune only deletes."
  }

  assert {
    condition = alltrue([
      for k in ["pr", "pr-cleanup", "staging"] :
      aws_codebuild_project.this[k].source[0].type == "GITHUB" &&
      aws_codebuild_project.this[k].source[0].location == "https://github.com/ahochoy/phoebe-onboarding.git" &&
      aws_codebuild_project.this[k].source[0].auth[0].type == "CODECONNECTIONS" &&
      aws_codebuild_project.this[k].source[0].auth[0].resource == aws_codeconnections_connection.github.arn
    ])
    error_message = "Webhook projects read GitHub through the phoebe-github connection (a webhook needs a GitHub source, so cleanup cannot be NO_SOURCE)."
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

run "distribution_id_reaches_specs" {
  command = plan

  variables {
    staging_distribution_id = "E2ABCDEF123456"
  }

  assert {
    condition = alltrue([
      for k in ["pr", "pr-cleanup"] :
      strcontains(aws_codebuild_project.this[k].source[0].buildspec, "DISTRIBUTION_ID: \"E2ABCDEF123456\"")
    ])
    error_message = "staging_distribution_id is templated into the inline specs."
  }
}

# ---- Project roles ------------------------------------------------------------

run "project_roles" {
  command = apply

  assert {
    condition = alltrue([
      aws_codebuild_project.this["pr"].service_role == "arn:aws:iam::123456789012:role/phoebe-ci-plan",
      aws_codebuild_project.this["pr-cleanup"].service_role == "arn:aws:iam::123456789012:role/phoebe-ci-pr-cleanup",
      aws_codebuild_project.this["staging"].service_role == "arn:aws:iam::123456789012:role/phoebe-ci-deploy-staging",
      aws_codebuild_project.this["release-plan"].service_role == "arn:aws:iam::123456789012:role/phoebe-ci-plan-production",
      aws_codebuild_project.this["release-apply"].service_role == "arn:aws:iam::123456789012:role/phoebe-ci-deploy-production",
    ])
    error_message = "pr: plan; cleanup: pr-cleanup; staging: deploy-staging; release-plan: plan-production (read-only, before approval); release-apply: deploy-production."
  }

  assert {
    condition = alltrue([
      for k, r in aws_iam_role.ci :
      r.name == "phoebe-ci-${k}" && r.permissions_boundary == "arn:aws:iam::123456789012:policy/phoebe-boundary-ci"
    ])
    error_message = "CI roles are phoebe-ci-<name> and carry phoebe-boundary-ci."
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
          jsonencode(flatten([s.Resource])) == jsonencode(["arn:aws:logs:us-east-2:123456789012:log-group:/aws/codebuild/phoebe-pr:*"])) ||
          (contains(["codeconnections:UseConnection", "codestar-connections:UseConnection"], a) &&
            alltrue([for r in flatten([s.Resource]) :
          can(regex("^arn:aws:(codeconnections|codestar-connections):us-east-2:123456789012:connection/", r))]))
        )
      ] if s.Effect == "Allow"
    ]))
    error_message = "phoebe-ci-plan has no write actions beyond the preview objects, the staging invalidation, its build logs and the connection."
  }

  assert {
    condition = anytrue([
      for s in jsondecode(aws_iam_role_policy.ci["plan"].policy).Statement :
      contains(flatten([s.Action]), "s3:PutObject") && contains(flatten([s.Action]), "s3:DeleteObject")
    ])
    error_message = "phoebe-ci-plan can publish and remove previews."
  }

  # R15: cleanup runs no repo code and needs no state or secrets.
  assert {
    condition = alltrue(flatten([
      for s in jsondecode(aws_iam_role_policy.ci["pr-cleanup"].policy).Statement : [
        for a in flatten([s.Action]) : (
          (a == "s3:DeleteObject" && jsonencode(flatten([s.Resource])) == jsonencode(["arn:aws:s3:::phoebe-staging-site-123456789012/previews/*"])) ||
          (a == "s3:ListBucket" && jsonencode(flatten([s.Resource])) == jsonencode(["arn:aws:s3:::phoebe-staging-site-123456789012"]) &&
          jsonencode(try(s.Condition.StringLike["s3:prefix"], [])) == jsonencode(["previews/pr-*"])) ||
          (a == "cloudfront:CreateInvalidation" && try(s.Condition.StringEquals["aws:ResourceTag/env"], "") == "staging") ||
          (contains(["logs:CreateLogStream", "logs:PutLogEvents"], a) &&
          jsonencode(flatten([s.Resource])) == jsonencode(["arn:aws:logs:us-east-2:123456789012:log-group:/aws/codebuild/phoebe-pr-cleanup:*"])) ||
          (startswith(a, "codeconnections:") || startswith(a, "codestar-connections:"))
        )
      ]
    ]))
    error_message = "phoebe-ci-pr-cleanup can only list and delete previews/pr-*, invalidate staging, write its logs and clone (no state, no secrets)."
  }

  # R14: release-plan runs before approval, so its role is read-only.
  assert {
    condition = alltrue(flatten([
      for s in jsondecode(aws_iam_role_policy.ci["plan-production"].policy).Statement : [
        for a in flatten([s.Action]) : (
          can(regex("^[a-z0-9-]+:(Get|List|Describe|BatchGet)[A-Za-z]*\\*?$", a)) ||
          (a == "s3:PutObject" && jsonencode(flatten([s.Resource])) == jsonencode(["arn:aws:s3:::phoebe-pipeline-artifacts-123456789012/*"])) ||
          (contains(["logs:CreateLogStream", "logs:PutLogEvents"], a) &&
          jsonencode(flatten([s.Resource])) == jsonencode(["arn:aws:logs:us-east-2:123456789012:log-group:/aws/codebuild/phoebe-release-plan:*"])) ||
          (contains(["codeconnections:UseConnection", "codestar-connections:UseConnection"], a) &&
            alltrue([for r in flatten([s.Resource]) :
          can(regex("^arn:aws:(codeconnections|codestar-connections):us-east-2:123456789012:connection/", r))]))
        )
      ] if s.Effect == "Allow"
    ]))
    error_message = "phoebe-ci-plan-production writes nothing but the saved plan artifact and its build logs (plus the connection, to clone)."
  }

  # R17: both release roles can use the connection for the CODEBUILD_CLONE_REF
  # source, with exactly the documented actions, on the phoebe-github connection only.
  assert {
    condition = alltrue([
      for k in ["plan-production", "deploy-production"] : anytrue([
        for s in jsondecode(aws_iam_role_policy.ci[k].policy).Statement :
        s.Sid == "CloneReleaseSource" && s.Effect == "Allow" &&
        jsonencode(sort(flatten([s.Action]))) == jsonencode(sort([
          "codeconnections:UseConnection", "codeconnections:GetConnectionToken", "codestar-connections:UseConnection",
        ])) &&
        jsonencode(sort(flatten([s.Resource]))) == jsonencode(sort([
          "arn:aws:codeconnections:us-east-2:123456789012:connection/00000000-0000-0000-0000-000000000000",
          "arn:aws:codestar-connections:us-east-2:123456789012:connection/00000000-0000-0000-0000-000000000000",
        ]))
      ])
    ])
    error_message = "Release roles hold CloneReleaseSource (UseConnection, GetConnectionToken) on the phoebe-github connection only."
  }

  assert {
    condition = alltrue(flatten([
      for k in keys(aws_iam_role_policy.ci) : [
        for s in jsondecode(aws_iam_role_policy.ci[k].policy).Statement : [
          for a in flatten([s.Action]) : a != "*" && !endswith(a, ":*")
        ]
      ]
    ]))
    error_message = "No CI role gets * or service:* actions."
  }

  assert {
    condition = alltrue([
      for k, p in aws_iam_role_policy.ci :
      length(distinct([for s in jsondecode(p.policy).Statement : s.Sid])) == length(jsondecode(p.policy).Statement)
    ])
    error_message = "Statement Sids are unique within each policy (IAM rejects duplicates)."
  }

  assert {
    condition = alltrue([
      for k, p in aws_iam_role_policy.ci : length(p.policy) <= 10240
    ])
    error_message = "Inline policies must fit IAM's 10,240-character per-role limit."
  }
}

# ---- Env-scoped reads (R14: no cross-env CloudFront or Lambda config) ---------

run "env_scoped_reads" {
  command = apply

  # Roles and the env whose config they may read.
  assert {
    condition = alltrue(flatten([
      for k, env in {
        "plan"              = "staging"
        "deploy-staging"    = "staging"
        "plan-production"   = "production"
        "deploy-production" = "production"
        } : [
        for s in concat(jsondecode(aws_iam_role_policy.ci[k].policy).Statement, jsondecode(aws_iam_policy.ci_reads[env].policy).Statement) : (
          !anytrue([for a in flatten([s.Action]) : startswith(a, "cloudfront:GetDistribution")]) ||
          (try(s.Condition.StringEquals["aws:ResourceTag/env"], "") == env &&
          jsonencode(flatten([s.Resource])) == jsonencode(["arn:aws:cloudfront::123456789012:distribution/*"]))
        )
      ]
    ]))
    error_message = "GetDistribution/GetDistributionConfig only on distributions tagged with the role's own env."
  }

  assert {
    condition = alltrue(flatten([
      for k, env in {
        "plan"              = "staging"
        "deploy-staging"    = "staging"
        "plan-production"   = "production"
        "deploy-production" = "production"
        } : [
        for s in concat(jsondecode(aws_iam_role_policy.ci[k].policy).Statement, jsondecode(aws_iam_policy.ci_reads[env].policy).Statement) : [
          for a in flatten([s.Action]) : (
            # Nothing CloudFront and no Lambda function reads on "*". R24: the
            # one write there is CreateEventSourceMapping, held to own-env functions.
            !contains(flatten([s.Resource]), "*") ||
            (!startswith(a, "cloudfront:") && (!startswith(a, "lambda:") || contains(["lambda:GetEventSourceMapping", "lambda:ListEventSourceMappings"], a))) ||
            (a == "lambda:CreateEventSourceMapping" && try(s.Condition.ArnLike["lambda:FunctionArn"], "") == "arn:aws:lambda:us-east-2:123456789012:function:phoebe-${env}-*")
          )
        ]
      ]
    ]))
    error_message = "No CloudFront or Lambda function config reads on Resource * (they carry the origin secret and env vars)."
  }

  assert {
    condition = alltrue(flatten([
      for k, env in {
        "plan"              = "staging"
        "deploy-staging"    = "staging"
        "plan-production"   = "production"
        "deploy-production" = "production"
        } : [
        for s in concat(jsondecode(aws_iam_role_policy.ci[k].policy).Statement, jsondecode(aws_iam_policy.ci_reads[env].policy).Statement) : [
          for r in flatten([s.Resource]) : !strcontains(r, env == "staging" ? "phoebe-production-" : "phoebe-staging-")
        ]
      ]
    ]))
    error_message = "No env role names the other env's resources."
  }

  assert {
    condition = (
      jsonencode({ for k, a in aws_iam_role_policy_attachment.ci_reads : k => a.policy_arn }) ==
      jsonencode({
        "deploy-production" = aws_iam_policy.ci_reads["production"].arn
        "deploy-staging"    = aws_iam_policy.ci_reads["staging"].arn
        "plan"              = aws_iam_policy.ci_reads["staging"].arn
        "plan-production"   = aws_iam_policy.ci_reads["production"].arn
      })
    )
    error_message = "Staging roles get phoebe-ci-reads-staging, production roles phoebe-ci-reads-production; cleanup and pipeline get none."
  }

  assert {
    condition = alltrue(flatten([
      for env in ["staging", "production"] : [
        for s in jsondecode(aws_iam_policy.ci_reads[env].policy).Statement : [
          for a in flatten([s.Action]) : s.Effect == "Allow" && can(regex("^[a-z0-9-]+:(Get|List|Describe|BatchGet)[A-Za-z]*\\*?$", a))
        ]
      ]
    ]))
    error_message = "phoebe-ci-reads-<env> is read-only."
  }

  assert {
    condition = alltrue([
      for env in ["staging", "production"] :
      aws_iam_policy.ci_reads[env].name == "phoebe-ci-reads-${env}" &&
      length(aws_iam_policy.ci_reads[env].policy) <= 6144 &&
      anytrue([
        for s in jsondecode(aws_iam_policy.ci_reads[env].policy).Statement :
        jsonencode(flatten([s.Action])) == jsonencode(["s3:GetObject"]) &&
        jsonencode(flatten([s.Resource])) == jsonencode(["arn:aws:s3:::phoebe-tfstate-123456789012/ai.tfstate"])
      ])
    ])
    error_message = "Each reads policy fits 6,144 chars and grants the ai.tfstate read terraform_remote_state needs."
  }
}

# ---- Deploy roles ---------------------------------------------------------------

run "deploy_roles" {
  command = apply

  assert {
    condition = alltrue(flatten([
      for env in ["staging", "production"] : [
        for s in jsondecode(aws_iam_role_policy.ci["deploy-${env}"].policy).Statement : (
          s.Effect != "Allow" ||
          !contains(flatten([s.Action]), "iam:CreateRole") ||
          try(s.Condition.StringEquals["iam:PermissionsBoundary"], "") == "arn:aws:iam::123456789012:policy/phoebe-boundary-${env}"
        )
      ]
    ]))
    error_message = "Each deploy role may create roles only with its own env's boundary."
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
      for k in ["plan", "pr-cleanup", "plan-production", "pipeline"] : [
        for s in jsondecode(aws_iam_role_policy.ci[k].policy).Statement :
        !anytrue([for a in flatten([s.Action]) : startswith(a, "iam:") && !can(regex("^iam:(Get|List)", a))])
      ]
    ]))
    error_message = "Only deploy roles have IAM write actions."
  }

  # Each deploy role manages only its own env's phoebe-<env>-* IAM roles.
  assert {
    condition = alltrue(flatten([
      for env in ["staging", "production"] : [
        for s in jsondecode(aws_iam_role_policy.ci["deploy-${env}"].policy).Statement : [
          for r in flatten([s.Resource]) : (
            !startswith(r, "arn:aws:iam::") ||
            r == "arn:aws:iam::123456789012:role/phoebe-${env}-*" ||
            r == "arn:aws:iam::123456789012:role/aws-service-role/rds.amazonaws.com/AWSServiceRoleForRDS"
          )
        ] if s.Effect == "Allow"
      ]
    ]))
    error_message = "Deploy roles touch only role/phoebe-<own env>-* (plus the RDS service-linked role)."
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

  # R24: CreateEventSourceMapping authorizes on "*" (no mapping ARN exists
  # yet), so it stands alone with the own-env lambda:FunctionArn condition; the
  # other mapping actions stay on event-source-mapping:* with the same condition.
  assert {
    condition = alltrue([
      for env in ["staging", "production"] : anytrue([
        for s in jsondecode(aws_iam_role_policy.ci["deploy-${env}"].policy).Statement :
        jsonencode(flatten([s.Action])) == jsonencode(["lambda:CreateEventSourceMapping"]) &&
        jsonencode(flatten([s.Resource])) == jsonencode(["*"]) &&
        s.Condition.ArnLike["lambda:FunctionArn"] == "arn:aws:lambda:us-east-2:123456789012:function:phoebe-${env}-*"
        ]) && alltrue([
        for s in jsondecode(aws_iam_role_policy.ci["deploy-${env}"].policy).Statement : (
          !anytrue([for a in flatten([s.Action]) : contains(["lambda:UpdateEventSourceMapping", "lambda:DeleteEventSourceMapping"], a)]) || (
            jsonencode(flatten([s.Resource])) == jsonencode(["arn:aws:lambda:us-east-2:123456789012:event-source-mapping:*"]) &&
            s.Condition.ArnLike["lambda:FunctionArn"] == "arn:aws:lambda:us-east-2:123456789012:function:phoebe-${env}-*"
          )
        )
      ])
    ])
    error_message = "CreateEventSourceMapping on * with the own-env FunctionArn condition; update/delete stay scoped to mappings."
  }

  assert {
    condition = alltrue([
      for env in ["staging", "production"] : anytrue([
        for s in jsondecode(aws_iam_role_policy.ci["deploy-${env}"].policy).Statement :
        s.Sid == "RdsDefaultVpcReads" && toset(flatten([s.Action])) == toset([
          "ec2:DescribeVpcs", "ec2:DescribeSubnets", "ec2:DescribeSecurityGroups",
          "ec2:DescribeAccountAttributes", "ec2:DescribeAvailabilityZones",
        ])
      ])
    ])
    error_message = "Deploy roles get the five read-only EC2 describes RDS default-VPC placement needs."
  }

  assert {
    condition = !anytrue(flatten([
      for k in keys(aws_iam_role_policy.ci) : [
        for s in jsondecode(aws_iam_role_policy.ci[k].policy).Statement : [
          for a in flatten([s.Action]) : startswith(a, "ec2:") && !startswith(a, "ec2:Describe")
        ]
      ]
    ]))
    error_message = "No CI role has an EC2 action other than a Describe."
  }

  # R13: production adds release-* tags to promoted digests; staging pushes.
  assert {
    condition = (
      alltrue([
        for s in jsondecode(aws_iam_role_policy.ci["deploy-production"].policy).Statement :
        !contains(flatten([s.Action]), "ecr:PutImage") ||
        jsonencode(flatten([s.Resource])) == jsonencode(["arn:aws:ecr:us-east-2:123456789012:repository/phoebe-api"])
      ]) &&
      anytrue([for s in jsondecode(aws_iam_role_policy.ci["deploy-production"].policy).Statement : contains(flatten([s.Action]), "ecr:PutImage")]) &&
      anytrue([for s in jsondecode(aws_iam_role_policy.ci["deploy-production"].policy).Statement : contains(flatten([s.Action]), "ecr:BatchGetImage")]) &&
      !anytrue([for s in jsondecode(aws_iam_role_policy.ci["deploy-production"].policy).Statement : contains(flatten([s.Action]), "ecr:InitiateLayerUpload")])
    )
    error_message = "Production gets BatchGetImage + PutImage on phoebe-api only (retagging, no layer uploads)."
  }

  assert {
    condition = alltrue([
      for a in ["ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage"] : anytrue([
        for s in jsondecode(aws_iam_role_policy.ci["deploy-staging"].policy).Statement :
        contains(flatten([s.Action]), a) && jsonencode(flatten([s.Resource])) == jsonencode(["arn:aws:ecr:us-east-2:123456789012:repository/phoebe-api"])
      ])
    ])
    error_message = "Staging keeps push on phoebe-api."
  }

  assert {
    condition = !anytrue(flatten([
      for k in ["plan", "pr-cleanup", "plan-production", "pipeline"] : [
        for s in jsondecode(aws_iam_role_policy.ci[k].policy).Statement : contains(flatten([s.Action]), "ecr:PutImage")
      ]
    ]))
    error_message = "Only the staging and production deploy roles can put images."
  }

  # R12: infra/ai is owner-applied; CI only reads ai.tfstate.
  assert {
    condition = alltrue(flatten([
      for k in keys(aws_iam_role_policy.ci) : [
        for s in jsondecode(aws_iam_role_policy.ci[k].policy).Statement : [
          for a in flatten([s.Action]) : !startswith(a, "bedrock")
        ]
      ]
    ]))
    error_message = "No CI role has Bedrock or AgentCore actions (infra/ai is owner-applied)."
  }

  assert {
    condition = alltrue(flatten([
      for k in keys(aws_iam_role_policy.ci) : [
        for s in jsondecode(aws_iam_role_policy.ci[k].policy).Statement : (
          !anytrue([for r in flatten([s.Resource]) : strcontains(r, "ai.tfstate")]) ||
          jsonencode(flatten([s.Action])) == jsonencode(["s3:GetObject"])
        )
      ]
    ]))
    error_message = "ai.tfstate is read-only for every CI role."
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
}

# ---- Boundaries ---------------------------------------------------------------------

run "boundary" {
  command = apply

  assert {
    condition     = toset([for p in values(aws_iam_policy.boundary) : p.name]) == toset(["phoebe-boundary-staging", "phoebe-boundary-production", "phoebe-boundary-ci"])
    error_message = "Per-env boundaries for infra/app roles plus one CI boundary."
  }

  assert {
    condition = alltrue([
      for k in keys(aws_iam_policy.boundary) : anytrue([
        for s in jsondecode(aws_iam_policy.boundary[k].policy).Statement :
        s.Effect == "Deny" &&
        length(setsubtract(["iam:Create*", "iam:Put*", "iam:Attach*", "iam:Delete*"], flatten([s.Action]))) == 0 &&
        length(flatten([try(s.NotResource, [])])) > 0 &&
        alltrue([
          for r in flatten([try(s.NotResource, [])]) : contains(
            k == "ci" ? [
              "arn:aws:iam::123456789012:role/phoebe-staging-*",
              "arn:aws:iam::123456789012:role/phoebe-production-*",
              "arn:aws:iam::123456789012:role/aws-service-role/rds.amazonaws.com/AWSServiceRoleForRDS",
            ] : ["arn:aws:iam::123456789012:role/phoebe-${k}-*"],
          r)
        ])
      ])
    ])
    error_message = "Every boundary denies iam:Create*/Put*/Attach*/Delete* unless the target is a phoebe-<env>-* role (env boundaries: only their own env)."
  }

  assert {
    condition = alltrue([
      for k in keys(aws_iam_policy.boundary) : anytrue([
        for s in jsondecode(aws_iam_policy.boundary[k].policy).Statement :
        s.Effect == "Deny" &&
        toset(flatten([try(s.NotAction, [])])) == toset(["cloudfront:*", "iam:*", "sts:*", "budgets:*"]) &&
        jsonencode(flatten([try(s.Condition.StringNotEquals["aws:RequestedRegion"], [])])) == jsonencode(["us-east-2"])
      ])
    ])
    error_message = "Every boundary denies actions outside us-east-2 except CloudFront, IAM, STS and Budgets."
  }

  assert {
    condition = alltrue(flatten([
      for k in keys(aws_iam_policy.boundary) : [
        for svc in ["organizations:*", "account:*"] : anytrue([
          for s in jsondecode(aws_iam_policy.boundary[k].policy).Statement :
          s.Effect == "Deny" && contains(flatten([try(s.Action, [])]), svc)
        ])
      ]
    ]))
    error_message = "Every boundary denies organizations:* and account:*."
  }

  # Env boundaries: nothing of the other env, no CI services.
  assert {
    condition = alltrue(flatten([
      for env in ["staging", "production"] : [
        for s in jsondecode(aws_iam_policy.boundary[env].policy).Statement : [
          for r in flatten([try(s.Resource, []), try(s.NotResource, [])]) :
          !strcontains(r, env == "staging" ? "phoebe-production" : "phoebe-staging")
        ]
      ]
    ]))
    error_message = "No env boundary statement names the other env's resources."
  }

  assert {
    condition = alltrue(flatten([
      for env in ["staging", "production"] : [
        for s in jsondecode(aws_iam_policy.boundary[env].policy).Statement : (
          s.Effect != "Allow" ||
          s.Sid == "SharedAi" ||
          alltrue([
            for r in flatten([s.Resource]) :
            strcontains(r, "phoebe-${env}") || startswith(r, "arn:aws:secretsmanager:us-east-2:123456789012:secret:rds!cluster-")
          ])
        )
      ]
    ]))
    error_message = "Env boundaries allow only phoebe-<env> resources (plus the shared AI resources and the RDS master secret)."
  }

  assert {
    condition = alltrue(flatten([
      for env in ["staging", "production"] : [
        for s in jsondecode(aws_iam_policy.boundary[env].policy).Statement : [
          for a in flatten([try(s.Action, [])]) : !(s.Effect == "Allow" && (
            startswith(a, "codebuild:") || startswith(a, "ecr:") || startswith(a, "iam:") ||
            startswith(a, "codeconnections:") || startswith(a, "cloudfront:") || startswith(a, "sts:")
          ))
        ]
      ]
    ]))
    error_message = "App-role boundaries allow no CodeBuild, ECR, IAM, connection, CloudFront or STS actions."
  }

  assert {
    condition = alltrue([
      for env in ["staging", "production"] : anytrue([
        for s in jsondecode(aws_iam_policy.boundary[env].policy).Statement :
        s.Sid == "SharedAi" && alltrue([for a in flatten([s.Action]) : startswith(a, "bedrock")])
      ])
    ])
    error_message = "The only env-agnostic allow is the shared Bedrock/AgentCore invoke set."
  }

  # CI boundary.
  assert {
    condition = anytrue([
      for s in jsondecode(aws_iam_policy.boundary["ci"].policy).Statement :
      s.Effect == "Deny" &&
      contains(flatten([try(s.Action, [])]), "iam:CreateRole") &&
      toset(flatten([try(s.Condition.StringNotEquals["iam:PermissionsBoundary"], [])])) == toset([
        "arn:aws:iam::123456789012:policy/phoebe-boundary-staging",
        "arn:aws:iam::123456789012:policy/phoebe-boundary-production",
      ])
    ])
    error_message = "CI may only create roles that carry an env boundary."
  }

  assert {
    condition = alltrue([
      for a in ["iam:DeleteRolePermissionsBoundary", "sts:AssumeRole"] : anytrue([
        for s in jsondecode(aws_iam_policy.boundary["ci"].policy).Statement :
        s.Effect == "Deny" && contains(flatten([try(s.Action, [])]), a)
      ])
    ])
    error_message = "CI cannot strip a boundary or hop roles."
  }

  assert {
    condition = anytrue([
      for s in jsondecode(aws_iam_policy.boundary["ci"].policy).Statement :
      s.Effect == "Deny" && contains(flatten([try(s.Resource, [])]), "arn:aws:iam::123456789012:role/phoebe-ci-*")
    ])
    error_message = "CI roles cannot modify the CI roles themselves (no self-escalation)."
  }

  # R24: the CI boundary admits exactly the five EC2 describes, not ec2:*.
  assert {
    condition = anytrue([
      for s in jsondecode(aws_iam_policy.boundary["ci"].policy).Statement :
      s.Effect == "Allow" && toset(flatten([s.Action])) == toset([
        "ec2:DescribeVpcs", "ec2:DescribeSubnets", "ec2:DescribeSecurityGroups",
        "ec2:DescribeAccountAttributes", "ec2:DescribeAvailabilityZones",
      ])
      ]) && !anytrue([
      for s in jsondecode(aws_iam_policy.boundary["ci"].policy).Statement :
      s.Effect == "Allow" && anytrue([for a in flatten([s.Action]) : startswith(a, "ec2:") && !startswith(a, "ec2:Describe")])
    ])
    error_message = "The CI boundary allows only the RDS default-VPC EC2 describes."
  }

  assert {
    condition     = alltrue([for p in values(aws_iam_policy.boundary) : length(replace(p.policy, "/\\s/", "")) <= 6144])
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
    condition     = aws_codepipeline.release.stage[0].action[0].configuration["OutputArtifactFormat"] == "CODEBUILD_CLONE_REF"
    error_message = "R17: Source hands CodeBuild a git clone (CODEBUILD_CLONE_REF) so release-plan reads the tag with git."
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

  # R13: release images are matched first (and so never expired by rule 2).
  assert {
    condition = (
      length(jsondecode(aws_ecr_lifecycle_policy.api.policy).rules) == 2 &&
      jsondecode(aws_ecr_lifecycle_policy.api.policy).rules[0].rulePriority == 1 &&
      jsondecode(aws_ecr_lifecycle_policy.api.policy).rules[0].selection.tagStatus == "tagged" &&
      jsonencode(jsondecode(aws_ecr_lifecycle_policy.api.policy).rules[0].selection.tagPrefixList) == jsonencode(["release-"]) &&
      jsondecode(aws_ecr_lifecycle_policy.api.policy).rules[0].selection.countType == "imageCountMoreThan" &&
      jsondecode(aws_ecr_lifecycle_policy.api.policy).rules[0].selection.countNumber >= 10000
    )
    error_message = "Rule 1 (highest priority) selects release-* tags with an unreachable count, so they are never expired."
  }

  assert {
    condition = (
      jsondecode(aws_ecr_lifecycle_policy.api.policy).rules[1].rulePriority == 2 &&
      jsondecode(aws_ecr_lifecycle_policy.api.policy).rules[1].selection.tagStatus == "any" &&
      jsondecode(aws_ecr_lifecycle_policy.api.policy).rules[1].selection.countType == "imageCountMoreThan" &&
      jsondecode(aws_ecr_lifecycle_policy.api.policy).rules[1].selection.countNumber == 60
    )
    error_message = "Rule 2 (last; tagStatus any must be last) expires everything else beyond the newest 60."
  }

  assert {
    condition = (
      toset([for t in values(aws_sns_topic.budget) : t.name]) == toset(["phoebe-budget-staging", "phoebe-budget-production"]) &&
      toset(keys(aws_budgets_budget.account)) == toset(["staging", "production"]) &&
      alltrue([
        for env, b in aws_budgets_budget.account :
        b.name == "phoebe-monthly-${env}" &&
        b.budget_type == "COST" &&
        b.time_unit == "MONTHLY" &&
        tonumber(b.limit_amount) == 30 &&
        b.limit_unit == "USD" &&
        length(b.cost_filter) == 0
      ])
    )
    error_message = "One monthly account-wide cost budget per env topic, at monthly_budget_usd (default 30, the project's spend limit)."
  }

  assert {
    condition = alltrue([
      for env, b in aws_budgets_budget.account :
      length(b.notification) == 1 && alltrue([
        for n in b.notification :
        n.threshold == 70 && n.threshold_type == "PERCENTAGE" && n.notification_type == "ACTUAL" &&
        n.comparison_operator == "GREATER_THAN" &&
        toset(n.subscriber_sns_topic_arns) == toset(["arn:aws:sns:us-east-2:123456789012:phoebe-budget-${env}"]) &&
        try(length(n.subscriber_email_addresses), 0) == 0
      ])
    ])
    error_message = "Each budget alerts at 70% actual to its own env topic only (Budgets allows one SNS subscriber per notification); no email without alert_email."
  }

  assert {
    condition = alltrue([
      for env in ["staging", "production"] : anytrue([
        for s in jsondecode(aws_sns_topic_policy.budget[env].policy).Statement :
        s.Effect == "Allow" && s.Principal.Service == "budgets.amazonaws.com" &&
        contains(flatten([s.Action]), "SNS:Publish") &&
        s.Resource == "arn:aws:sns:us-east-2:123456789012:phoebe-budget-${env}" &&
        s.Condition.StringEquals["aws:SourceAccount"] == "123456789012"
      ])
    ])
    error_message = "Budgets may publish to each env topic, scoped by aws:SourceAccount."
  }
}

# ---- Fix round 1: budget isolation, RDS secret, fork gate, paths ----------

run "budget_isolation" {
  command = apply

  # Every SNS grant of every CI role (inline and reads) stays on its own env topic.
  assert {
    condition = alltrue(flatten([
      for k, env in {
        "plan"              = "staging"
        "deploy-staging"    = "staging"
        "plan-production"   = "production"
        "deploy-production" = "production"
        } : [
        for s in concat(jsondecode(aws_iam_role_policy.ci[k].policy).Statement, jsondecode(aws_iam_policy.ci_reads[env].policy).Statement) : (
          !anytrue([for a in flatten([s.Action]) : startswith(a, "sns:")]) ||
          alltrue([
            for r in flatten([s.Resource]) :
            r == "arn:aws:sns:us-east-2:123456789012:phoebe-budget-${env}" || r == "arn:aws:sns:us-east-2:123456789012:phoebe-budget-${env}:*"
          ])
        )
      ]
    ]))
    error_message = "No CI role can touch the other env's budget topic or its subscriptions (no SNS grant on *)."
  }

  assert {
    condition = !anytrue(flatten([
      for k in keys(aws_iam_role_policy.ci) : [
        for s in jsondecode(aws_iam_role_policy.ci[k].policy).Statement : anytrue([
          for a in flatten([s.Action]) : contains(["sns:SetSubscriptionAttributes", "sns:*"], a)
        ])
      ]
    ]))
    error_message = "No CI role may change subscription attributes (filter policies would mute the kill switch)."
  }

  assert {
    condition     = !anytrue([for k in ["plan", "pr-cleanup", "plan-production", "pipeline"] : strcontains(aws_iam_role_policy.ci[k].policy, "sns:")])
    error_message = "Only deploy roles have inline SNS actions."
  }

  assert {
    condition = alltrue([
      for env in ["staging", "production"] : alltrue([
        for s in jsondecode(aws_iam_role_policy.ci["deploy-${env}"].policy).Statement : (
          !contains(flatten([s.Action]), "sns:Subscribe") || (
            jsonencode(flatten([s.Action])) == jsonencode(["sns:Subscribe"]) &&
            jsonencode(flatten([s.Resource])) == jsonencode(["arn:aws:sns:us-east-2:123456789012:phoebe-budget-${env}"]) &&
            try(s.Condition.StringEquals["sns:Endpoint"], "") == "arn:aws:lambda:us-east-2:123456789012:function:phoebe-${env}-budget" &&
            try(s.Condition.StringEquals["sns:Protocol"], "") == "lambda"
          )
        )
      ])
    ])
    error_message = "Subscribe only on the own topic, only the own budget Lambda, protocol lambda."
  }

  assert {
    condition = alltrue([
      for env in ["staging", "production"] : anytrue([
        for s in jsondecode(aws_iam_role_policy.ci["deploy-${env}"].policy).Statement :
        jsonencode(flatten([s.Action])) == jsonencode(["sns:Unsubscribe"]) &&
        jsonencode(flatten([s.Resource])) == jsonencode(["arn:aws:sns:us-east-2:123456789012:phoebe-budget-${env}:*"])
      ])
    ])
    error_message = "Unsubscribe only subscriptions on the own topic."
  }
}

run "rds_secret_and_paths" {
  command = apply

  # I1: creating a cluster with a managed password needs no RotateSecret.
  assert {
    condition     = !anytrue([for k in keys(aws_iam_role_policy.ci) : strcontains(aws_iam_role_policy.ci[k].policy, "secretsmanager:RotateSecret")])
    error_message = "No CI role can rotate secrets."
  }

  # I2: the env boundary's master-secret allow fails closed on the cluster tag.
  assert {
    condition = alltrue(flatten([
      for env in ["staging", "production"] : [
        for s in jsondecode(aws_iam_policy.boundary[env].policy).Statement : (
          s.Effect != "Allow" ||
          !anytrue([for r in flatten([s.Resource]) : strcontains(r, "secret:rds!cluster-")]) ||
          try(s.Condition.StringEquals["secretsmanager:ResourceTag/aws:rds:primaryDBClusterArn"], "") == "arn:aws:rds:us-east-2:123456789012:cluster:phoebe-${env}"
        )
      ]
    ]))
    error_message = "The Aurora master secret is allowed only when tagged with this env's cluster."
  }

  assert {
    condition = alltrue([
      for env in ["staging", "production"] : anytrue([
        for s in jsondecode(aws_iam_policy.boundary[env].policy).Statement : s.Sid == "EnvDbSecret" && s.Effect == "Allow"
      ]) && !strcontains(aws_iam_policy.boundary[env].policy, "\"Null\"")
    ])
    error_message = "No Null-guarded (fail-open) secret deny remains."
  }

  # Minor: deploy roles refuse pathed roles ("*" crosses "/").
  assert {
    condition = alltrue([
      for env in ["staging", "production"] : anytrue([
        for s in jsondecode(aws_iam_role_policy.ci["deploy-${env}"].policy).Statement :
        s.Effect == "Deny" && contains(flatten([s.Action]), "iam:CreateRole") &&
        jsonencode(flatten([s.Resource])) == jsonencode(["arn:aws:iam::123456789012:role/*/*"])
      ])
    ])
    error_message = "Deploy roles cannot create roles under a path."
  }
}

run "fork_gate" {
  command = plan

  # I3: phoebe-pr checks the PR's head repo before any repo code runs.
  assert {
    condition = (
      strcontains(aws_codebuild_project.this["pr"].source[0].buildspec, "PHOEBE_GITHUB_REPO: \"ahochoy/phoebe-onboarding\"") &&
      strcontains(aws_codebuild_project.this["pr"].source[0].buildspec, "https://api.github.com/repos/$PHOEBE_GITHUB_REPO/pulls/$N") &&
      strcontains(aws_codebuild_project.this["pr"].source[0].buildspec, "head.repo.full_name") &&
      strcontains(aws_codebuild_project.this["pr"].source[0].buildspec, "--max-time")
    )
    error_message = "The PR spec fetches the PR from the public API and compares .head.repo.full_name with github_repo."
  }

  assert {
    condition = (
      can(regex("(?s)api\\.github\\.com.*npm ci\n", aws_codebuild_project.this["pr"].source[0].buildspec)) &&
      !can(regex("(?s)npm ci\n.*api\\.github\\.com", aws_codebuild_project.this["pr"].source[0].buildspec)) &&
      !can(regex("(?s)terraform init.*api\\.github\\.com", aws_codebuild_project.this["pr"].source[0].buildspec)) &&
      can(regex("(?s)^.*?install:.*?api\\.github\\.com.*?pre_build:", aws_codebuild_project.this["pr"].source[0].buildspec))
    )
    error_message = "The fork gate runs in the install phase, before npm ci and terraform."
  }

  assert {
    condition     = strcontains(aws_codebuild_project.this["pr"].source[0].buildspec, "|| HEAD_REPO=\"\"")
    error_message = "An API failure leaves HEAD_REPO empty, so the gate refuses (fail closed)."
  }

  # Fix round 2: no interpreter that imports from the cwd (a fork's json.py).
  assert {
    condition = (
      !strcontains(aws_codebuild_project.this["pr"].source[0].buildspec, "python") &&
      strcontains(aws_codebuild_project.this["pr"].source[0].buildspec, "| jq -er .head.repo.full_name)")
    )
    error_message = "The fork gate parses with jq only; no python3 anywhere in the PR spec."
  }

  assert {
    condition = can(regex(
      "if ! command -v jq >/dev/null 2>&1; then\\s*echo \"Refusing: jq is required[^\\n]*\\n\\s*exit 1\\s*fi",
      aws_codebuild_project.this["pr"].source[0].buildspec,
    ))
    error_message = "Without jq the gate aborts (fail closed), with no fallback."
  }

  assert {
    condition = (
      can(regex("(?s)install:.*?GATE_DIR=\\$\\(mktemp -d\\) && cd \"\\$GATE_DIR\".*?api\\.github\\.com.*?jq -er", aws_codebuild_project.this["pr"].source[0].buildspec)) &&
      can(regex("(?s)head repo verified[^\\n]*\\n\\s*cd \"\\$CODEBUILD_SRC_DIR\"", aws_codebuild_project.this["pr"].source[0].buildspec))
    )
    error_message = "The gate moves to an empty temp directory before fetching and parsing, and returns to the checkout only after it passes."
  }
}


# ---- Spend-limit alerts --------------------------------------------------------------

run "alert_email_wired_when_set" {
  command = apply

  variables {
    alert_email = "owner@example.com"
  }

  assert {
    condition = (
      toset(one(aws_budgets_budget.account["production"].notification).subscriber_email_addresses) ==
      toset(["owner@example.com"]) &&
      try(length(one(aws_budgets_budget.account["staging"].notification).subscriber_email_addresses), 0) == 0
    )
    error_message = "With alert_email set, only the production budget emails it (both budgets trip together)."
  }

  assert {
    condition = (
      length(aws_sns_topic_subscription.alert_email) == 1 &&
      aws_sns_topic_subscription.alert_email[0].protocol == "email" &&
      aws_sns_topic_subscription.alert_email[0].topic_arn == "arn:aws:sns:us-east-2:123456789012:phoebe-alerts"
    )
    error_message = "With alert_email set, phoebe-alerts has one email subscription."
  }
}

run "alert_email_optional" {
  command = apply

  assert {
    condition     = length(aws_sns_topic_subscription.alert_email) == 0
    error_message = "Without alert_email there is no email subscription."
  }
}

run "db_stopped_rules" {
  command = apply

  assert {
    condition = alltrue([
      for env in ["staging", "production"] :
      aws_cloudwatch_event_rule.db_stopped[env].name == "phoebe-${env}-db-stopped" &&
      jsondecode(aws_cloudwatch_event_rule.db_stopped[env].event_pattern) == {
        source        = ["aws.rds"]
        "detail-type" = ["RDS DB Cluster Event"]
        detail = {
          EventID          = ["RDS-EVENT-0150"]
          SourceIdentifier = ["phoebe-${env}"]
        }
      }
    ])
    error_message = "Each env has phoebe-<env>-db-stopped on RDS-EVENT-0150 for its own cluster."
  }

  assert {
    condition = alltrue([
      for env in ["staging", "production"] :
      aws_cloudwatch_event_target.db_stopped_lambda[env].rule == "phoebe-${env}-db-stopped" &&
      aws_cloudwatch_event_target.db_stopped_lambda[env].arn == "arn:aws:lambda:us-east-2:123456789012:function:phoebe-${env}-budget" &&
      aws_cloudwatch_event_target.db_stopped_email[env].rule == "phoebe-${env}-db-stopped" &&
      aws_cloudwatch_event_target.db_stopped_email[env].arn == "arn:aws:sns:us-east-2:123456789012:phoebe-alerts" &&
      strcontains(aws_cloudwatch_event_target.db_stopped_email[env].input_transformer[0].input_template, "make db-start ENV=${env}")
    ])
    error_message = "Each rule targets its env's budget Lambda and the alerts topic, whose message names make db-start."
  }

  assert {
    condition = anytrue([
      for s in jsondecode(aws_sns_topic_policy.alerts.policy).Statement :
      s.Effect == "Allow" && s.Principal.Service == "events.amazonaws.com" &&
      contains(flatten([s.Action]), "SNS:Publish") &&
      s.Resource == "arn:aws:sns:us-east-2:123456789012:phoebe-alerts" &&
      toset(flatten([s.Condition.ArnEquals["aws:SourceArn"]])) == toset([
        "arn:aws:events:us-east-2:123456789012:rule/phoebe-staging-db-stopped",
        "arn:aws:events:us-east-2:123456789012:rule/phoebe-production-db-stopped",
      ])
    ])
    error_message = "Only the two db-stopped rules may publish to phoebe-alerts."
  }
}
