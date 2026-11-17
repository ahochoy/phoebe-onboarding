data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

# infra/ai is a separate shared root (guardrail + harnesses); read its outputs.
data "terraform_remote_state" "ai" {
  backend = "s3"

  config = {
    bucket = var.ai_state_bucket
    key    = "ai.tfstate"
    region = "us-east-2"
  }
}

locals {
  region     = "us-east-2"
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
  prefix     = "phoebe-${var.env}"
  production = var.env == "production"

  ai                = data.terraform_remote_state.ai.outputs
  harness_arn       = var.answer_harness == "nova" ? local.ai.harness_nova_arn : local.ai.harness_haiku_arn
  guardrail_arn     = "arn:${local.partition}:bedrock:${local.region}:${local.account_id}:guardrail/${local.ai.guardrail_id}"
  db_secret_arn     = aws_rds_cluster.main.master_user_secret[0].secret_arn
  db_name           = "phoebe"
  aurora_engine     = "aurora-postgresql"
  aurora_engine_ver = "16.15" # min_capacity = 0 needs 16.3+; 16.15 was the latest non-limitless 16.x in us-east-2 on 2026-11-15 (R27).
}

# ---- Aurora PostgreSQL Serverless v2, reached only through the Data API -----

resource "aws_rds_cluster" "main" {
  cluster_identifier = local.prefix
  engine             = local.aurora_engine
  engine_mode        = "provisioned"
  engine_version     = local.aurora_engine_ver
  database_name      = local.db_name

  master_username             = "phoebe_admin"
  manage_master_user_password = true

  enable_http_endpoint = true
  storage_encrypted    = true

  deletion_protection       = local.production
  skip_final_snapshot       = !local.production
  final_snapshot_identifier = local.production ? "${local.prefix}-final" : null
  backup_retention_period   = local.production ? 7 : 1
  copy_tags_to_snapshot     = true

  # 1 ACU is plenty for this demo, and a low peak keeps the project spend limit's
  # projection calm: it extrapolates from bursts, not from what was spent.
  serverlessv2_scaling_configuration {
    min_capacity             = 0
    max_capacity             = 1
    seconds_until_auto_pause = 300
  }

  lifecycle {
    # Minor versions are upgraded by AWS; don't fight them on every plan.
    ignore_changes = [engine_version]
  }
}

resource "aws_rds_cluster_instance" "main" {
  identifier          = "${local.prefix}-1"
  cluster_identifier  = aws_rds_cluster.main.id
  instance_class      = "db.serverless"
  engine              = aws_rds_cluster.main.engine
  engine_version      = aws_rds_cluster.main.engine_version
  publicly_accessible = false

  auto_minor_version_upgrade = true

  lifecycle {
    ignore_changes = [engine_version]
  }
}

# ---- DynamoDB: sessions, and counters + kill switch ------------------------
# Expiry is enforced in code; TTL on expires_at only garbage-collects.

resource "aws_dynamodb_table" "sessions" {
  name         = "${local.prefix}-sessions"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"

  attribute {
    name = "pk"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  deletion_protection_enabled = local.production
}

resource "aws_dynamodb_table" "state" {
  name         = "${local.prefix}-state"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"

  attribute {
    name = "pk"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  deletion_protection_enabled = local.production
}
