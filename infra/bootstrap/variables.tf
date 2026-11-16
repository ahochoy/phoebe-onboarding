variable "github_repo" {
  description = "GitHub repository (owner/name) that CodeBuild and the release pipeline build."
  type        = string
  default     = "ahochoy/phoebe-onboarding"

  validation {
    condition     = can(regex("^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$", var.github_repo))
    error_message = "github_repo must be owner/name."
  }
}

variable "github_owner_id" {
  description = "The owner's numeric GitHub user id. Every webhook filter group requires ACTOR_ACCOUNT_ID ^<id>$, so a fork PR never starts a build."
  type        = string

  validation {
    condition     = can(regex("^[0-9]+$", var.github_owner_id))
    error_message = "github_owner_id must be the numeric GitHub user id (not the login)."
  }
}

variable "github_connection_ready" {
  description = "Set true once the owner has authorized the phoebe-github connection in the console. CodeBuild can only create the GitHub webhooks through an AVAILABLE connection."
  type        = bool
  default     = false
}

variable "staging_distribution_id" {
  description = "Staging CloudFront distribution id, once infra/app has created it (Task 9). The inline PR and cleanup buildspecs invalidate /pr-<n>/* with it; empty skips the invalidation."
  type        = string
  default     = ""

  validation {
    condition     = can(regex("^(E[A-Z0-9]+)?$", var.staging_distribution_id))
    error_message = "staging_distribution_id must be empty or a CloudFront distribution id (E...)."
  }
}

variable "monthly_budget_usd" {
  description = "Monthly account cost budget in USD. 80% of actual spend alerts the phoebe-budget topic."
  type        = number
  default     = 20

  validation {
    condition     = var.monthly_budget_usd > 0
    error_message = "monthly_budget_usd must be positive."
  }
}
