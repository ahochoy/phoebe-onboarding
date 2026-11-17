# Offline: a mocked provider, so nothing calls AWS.
mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
    }
  }
  mock_data "aws_partition" {
    defaults = {
      partition = "aws"
    }
  }
  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }
}

# Each chat opens a new runtime session (a fresh runtimeSessionId), and an idle
# session bills its memory until this timeout. One minute instead of 30 cuts
# that idle cost, which was most of the AgentCore line.
run "harness_idle_timeout" {
  command = plan

  assert {
    condition = alltrue([
      for h in [aws_bedrockagentcore_harness.haiku, aws_bedrockagentcore_harness.nova] :
      h.environment[0].agentcore_runtime_environment[0].lifecycle_configuration[0].idle_runtime_session_timeout == 60
    ])
    error_message = "Both harnesses end idle runtime sessions after 60 seconds."
  }
}
