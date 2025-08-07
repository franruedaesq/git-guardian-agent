# Git Guardian Agent ✨

[![Build Status](https://github.com/franruedaesq/git-guardian-agent/actions/workflows/build-agent.yml/badge.svg)](https://github.com/franruedaesq/git-guardian-agent/actions/workflows/build-agent.yml)
[![Version](https://img.shields.io/badge/version-v1.1.0-blue)](https://github.com/franruedaesq/git-guardian-agent)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

An autonomous agent that integrates directly into your CI/CD pipeline to act as an automated quality and security gate. It solves two critical problems at the earliest stage of development: inconsistent commit messaging and accidental secret leakage.

The agent provides immediate, intelligent feedback within the developer's workflow, enhancing both development velocity and security posture.

---

## How It Works

The Git Guardian Agent is a self-contained, Dockerized Python application with a hybrid analysis engine:

1.  **Regex Pre-scan:** It first performs a rapid scan for obvious, high-confidence secret patterns (like AWS keys).
2.  **LLM Analysis:** It then uses a powerful Large Language Model (**Anthropic Claude 3.7 Sonnet** via AWS Bedrock) to perform a nuanced analysis of both the commit message format and the code changes for more subtle secrets.
3.  **Reusable Workflow:** The entire process is wrapped in a reusable GitHub Actions workflow, allowing any team to adopt it with just a few lines of YAML.
4.  **Observability & Logging:** Every decision is logged to an AWS S3 bucket for auditing, and key performance metrics (execution time, pass/fail counts) are pushed to a Prometheus Pushgateway for real-time monitoring.

---

## 🚀 Quick Start & Usage

To integrate the Git Guardian Agent into your repository, follow these two steps.

### Step 1: Configure Repository Secrets

In your GitHub repository, go to `Settings` > `Secrets and variables` > `Actions` and add the following repository secrets:

- `AWS_IAM_ROLE_ARN`: The ARN of the IAM Role the action will assume. This role must have permissions for `bedrock:InvokeModel` and `s3:PutObject`.
- `S3_LOG_BUCKET`: The name of the AWS S3 bucket where the agent will store its decision logs.
- `PUSHGATEWAY_URL`: (Optional) The URL of your Prometheus Pushgateway for metrics (e.g., `http://your-gateway.com:9091`).

### Step 2: Create the Workflow File

In your repository, create a new file at `.github/workflows/guardian-check.yml` and paste the following content.

```yaml
name: Git Guardian Check

on: [push]

permissions:
  id-token: write # Required to authenticate with AWS OIDC
  contents: read # Required to checkout the code

jobs:
  guardian-check:
    # This calls the centralized, reusable workflow from the main agent repository.
    # Be sure to use your GitHub username/organization.
    uses: franruedaesq/git-guardian-agent/.github/workflows/reusable-agent-check.yml@main
    with:
      # You can pin to a specific version or use 'latest'
      agent_tag: "latest"
    secrets:
      # This securely passes your repository's secrets to the reusable workflow.
      AWS_IAM_ROLE_ARN: ${{ secrets.AWS_IAM_ROLE_ARN }}
      S3_LOG_BUCKET: ${{ secrets.S3_LOG_BUCKET }}
      PUSHGATEWAY_URL: ${{ secrets.PUSHGATEWAY_URL }}
```

That's it! On the next `git push`, the Git Guardian Agent will automatically analyze your commit. If it fails, the CI pipeline will be blocked, and the reason will be clearly displayed in the action's logs.
