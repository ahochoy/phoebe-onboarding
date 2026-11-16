# One shared repo for both envs. Each commit pushes two images (ruling R9):
# <sha> (api target) and <sha>-jobs (jobs target). Production promotes the
# digest staging pushed; it never builds, it only adds release-<git tag> tags.

resource "aws_ecr_repository" "api" {
  name                 = "phoebe-api"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "api" {
  repository = aws_ecr_repository.api.name

  # Ruling R13. ECR can only expire, so rule 1 "keeps" release images by
  # selecting them with a count they will never reach. ECR documents that an
  # image matched by a higher-priority rule is not expired by a lower one, so
  # rule 2 (tagStatus any, which must be last) skips them. Rule 2 then expires
  # everything else beyond the newest 60 (30 commits x api + jobs).
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Never expire release images (release-<git tag>, release-<git tag>-jobs)"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["release-"]
          countType     = "imageCountMoreThan"
          countNumber   = 10000
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Expire all other images beyond the newest 60"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 60
        }
        action = { type = "expire" }
      },
    ]
  })
}

# Lambda pulls the image with its service principal; granting it here means the
# deploy roles never need ecr:SetRepositoryPolicy.
resource "aws_ecr_repository_policy" "api" {
  repository = aws_ecr_repository.api.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "LambdaPull"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
      Condition = {
        StringLike = { "aws:sourceArn" = "arn:aws:lambda:${local.region}:${local.account_id}:function:phoebe-*" }
      }
    }]
  })
}
