"""Run the simplified mini agent from the command line."""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

# Allow this script to import code from the project's src directory.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.mini_agent import ask_agent  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask the mini CSV agent a question.")
    parser.add_argument("question", help="Question for the agent")
    parser.add_argument("--trace", action="store_true", help="Show tool activity")
    args = parser.parse_args()

    load_dotenv()
    result = ask_agent(args.question, show_trace=args.trace)

    print(result["answer"])
    print("Tools used:", ", ".join(result["tools_used"]) or "none")


if __name__ == "__main__":
    main()
