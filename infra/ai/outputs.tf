output "guardrail_id" {
  description = "Value for PHOEBE_GUARDRAIL_ID."
  value       = aws_bedrock_guardrail.answers.guardrail_id
}

output "guardrail_version" {
  description = "Value for PHOEBE_GUARDRAIL_VERSION."
  value       = aws_bedrock_guardrail_version.answers.version
}

output "harness_haiku_arn" {
  description = "Value for PHOEBE_HARNESS_ARN (default answer model)."
  value       = aws_bedrockagentcore_harness.haiku.arn
}

output "harness_nova_arn" {
  description = "Value for PHOEBE_HARNESS_ARN when answering with Nova Micro."
  value       = aws_bedrockagentcore_harness.nova.arn
}
