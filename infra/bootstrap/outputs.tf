output "state_bucket" {
  description = "Terraform state bucket (infra/app ai_state_bucket; every backend's bucket)."
  value       = aws_s3_bucket.state.bucket
}

output "boundary_policy_arn" {
  description = "phoebe-boundary ARN (infra/app boundary_policy_arn)."
  value       = aws_iam_policy.boundary.arn
}

output "budget_topic_arn" {
  description = "phoebe-budget SNS topic ARN in us-east-2 (infra/app budget_topic_arn)."
  value       = aws_sns_topic.budget.arn
}

output "ecr_repository_url" {
  description = "phoebe-api repository URL (tags <sha> and <sha>-jobs)."
  value       = aws_ecr_repository.api.repository_url
}

output "connection_arn" {
  description = "phoebe-github CodeConnections ARN."
  value       = aws_codeconnections_connection.github.arn
}

output "connection_status" {
  description = "PENDING until the owner authorizes it in the console; then set github_connection_ready = true and re-apply."
  value       = aws_codeconnections_connection.github.connection_status
}

output "codebuild_projects" {
  description = "CodeBuild project names."
  value       = [for p in aws_codebuild_project.this : p.name]
}

output "pipeline_name" {
  description = "Release pipeline (v* tags)."
  value       = aws_codepipeline.release.name
}

output "ci_role_arns" {
  description = "CI role ARNs by name."
  value       = { for k, r in aws_iam_role.ci : "phoebe-ci-${k}" => r.arn }
}
