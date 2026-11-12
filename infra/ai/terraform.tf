terraform {
  required_version = ">= 1.10, < 2.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.62"
    }
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
