env = "production"

# The account's Lambda concurrency quota is 10, and Lambda always keeps 10
# unreserved, so no function can reserve concurrency (owner decision,
# 2026-11-15). The SQS mapping still caps the worker at 2.
api_reserved_concurrency    = null
worker_reserved_concurrency = null

# Account-specific inputs (no secrets; the values are ARNs and names).
boundary_policy_arn      = "arn:aws:iam::927161114143:policy/phoebe-boundary-production"
ai_state_bucket          = "phoebe-tfstate-927161114143"
budget_topic_arn         = "arn:aws:sns:us-east-2:927161114143:phoebe-budget-production"
password_hash_secret_arn = "arn:aws:secretsmanager:us-east-2:927161114143:secret:phoebe-production-password-hash-motrOw"

# Image digests are passed per deploy:
#   -var api_image_digest=sha256:... -var jobs_image_digest=sha256:...
