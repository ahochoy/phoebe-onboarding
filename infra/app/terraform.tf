terraform {
  required_version = ">= 1.10, < 2.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.62"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.7"
    }
  }

  # Partial config: bucket, key, region and use_lockfile come from
  # envs/<env>.s3.tfbackend (`terraform init -backend-config=...`).
  backend "s3" {}
}

provider "aws" {
  region = "us-east-2"

  default_tags {
    tags = {
      project = "phoebe"
      env     = var.env
    }
  }
}
