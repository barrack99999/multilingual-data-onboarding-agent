"""Compare repeated structured outputs at low and high temperatures."""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import APIError, OpenAI


OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "target_field": {"type": "string"},
        "data_type": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["target_field", "data_type", "reason"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You help map source CSV fields to a standard data model. "
    "Return only the requested structured result."
)

USER_PROMPT = (
    "Map the U.S. customer CSV field 'signup_dt'. Sample values are "
    "'2024-01-15', '01/22/2024', and '2024/02/03'. Suggest one target "
    "field, one data type, and a short reason."
)


def run_experiment(runs: int) -> list[dict]:
    client = OpenAI()
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    results = []

    for temperature in (0.0, 1.2):
        for run_number in range(1, runs + 1):
            response = client.responses.create(
                model=model,
                instructions=SYSTEM_PROMPT,
                input=USER_PROMPT,
                temperature=temperature,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "field_mapping",
                        "strict": True,
                        "schema": OUTPUT_SCHEMA,
                    }
                },
                store=False,
            )
            results.append(
                {
                    "temperature": temperature,
                    "run": run_number,
                    "output": json.loads(response.output_text),
                }
            )

    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument(
        "--output",
        default="outputs/temperature-results.json",
    )
    args = parser.parse_args()

    if args.runs < 1:
        parser.error("--runs must be at least 1")

    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not configured in .env")
        sys.exit(1)

    try:
        results = run_experiment(args.runs)
    except APIError as error:
        print(f"API experiment failed: {error}")
        sys.exit(1)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2) + "\n")

    print(json.dumps(results, indent=2))
    print(f"\nSaved results to {output_path}")


if __name__ == "__main__":
    main()
