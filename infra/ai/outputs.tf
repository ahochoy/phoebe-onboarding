output "guardrail_id" {
  description = "Value for PHOEBE_GUARDRAIL_ID."
  value       = aws_bedrock_guardrail.answers.guardrail_id
}

output "guardrail_version" {
  description = "Value for PHOEBE_GUARDRAIL_VERSION."
  value       = aws_bedrock_guardrail_version.answers.version
}
