# main.tf

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# Configure the AWS Provider
provider "aws" {
  region = "eu-central-1" # preferred AWS region
}

data "aws_caller_identity" "current" {}


# 1. AWS ECR (Elastic Container Registry) to store our Docker images
resource "aws_ecr_repository" "agent_repo" {
  name                 = "git-guardian-agent"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Project = "Git Guardian Agent"
  }
}

# 2. S3 Bucket for MLOps logging
resource "aws_s3_bucket" "agent_logs" {
  # Bucket names must be globally unique. Add a random suffix.
  bucket = "git-guardian-agent-logs-${random_id.bucket_suffix.hex}"

  tags = {
    Project = "Git Guardian Agent"
  }
}

# Prevents accidental deletion of the log bucket
resource "aws_s3_bucket_public_access_block" "agent_logs_access" {
  bucket = aws_s3_bucket.agent_logs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Adds a lifecycle rule to transition old logs to cheaper storage and eventually delete them
resource "aws_s3_bucket_lifecycle_configuration" "agent_logs_lifecycle" {
  bucket = aws_s3_bucket.agent_logs.id

  rule {
    id     = "log-retention"
    status = "Enabled"

    # This filter block tells the rule to apply to all objects in the bucket.
    filter {}

    transition {
      days          = 30
      storage_class = "STANDARD_IA" # Infrequent Access
    }

    expiration {
      days = 365
    }
  }
}

# Used to generate a unique suffix for the S3 bucket name
resource "random_id" "bucket_suffix" {
  byte_length = 8
}

# 3. IAM Role for GitHub Actions to securely authenticate with AWS using OIDC
data "aws_iam_policy_document" "github_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type = "Federated"
      # This now correctly constructs the ARN for the GitHub OIDC provider
      # It uses the account ID we fetched with the aws_caller_identity data source
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/token.actions.githubusercontent.com"]
    }

    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      # IMPORTANT: Make sure this still correctly points to your repository
      # Replace <YourGitHubOrg>/<YourRepoName> if you haven't already
      values = ["repo:franruedaesq/git-guardian-agent:*", "repo:franruedaesq/dummy-repo:*"]
    }


  }

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:user/qlora-user"]
    }
  }
}

resource "aws_iam_role" "github_actions_role" {
  name               = "GitGuardianAgent-GitHubActionsRole"
  assume_role_policy = data.aws_iam_policy_document.github_assume_role.json
}

# 4. IAM Policy defining what the GitHub Actions role is allowed to do
data "aws_iam_policy_document" "agent_permissions" {
  # ECR Permissions
  statement {
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  statement {
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:CompleteLayerUpload",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart"
    ]
    resources = [aws_ecr_repository.agent_repo.arn]
  }

  # Bedrock Permissions
  statement {
    effect = "Allow"
    actions = [
      "bedrock:InvokeModel"
    ]
    # This allows the role to invoke the specific Claude 3 Sonnet model
    resources = [
      "arn:aws:bedrock:eu-central-1:183611507583:inference-profile/eu.anthropic.claude-3-7-sonnet-20250219-v1:0",

      "arn:aws:bedrock:eu-north-1::foundation-model/anthropic.claude-3-7-sonnet-20250219-v1:0",

      "arn:aws:bedrock:*::foundation-model/anthropic.claude-3-7-sonnet-20250219-v1:0"
    ]
  }

  statement {
    effect = "Allow"
    actions = [
      "s3:PutObject"
    ]
    #  the /* at the end to allow writing objects inside the bucket
    resources = ["${aws_s3_bucket.agent_logs.arn}/*"]
  }
}

resource "aws_iam_policy" "github_actions_agent_policy" {
  name   = "GitGuardianAgent-GitHubActionsPolicy"
  policy = data.aws_iam_policy_document.agent_permissions.json
}

resource "aws_iam_role_policy_attachment" "attach_agent_policy" {
  role       = aws_iam_role.github_actions_role.name
  policy_arn = aws_iam_policy.github_actions_agent_policy.arn
}

# 5. Outputs - We'll need these values later
output "ecr_repository_url" {
  value       = aws_ecr_repository.agent_repo.repository_url
  description = "The URL of the ECR repository."
}

output "log_s3_bucket_name" {
  value       = aws_s3_bucket.agent_logs.bucket
  description = "The name of the S3 bucket for logging."
}

output "github_actions_iam_role_arn" {
  value       = aws_iam_role.github_actions_role.arn
  description = "The ARN of the IAM Role for GitHub Actions."
}

output "label_studio_access_key_id" {
  value       = aws_iam_access_key.label_studio_key.id
  description = "The Access Key ID for the Label Studio user."
}

output "label_studio_secret_key" {
  value       = aws_iam_access_key.label_studio_key.secret
  description = "The Secret Access Key for the Label Studio user."
  sensitive   = true # This prevents Terraform from showing it in normal output
}


# --- LABEL STUDIO RESOURCES ---

# 6. IAM User for Label Studio
# This creates a dedicated user account for the Label Studio application.
resource "aws_iam_user" "label_studio_user" {
  name = "label-studio-service-user"
  tags = {
    Project = "Git Guardian Agent"
  }
}

# 7. IAM Policy for the Label Studio User
# This policy grants the exact permissions needed to read logs and write annotations.
data "aws_iam_policy_document" "label_studio_s3_policy_document" {
  statement {
    sid    = "LabelStudioS3Access"
    effect = "Allow"
    actions = [
      "s3:ListBucket",
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject"
    ]
    resources = [
      aws_s3_bucket.agent_logs.arn,
      "${aws_s3_bucket.agent_logs.arn}/*" # Important: grants access to objects within the bucket
    ]
  }
}

resource "aws_iam_policy" "label_studio_s3_policy" {
  name   = "LabelStudio-S3-Policy"
  policy = data.aws_iam_policy_document.label_studio_s3_policy_document.json
}

# 8. Attach the policy to the user
resource "aws_iam_user_policy_attachment" "label_studio_attach" {
  user       = aws_iam_user.label_studio_user.name
  policy_arn = aws_iam_policy.label_studio_s3_policy.arn
}

# 9. Create an Access Key for the user
# This generates the credentials Label Studio will use to authenticate.
resource "aws_iam_access_key" "label_studio_key" {
  user = aws_iam_user.label_studio_user.name
}

# 10. CORS Configuration for the S3 Logging Bucket
# This allows the Label Studio web interface to directly access bucket data.
resource "aws_s3_bucket_cors_configuration" "agent_logs_cors" {
  bucket = aws_s3_bucket.agent_logs.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "HEAD"] # GET is sufficient as per docs, but HEAD is good practice
    allowed_origins = ["*"]           # For local testing; for production, change to your Label Studio URL
    expose_headers  = ["ETag"]
    max_age_seconds = 3000
  }
}
