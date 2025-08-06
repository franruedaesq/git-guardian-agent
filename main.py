# main.py
import json
import sys

from src.agent import GuardianAgent

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "reason": "Usage: python main.py <path_to_input.json>",
                }
            )
        )
        sys.exit(1)

    input_filepath = sys.argv[1]

    agent = GuardianAgent()
    final_decision = agent.analyze(input_filepath)

    # Print the final JSON decision to stdout
    print(json.dumps(final_decision, indent=2))

    # Exit with a non-zero status code if the check failed
    if final_decision.get("status") == "FAIL":
        sys.exit(1)
