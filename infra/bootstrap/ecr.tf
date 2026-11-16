# One shared repo for both envs. Each commit pushes two images (ruling R9):
# <sha> (api target) and <sha>-jobs (jobs target). Production promotes the
# digest staging pushed; it never builds.

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

  # 60 images = the last 30 commits (api + jobs each).
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 60 images (30 commits x api + jobs)"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 60
      }
      action = { type = "expire" }
    }]
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
