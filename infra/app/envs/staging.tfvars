env = "staging"

# Account-specific inputs (no secrets; the values are ARNs and names). Fill in
# with the account id once infra/bootstrap is applied (Task 9), then commit:
# boundary_policy_arn      = "arn:aws:iam::<account_id>:policy/phoebe-boundary"
# ai_state_bucket          = "phoebe-tfstate-<account_id>"
# budget_topic_arn         = "arn:aws:sns:us-east-2:<account_id>:phoebe-budget"
# password_hash_secret_arn = "arn:aws:secretsmanager:us-east-2:<account_id>:secret:phoebe-staging-password-hash-<suffix>"

# image_digest is passed per deploy: -var image_digest=sha256:...
