# CloudFront edge: the SPA from the private site bucket (OAC), /api/* to the
# function URL, one security headers policy on both. Default *.cloudfront.net
# certificate only: no aliases, ACM or Route 53. CloudFront Functions only (no
# Lambda@Edge). The distribution is global; everything else is in us-east-2.

locals {
  # AWS managed policies, by ID (they are not resources we own).
  cache_policy_caching_optimized = "658327ea-f89d-4fab-a63d-7e88639e58f6"
  cache_policy_caching_disabled  = "4135ea2d-6df8-47a0-9b3a-6c3fd7bf9d80"
  # Every viewer header, cookie and query string except Host (a function URL
  # needs its own Host). The AWS docs also list the CloudFront-* viewer headers
  # (CloudFront-Viewer-Address, which the API reads for the client IP) as part of it.
  origin_request_policy_all_viewer_except_host = "b689b0a8-53d0-40ab-baf2-68738e2966ac"

  api_origin_domain = trimsuffix(trimprefix(aws_lambda_function_url.api.function_url, "https://"), "/")

  csp = join("; ", [
    "default-src 'self'",
    "img-src 'self' data:",
    "style-src 'self' 'unsafe-inline'",
    "connect-src 'self'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ])
}

resource "aws_cloudfront_function" "spa_router" {
  name    = "${local.prefix}-spa-router"
  runtime = "cloudfront-js-2.0"
  comment = "SPA fallback and /pr-<n>/ preview routing (viewer-request, S3 behaviour only)."
  publish = true
  code    = file("${path.module}/functions/spa_router.js")
}

resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "${local.prefix}-site"
  description                       = "OAC for the ${local.prefix} site bucket."
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_response_headers_policy" "security" {
  name    = "${local.prefix}-security-headers"
  comment = "CSP, HSTS, nosniff and referrer policy for the SPA and the API."

  security_headers_config {
    content_security_policy {
      content_security_policy = local.csp
      override                = true
    }

    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = false
      preload                    = false
      override                   = true
    }

    content_type_options {
      override = true
    }

    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = true
    }
  }
}

resource "aws_cloudfront_distribution" "main" {
  comment             = "${local.prefix}: SPA, previews and API"
  enabled             = true
  is_ipv6_enabled     = true
  http_version        = "http2and3"
  price_class         = "PriceClass_100"
  default_root_object = "index.html"

  origin {
    origin_id                = "site"
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }

  origin {
    origin_id   = "api"
    domain_name = local.api_origin_domain

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
      # Streaming answers can idle between tokens; 60 s is the CloudFront maximum without a quota request.
      origin_read_timeout = 60
    }

    # The API's origin guard rejects requests without this header (except /api/health).
    custom_header {
      name  = "X-Phoebe-Origin"
      value = random_password.origin.result
    }
  }

  default_cache_behavior {
    target_origin_id           = "site"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = local.cache_policy_caching_optimized
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.spa_router.arn
    }
  }

  ordered_cache_behavior {
    path_pattern     = "/api/*"
    target_origin_id = "api"
    allowed_methods  = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods   = ["GET", "HEAD"]
    # Compression would buffer the SSE stream.
    compress                   = false
    viewer_protocol_policy     = "redirect-to-https"
    cache_policy_id            = local.cache_policy_caching_disabled
    origin_request_policy_id   = local.origin_request_policy_all_viewer_except_host
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

# Only this distribution (OAC) may read the site bucket.
resource "aws_s3_bucket_policy" "site" {
  bucket = aws_s3_bucket.site.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowCloudFrontRead"
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.site.arn}/*"
      Condition = {
        StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.main.arn }
      }
    }]
  })

  depends_on = [aws_s3_bucket_public_access_block.site]
}
