output "api_function_url" {
  description = "API function URL (CloudFront origin for /api/*; direct calls get 403)."
  value       = aws_lambda_function_url.api.function_url
}

output "site_bucket" {
  description = "S3 bucket holding the SPA (and staging previews/)."
  value       = aws_s3_bucket.site.bucket
}

output "ops_function_name" {
  description = "Ops Lambda for migrate / seed_if_empty / status."
  value       = aws_lambda_function.this["ops"].function_name
}

output "cluster_arn" {
  description = "Aurora cluster ARN (PHOEBE_DB_CLUSTER_ARN)."
  value       = aws_rds_cluster.main.arn
}

output "db_secret_arn" {
  description = "Aurora managed master-user secret ARN (PHOEBE_DB_SECRET_ARN)."
  value       = local.db_secret_arn
}

output "origin_secret_arn" {
  description = "Secrets Manager ARN of the X-Phoebe-Origin header value."
  value       = aws_secretsmanager_secret.origin.arn
}

output "api_role_arn" {
  description = "API Lambda execution role ARN."
  value       = aws_iam_role.lambda["api"].arn
}

output "distribution_id" {
  description = "CloudFront distribution id (ci/deploy.sh invalidates /*; staging's feeds infra/bootstrap staging_distribution_id)."
  value       = aws_cloudfront_distribution.main.id
}

output "site_url" {
  description = "Public URL of this env's CloudFront distribution (SPA at /, API at /api/*, previews at /pr-<n>/ in staging)."
  value       = "https://${aws_cloudfront_distribution.main.domain_name}"
}
