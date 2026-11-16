# phoebe-release: a pushed v* tag -> plan production -> owner approves -> apply
# that saved plan. Plan and Apply both run as phoebe-ci-deploy-production.

locals {
  # The tag's commit; release-plan resolves phoebe-api:<sha> and <sha>-jobs to digests.
  release_env = jsonencode([{
    name  = "RELEASE_COMMIT"
    value = "#{SourceVariables.CommitId}"
    type  = "PLAINTEXT"
  }])
}

resource "aws_codepipeline" "release" {
  name           = "phoebe-release"
  role_arn       = aws_iam_role.ci["pipeline"].arn
  pipeline_type  = "V2"
  execution_mode = "QUEUED" # never supersede a release waiting for approval

  artifact_store {
    type     = "S3"
    location = aws_s3_bucket.artifacts.bucket
  }

  stage {
    name = "Source"

    action {
      name             = "Source"
      category         = "Source"
      owner            = "AWS"
      provider         = "CodeStarSourceConnection"
      version          = "1"
      namespace        = "SourceVariables"
      output_artifacts = ["source"]

      configuration = {
        ConnectionArn    = aws_codeconnections_connection.github.arn
        FullRepositoryId = var.github_repo
        BranchName       = "main"
      }
    }
  }

  stage {
    name = "Plan"

    action {
      name             = "Plan"
      category         = "Build"
      owner            = "AWS"
      provider         = "CodeBuild"
      version          = "1"
      input_artifacts  = ["source"]
      output_artifacts = ["plan"]

      configuration = {
        ProjectName          = aws_codebuild_project.this["release-plan"].name
        EnvironmentVariables = local.release_env
      }
    }
  }

  stage {
    name = "Approve"

    action {
      name     = "Approve"
      category = "Approval"
      owner    = "AWS"
      provider = "Manual"
      version  = "1"

      configuration = {
        CustomData = "Review the production plan in the Plan stage's phoebe-release-plan build log, then approve."
      }
    }
  }

  stage {
    name = "Apply"

    action {
      name            = "Apply"
      category        = "Build"
      owner           = "AWS"
      provider        = "CodeBuild"
      version         = "1"
      input_artifacts = ["source", "plan"]

      configuration = {
        ProjectName          = aws_codebuild_project.this["release-apply"].name
        PrimarySource        = "source"
        EnvironmentVariables = local.release_env
      }
    }
  }

  trigger {
    provider_type = "CodeStarSourceConnection"

    git_configuration {
      source_action_name = "Source"

      push {
        tags {
          includes = ["v*"]
        }
      }
    }
  }
}
