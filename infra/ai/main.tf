# ---- Guardrail --------------------------------------------------------------

resource "aws_bedrock_guardrail" "answers" {
  name                      = "phoebe-answers"
  description               = "Input and output safety filters for Phoebe chat answers."
  blocked_input_messaging   = "Phoebe can't help with that one."
  blocked_outputs_messaging = "Phoebe can't help with that one."

  content_policy_config {
    dynamic "filters_config" {
      for_each = ["HATE", "INSULTS", "SEXUAL", "VIOLENCE", "MISCONDUCT"]
      content {
        type            = filters_config.value
        input_strength  = "MEDIUM"
        output_strength = "MEDIUM"
      }
    }

    # Prompt-attack filtering is input-only; the API requires output NONE.
    filters_config {
      type            = "PROMPT_ATTACK"
      input_strength  = "HIGH"
      output_strength = "NONE"
    }
  }
}

resource "aws_bedrock_guardrail_version" "answers" {
  guardrail_arn = aws_bedrock_guardrail.answers.guardrail_arn
  description   = "Phoebe answers v1"
}
