# GitHub connection, the five CodeBuild projects and their webhooks.

# Created PENDING. The owner authorizes it once in the console (README.md).
resource "aws_codeconnections_connection" "github" {
  name          = "phoebe-github"
  provider_type = "GitHub"
}

locals {
  repo_url = "https://github.com/${var.github_repo}.git"
  image    = "aws/codebuild/amazonlinux-aarch64-standard:3.0"

  # pr and pr-cleanup take their steps from here, never from the checkout.
  # Every other project uses ci/buildspec-<key>.yml.
  inline_buildspecs = {
    "pr" = templatefile("${path.module}/buildspecs/pr.yml", {
      site_bucket       = "phoebe-staging-site-${local.account_id}"
      state_bucket      = local.state_bucket
      distribution_id   = var.staging_distribution_id
      terraform_version = local.terraform_version
      github_repo       = var.github_repo
    })
    "pr-cleanup" = templatefile("${path.module}/buildspecs/pr-cleanup.yml", {
      site_bucket     = "phoebe-staging-site-${local.account_id}"
      distribution_id = var.staging_distribution_id
    })
  }
  terraform_version = "1.16.4"

  # Only the owner's own events ever start a build. A fork PR's actor is the
  # fork's author, so it matches no group.
  actor_filter = { type = "ACTOR_ACCOUNT_ID", pattern = "^${var.github_owner_id}$" }

  projects = {
    "pr" = {
      description = "PR: frontend preview at /pr-<n>/ and read-only staging plan (inline buildspec)"
      role        = "plan"
      source      = "GITHUB"
      privileged  = false
      concurrency = null
      timeout     = 30
      events      = "PULL_REQUEST_CREATED, PULL_REQUEST_UPDATED, PULL_REQUEST_REOPENED"
      ref_filter  = { type = "BASE_REF", pattern = "^refs/heads/main$" }
    }
    "pr-cleanup" = {
      description = "PR closed or merged: delete previews/pr-<n>/ (inline buildspec)"
      role        = "pr-cleanup"
      source      = "GITHUB"
      privileged  = false
      concurrency = null
      timeout     = 15
      events      = "PULL_REQUEST_CLOSED, PULL_REQUEST_MERGED"
      ref_filter  = { type = "BASE_REF", pattern = "^refs/heads/main$" }
    }
    "staging" = {
      description = "Push to main: build and push the images, deploy staging"
      role        = "deploy-staging"
      source      = "GITHUB"
      privileged  = true # docker buildx; the only Docker build
      concurrency = 1
      timeout     = 60
      events      = "PUSH"
      ref_filter  = { type = "HEAD_REF", pattern = "^refs/heads/main$" }
    }
    "release-plan" = {
      description = "Release: resolve the tag commit's digests, plan production (read-only)"
      role        = "plan-production"
      source      = "CODEPIPELINE"
      privileged  = false # promotes by digest, never builds
      concurrency = 1
      timeout     = 30
      events      = null
      ref_filter  = null
    }
    "release-apply" = {
      description = "Release: apply the saved production plan, migrate, seed, publish the SPA"
      role        = "deploy-production"
      source      = "CODEPIPELINE"
      privileged  = false
      concurrency = 1
      timeout     = 60
      events      = null
      ref_filter  = null
    }
  }

  webhook_projects = var.github_connection_ready ? {
    for k, p in local.projects : k => p if p.events != null
  } : {}
}

# Pre-created so the build roles need only CreateLogStream/PutLogEvents.
resource "aws_cloudwatch_log_group" "build" {
  for_each = local.projects

  name              = "/aws/codebuild/phoebe-${each.key}"
  retention_in_days = 30
}

resource "aws_codebuild_project" "this" {
  for_each = local.projects

  name                   = "phoebe-${each.key}"
  description            = each.value.description
  service_role           = aws_iam_role.ci[each.value.role].arn
  build_timeout          = each.value.timeout
  concurrent_build_limit = each.value.concurrency

  artifacts {
    type = each.value.source == "CODEPIPELINE" ? "CODEPIPELINE" : "NO_ARTIFACTS"
  }

  environment {
    type                        = "ARM_CONTAINER"
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = local.image
    image_pull_credentials_type = "CODEBUILD"
    privileged_mode             = each.value.privileged
  }

  source {
    type            = each.value.source
    location        = each.value.source == "GITHUB" ? local.repo_url : null
    git_clone_depth = each.value.source == "GITHUB" ? 1 : null
    buildspec       = lookup(local.inline_buildspecs, each.key, "ci/buildspec-${each.key}.yml")

    dynamic "auth" {
      for_each = each.value.source == "GITHUB" ? [1] : []
      content {
        type     = "CODECONNECTIONS"
        resource = aws_codeconnections_connection.github.arn
      }
    }
  }

  logs_config {
    cloudwatch_logs {
      group_name = aws_cloudwatch_log_group.build[each.key].name
    }

    s3_logs {
      status = "DISABLED"
    }
  }

  depends_on = [aws_iam_role_policy.ci]
}

resource "aws_codebuild_webhook" "this" {
  for_each = local.webhook_projects

  project_name = aws_codebuild_project.this[each.key].name
  build_type   = "BUILD"

  filter_group {
    filter {
      type    = "EVENT"
      pattern = each.value.events
    }

    filter {
      type    = each.value.ref_filter.type
      pattern = each.value.ref_filter.pattern
    }

    filter {
      type    = local.actor_filter.type
      pattern = local.actor_filter.pattern
    }
  }

  # Defence in depth for PRs: fork PRs would also need a maintainer's approval
  # comment (the actor filter already stops them).
  dynamic "pull_request_build_policy" {
    for_each = startswith(each.value.events, "PULL_REQUEST") ? [1] : []
    content {
      requires_comment_approval = "FORK_PULL_REQUESTS"
      approver_roles            = ["GITHUB_ADMIN"]
    }
  }
}
