"""Run the two required live tests for the simplified mini agent."""

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.mini_agent import ask_agent  # noqa: E402


def main() -> None:
    load_dotenv()
    csv_path = PROJECT_ROOT / "data" / "customer_a_customers.csv"

    cases = [
        {
            "name": "Greeting without a tool",
            "question": "Hello! Briefly introduce yourself.",
            "expected_tools": [],
        },
        {
            "name": "CSV question with a tool",
            "question": (
                f"Inspect the CSV at {csv_path}. Tell me the row count and "
                "column names."
            ),
            "expected_tools": ["get_csv_info"],
        },
    ]

    results = []
    for case in cases:
        result = ask_agent(case["question"], show_trace=True)
        passed = result["tools_used"] == case["expected_tools"]
        results.append({"case": case["name"], "passed": passed, **result})
        print(f"\n{case['name']}: {'PASS' if passed else 'FAIL'}")
        print(result["answer"])

    output_path = PROJECT_ROOT / "outputs" / "mini-agent-test-results.json"
    output_path.write_text(json.dumps(results, indent=2) + "\n")

    if not all(result["passed"] for result in results):
        raise SystemExit(1)

    print(f"\nSaved results to {output_path}")


if __name__ == "__main__":
    main()
