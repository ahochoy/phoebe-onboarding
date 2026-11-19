# Offline: a mocked provider, so nothing calls AWS.
mock_provider "aws" {}

run "guardrail_filters" {
  command = plan

  assert {
    condition = toset([
      for f in aws_bedrock_guardrail.answers.content_policy_config[0].filters_config : f.type
    ]) == toset(["HATE", "INSULTS", "SEXUAL", "VIOLENCE", "MISCONDUCT", "PROMPT_ATTACK"])
    error_message = "The guardrail filters the five content categories and prompt attacks."
  }

  assert {
    condition = alltrue([
      for f in aws_bedrock_guardrail.answers.content_policy_config[0].filters_config :
      f.output_strength == "NONE" if f.type == "PROMPT_ATTACK"
    ])
    error_message = "Prompt-attack filtering is input-only (the API requires output NONE)."
  }
}
