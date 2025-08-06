# tests/test_agent.py
import json

import pytest

from src.agent import GuardianAgent

# A sample of a perfect commit input
GOOD_COMMIT_DATA = {
    "commit_message": "feat(api): add new endpoint for user profiles",
    "commit_diff": "--- a/users.js\n+++ b/users.js\n-    return 'hello';\n+    return 'world';",
}

# A sample of a commit with a bad message format
BAD_MESSAGE_DATA = {
    "commit_message": "added user profiles",
    "commit_diff": "--- a/users.js\n+++ b/users.js\n-    return 'hello';\n+    return 'world';",
}

# A sample of a commit with a blatant AWS key
SECRET_IN_DIFF_DATA = {
    "commit_message": "fix(config): update production settings",
    "commit_diff": "--- a/config.py\n+++ b/config.py\n+ AWS_ACCESS_KEY_ID = 'AKIAIOSFODNN7EXAMPLE'",
}


@pytest.fixture
def agent():
    """Provides a GuardianAgent instance for testing."""
    return GuardianAgent()


def test_regex_scan_detects_secret(agent, tmp_path):
    """Ensure the initial regex scan catches obvious secrets."""
    p = tmp_path / "commit_data.json"
    p.write_text(json.dumps(SECRET_IN_DIFF_DATA))

    # We expect the regex scan to catch this, so no LLM call should be made.
    result = agent.analyze(p)

    assert result["status"] == "FAIL"
    assert "AWS Access Key" in result["reason"]


def test_llm_pass_on_good_commit(agent, tmp_path, mocker):
    """Test a perfect commit that should pass the LLM check."""
    # Mock the LLM's response to simulate a PASS
    mocker.patch.object(
        agent,
        "_invoke_llm",
        return_value={"status": "PASS", "reason": "All checks passed."},
    )

    p = tmp_path / "commit_data.json"
    p.write_text(json.dumps(GOOD_COMMIT_DATA))

    result = agent.analyze(p)

    assert result["status"] == "PASS"
    agent._invoke_llm.assert_called_once()  # Verify the LLM was indeed called


def test_llm_fail_on_bad_message(agent, tmp_path, mocker):
    """Test a commit with a bad message that should fail the LLM check."""
    # Mock the LLM's response to simulate a FAIL for the commit message
    mocker.patch.object(
        agent,
        "_invoke_llm",
        return_value={
            "status": "FAIL",
            "reason": "Commit Message Compliance Failed: The message does not follow Conventional Commits format.",
        },
    )

    p = tmp_path / "commit_data.json"
    p.write_text(json.dumps(BAD_MESSAGE_DATA))

    result = agent.analyze(p)

    assert result["status"] == "FAIL"
    assert "Conventional Commits" in result["reason"]
    agent._invoke_llm.assert_called_once()
