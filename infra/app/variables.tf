variable "env" {
  description = "Environment name: staging or production. Prefixes every resource as phoebe-<env>."
  type        = string

  validation {
    condition     = contains(["staging", "production"], var.env)
    error_message = "env must be staging or production."
  }
}

variable "api_image_digest" {
  description = "Digest of the `api` image (Dockerfile target api, tag <sha>) the API Lambda runs. Never a tag."
  type        = string

  validation {
    condition     = can(regex("^sha256:[0-9a-f]{64}$", var.api_image_digest))
    error_message = "api_image_digest must be sha256:<64 lowercase hex>, not a tag."
  }
}

variable "jobs_image_digest" {
  description = "Digest of the `jobs` image (Dockerfile target jobs, tag <sha>-jobs) the other Lambdas run. Never a tag."
  type        = string

  validation {
    condition     = can(regex("^sha256:[0-9a-f]{64}$", var.jobs_image_digest))
    error_message = "jobs_image_digest must be sha256:<64 lowercase hex>, not a tag."
  }
}

variable "boundary_policy_arn" {
  description = "ARN of this env's bootstrap permissions boundary (phoebe-boundary-<env>). Every role here sets it."
  type        = string

  validation {
    condition     = can(regex("^arn:aws:iam::[0-9]{12}:policy/phoebe-boundary-${var.env}$", var.boundary_policy_arn))
    error_message = "boundary_policy_arn must be arn:aws:iam::<account>:policy/phoebe-boundary-<env> (this env's boundary)."
  }
}

variable "ai_state_bucket" {
  description = "S3 bucket that holds the shared infra/ai state (key ai.tfstate)."
  type        = string

  validation {
    condition     = can(regex("^phoebe-tfstate-[0-9]{12}$", var.ai_state_bucket))
    error_message = "ai_state_bucket must be phoebe-tfstate-<account_id>."
  }
}

variable "budget_topic_arn" {
  description = "ARN of this env's bootstrap budget SNS topic (phoebe-budget-<env>, us-east-2)."
  type        = string

  validation {
    condition     = can(regex("^arn:aws:sns:us-east-2:[0-9]{12}:phoebe-budget-${var.env}$", var.budget_topic_arn))
    error_message = "budget_topic_arn must be this env's phoebe-budget-<env> topic in us-east-2."
  }
}

variable "password_hash_secret_arn" {
  description = "ARN of the owner-created Secrets Manager secret phoebe-<env>-password-hash (Task 9)."
  type        = string

  validation {
    condition = can(regex(
      "^arn:aws:secretsmanager:us-east-2:[0-9]{12}:secret:phoebe-${var.env}-password-hash-[A-Za-z0-9]{6}$",
      var.password_hash_secret_arn,
    ))
    error_message = "password_hash_secret_arn must be the full ARN (with the 6-character random suffix) of this env's phoebe-<env>-password-hash secret in us-east-2."
  }
}

variable "answer_harness" {
  description = "Which infra/ai harness answers chat: haiku (default) or nova (while Haiku access is pending)."
  type        = string
  default     = "haiku"

  validation {
    condition     = contains(["haiku", "nova"], var.answer_harness)
    error_message = "answer_harness must be haiku or nova."
  }
}

# Ruling R23: reserved concurrency counts against the account's concurrency
# quota (new accounts can be as low as 10, with 10 always left unreserved).
# Task 9 checks the quota; the owner requests an increase or sets null.
variable "api_reserved_concurrency" {
  description = "Reserved concurrency for the API Lambda (the spend cap on parallel requests). null = unreserved."
  type        = number
  default     = 5
  nullable    = true

  validation {
    condition     = coalesce(var.api_reserved_concurrency, 1) >= 1
    error_message = "api_reserved_concurrency must be null or at least 1 (0 would disable the API)."
  }
}

variable "worker_reserved_concurrency" {
  description = "Reserved concurrency for the indexing worker Lambda. null = unreserved (the SQS mapping still caps it at 2)."
  type        = number
  default     = 2
  nullable    = true

  validation {
    condition     = coalesce(var.worker_reserved_concurrency, 1) >= 1
    error_message = "worker_reserved_concurrency must be null or at least 1 (0 would stop indexing)."
  }
}

variable "log_level" {
  description = "PHOEBE_LOG_LEVEL for every Lambda."
  type        = string
  default     = "INFO"

  validation {
    condition     = contains(["DEBUG", "INFO", "WARNING", "ERROR"], var.log_level)
    error_message = "log_level must be DEBUG, INFO, WARNING or ERROR."
  }
}
