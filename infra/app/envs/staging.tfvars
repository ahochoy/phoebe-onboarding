env = "staging"

# The account's Lambda concurrency quota is 10, and Lambda always keeps 10
# unreserved, so no function can reserve concurrency (owner decision,
# 2026-11-15). The SQS mapping still caps the worker at 2.
api_reserved_concurrency    = null
worker_reserved_concurrency = null

# Account-specific inputs (no secrets; the values are ARNs and names). Fill in
# with the account id once infra/bootstrap is applied (Task 9), then commit:
# boundary_policy_arn      = "arn:aws:iam::<account_id>:policy/phoebe-boundary-staging"
# ai_state_bucket          = "phoebe-tfstate-<account_id>"
# budget_topic_arn         = "arn:aws:sns:us-east-2:<account_id>:phoebe-budget-staging"
# password_hash_secret_arn = "arn:aws:secretsmanager:us-east-2:<account_id>:secret:phoebe-staging-password-hash-<suffix>"

# Image digests are passed per deploy:
#   -var api_image_digest=sha256:... -var jobs_image_digest=sha256:...
