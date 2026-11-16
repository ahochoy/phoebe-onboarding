terraform {
  required_version = ">= 1.10, < 2.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.62"
    }
  }

  # Shared state in the bootstrap bucket. The local terraform.tfstate moves
  # here with `terraform init -migrate-state` in Task 9 (see infra/bootstrap).
  backend "s3" {
    key          = "ai.tfstate"
    region       = "us-east-2"
    use_lockfile = true
    encrypt      = true
    # bucket = "phoebe-tfstate-<account_id>" (pass -backend-config=bucket=...)
  }
}

provider "aws" {
  region = "us-east-2"

  default_tags {
    tags = {
      project = "phoebe"
    }
  }
}
