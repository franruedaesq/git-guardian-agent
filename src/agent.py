# src/agent.py
import json
import re

import boto3


class GuardianAgent:
    def __init__(
        self,
        model_id="arn:aws:bedrock:eu-central-1:183611507583:inference-profile/eu.anthropic.claude-3-7-sonnet-20250219-v1:0",
        region="eu-central-1",
    ):
        self.model_id = model_id
        self.bedrock_client = boto3.client(
            service_name="bedrock-runtime", region_name=region
        )

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
        try:
            data = self._read_input(filepath)
            commit_message = data.get("commit_message", "")
            diff_text = data.get("commit_diff", "")

            # 1. Hybrid Approach: Run fast regex scan first
            regex_result = self._run_regex_scan(diff_text)
            if regex_result:
                return {"status": "FAIL", "reason": regex_result}

            # 2. If regex passes, use the more intelligent LLM
            prompt = self._construct_prompt(commit_message, diff_text)
            result = self._invoke_llm(prompt)
            return result

        except Exception as e:
            return {"status": "FAIL", "reason": f"Internal agent error: {str(e)}"}
