terraform {
  required_version = ">= 1.10, < 2.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.62"
    }
  }

  # The first apply (Task 9) runs with local state through an uncommitted
  # local_override.tf; `terraform init -migrate-state -backend-config=bucket=...`
  # then moves the state into the bucket this root creates (see README.md).
  backend "s3" {
    key          = "bootstrap.tfstate"
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
