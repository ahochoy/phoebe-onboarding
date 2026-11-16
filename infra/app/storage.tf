# Bucket names (ruling R2): phoebe-<env>-site-<account_id>, phoebe-<env>-uploads-<account_id>.

# ---- Uploads: sandbox blobs under uploads/<session_id>/ ---------------------

resource "aws_s3_bucket" "uploads" {
  bucket        = "${local.prefix}-uploads-${local.account_id}"
  force_destroy = !local.production
}

resource "aws_s3_bucket_ownership_controls" "uploads" {
  bucket = aws_s3_bucket.uploads.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "uploads" {
  bucket = aws_s3_bucket.uploads.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "uploads" {
  bucket = aws_s3_bucket.uploads.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Sandboxes live at most 24 h and the sweeper deletes their blobs; this catches
# any blob a failed sweep left behind.
resource "aws_s3_bucket_lifecycle_configuration" "uploads" {
  bucket = aws_s3_bucket.uploads.id

  rule {
    id     = "expire-uploads"
    status = "Enabled"

    filter {}

    expiration {
      days = 2
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

# ---- Site: the SPA (and staging's previews/). Private; Task 6 adds the
# bucket policy that lets only this env's CloudFront distribution (OAC) read it.

resource "aws_s3_bucket" "site" {
  bucket        = "${local.prefix}-site-${local.account_id}"
  force_destroy = !local.production
}

resource "aws_s3_bucket_ownership_controls" "site" {
  bucket = aws_s3_bucket.site.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "site" {
  bucket = aws_s3_bucket.site.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "site" {
  bucket = aws_s3_bucket.site.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}
