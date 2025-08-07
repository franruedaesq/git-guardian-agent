import json
import os
import re
import sys
import time  # New import
from datetime import datetime, timezone

import boto3

# New imports from prometheus_client
from prometheus_client import CollectorRegistry, Counter, Gauge, push_to_gateway


class GuardianAgent:
    def __init__(
        self,
        model_id=(
            "arn:aws:bedrock:eu-central-1:"
            "183611507583:inference-profile/"
            "eu.anthropic.claude-3-7-sonnet-20250219-v1:0"
        ),
        region="eu-central-1",
    ):
        self.model_id = model_id
        self.bedrock_client = boto3.client(
            service_name="bedrock-runtime", region_name=region
        )
        self.s3_client = boto3.client("s3")
        self.log_bucket = os.getenv("S3_LOG_BUCKET")
        self.pushgateway_url = os.getenv("PUSHGATEWAY_URL")

    def _push_metrics(self, duration, decision, repo_name):
        """Pushes execution metrics to a Prometheus Pushgateway."""
        if not self.pushgateway_url:
            print(
                "Warning: PUSHGATEWAY_URL not set. Skipping metrics push.",
                file=sys.stderr,
            )
            return

        registry = CollectorRegistry()

        g = Gauge(
            "agent_execution_duration_seconds",
            "Time taken for the agent to complete analysis",
            registry=registry,
        )
        g.set(duration)

        c = Counter(
            "agent_decisions_total",
            "Total number of agent decisions",
            ["status", "repository"],
            registry=registry,
        )
        c.labels(status=decision.get("status", "ERROR"), repository=repo_name).inc()

        try:
            push_to_gateway(
                self.pushgateway_url, job="git-guardian-agent", registry=registry
            )
            print(
                f"Successfully pushed metrics to {self.pushgateway_url}",
                file=sys.stderr,
            )
        except Exception as e:
            print(f"Error pushing metrics to Pushgateway: {str(e)}", file=sys.stderr)

    def _upload_log_to_s3(self, log_data):
        """Uploads the detailed transaction log to S3."""
        if not self.log_bucket:
            # Send this warning to stderr
            print(
                "Warning: S3_LOG_BUCKET environment variable not set. Skipping log upload.",
                file=sys.stderr,
            )
            return

        commit_hash = log_data["input"]["commit_hash"]
        log_key = f"{commit_hash}.json"

        try:
            self.s3_client.put_object(
                Bucket=self.log_bucket,
                Key=log_key,
                Body=json.dumps(log_data, indent=2),
                ContentType="application/json",
            )
            # Send this success message to stderr
            print(
                f"Successfully uploaded log to s3://{self.log_bucket}/{log_key}",
                file=sys.stderr,
            )
        except Exception as e:
            # Send this error message to stderr
            print(f"Error uploading log to S3: {str(e)}", file=sys.stderr)

    def _read_input(self, filepath):
        """Reads the input JSON file containing commit data."""
        with open(filepath, "r") as f:
            return json.load(f)

    def _run_regex_scan(self, diff_text):
        """Performs a quick, deterministic regex scan for obvious secrets."""
        # AWS Access Key ID pattern
        aws_key_pattern = re.compile(r"(?<![A-Z0-9])[A-Z0-9]{20}(?![A-Z0-9])")

        # A simple pattern for high-entropy strings in quotes (30+ alphanumeric chars)
        generic_secret_pattern = re.compile(r'["\'][a-zA-Z0-9]{30,}["\']')

        if aws_key_pattern.search(diff_text):
            return "Failed: A pattern resembling an AWS Access Key was found."
        if generic_secret_pattern.search(diff_text):
            return "Failed: A high-entropy string resembling a secret was found."

        return None

    def _construct_prompt(self, commit_message, diff_text):
        """Constructs the detailed prompt for the LLM."""
        return f"""
        Human: You are 'Guardian,' an expert senior software engineer performing a pre-check on a git commit. You are meticulous, helpful, and concise.
        You will receive a JSON object containing a commit message and a code diff. Your task is to analyze them based on two criteria: Commit Message Compliance and Secret Detection.

        <commit_data>
        <commit_message>{commit_message}</commit_message>
        <diff_text>
        {diff_text}
        </diff_text>
        </commit_data>

        Your analysis rules are:
        1.  **Commit Message Compliance**: The commit message MUST follow the Conventional Commits specification. It must start with a type like 'feat:', 'fix:', 'chore:', 'docs:', 'refactor:', etc., followed by a concise, descriptive subject.
        2.  **Secret Detection**: Scrutinize the code diff for any hardcoded secrets. This includes, but is not limited to, API tokens, database connection strings, private keys, and high-entropy strings within quotation marks. Be extra vigilant.

        Your response MUST be a single, valid JSON object with NO other text before or after it.
        The JSON object must have two fields: "status" ('PASS' or 'FAIL') and "reason" (a brief, helpful explanation for the developer if it fails, explaining what is wrong and how to fix it). If multiple issues exist, report the most critical one first (secrets are more critical than message format).

        Assistant:
        """

    def _invoke_llm(self, prompt):
        """Invokes the Bedrock LLM and parses the response."""
        body = json.dumps(
            {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 500,
                "messages": [{"role": "user", "content": prompt}],
            }
        )

        try:
            response = self.bedrock_client.invoke_model(
                body=body, modelId=self.model_id
            )
            response_body = json.loads(response.get("body").read())
            # The actual response is nested inside the 'content' list
            llm_output_text = response_body["content"][0]["text"]
            # The LLM should return a JSON string, so we parse it.
            return json.loads(llm_output_text)
        except Exception as e:
            # If the LLM fails or returns malformed JSON, we fail safe
            return {
                "status": "FAIL",
                "reason": f"Internal agent error: Could not process LLM response. Details: {str(e)}",
            }

    def analyze(self, filepath):
        """Main analysis method."""
        start_time = time.time()
        input_data = self._read_input(filepath)

        repo_name = input_data.get("repository_name", "unknown_repo")
        try:
            commit_message = input_data.get("commit_message", "")
            diff_text = input_data.get("commit_diff", "")

            regex_result = self._run_regex_scan(diff_text)
            if regex_result:
                decision = {"status": "FAIL", "reason": regex_result}
            else:
                prompt = self._construct_prompt(commit_message, diff_text)
                decision = self._invoke_llm(prompt)

        except Exception as e:
            decision = {"status": "FAIL", "reason": f"Internal agent error: {str(e)}"}

        # NEW: Construct and upload the final log
        log_data = {
            "input": input_data,
            "decision": decision,
            "metadata": {
                "agent_version": "1.1.0",  # We can version our agent
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            },
        }
        self._upload_log_to_s3(log_data)
        duration = time.time() - start_time
        self._push_metrics(duration, decision, repo_name)

        return decision
