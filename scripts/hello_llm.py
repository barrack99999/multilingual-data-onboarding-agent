"""Make one API call and print a structured JSON response."""

import json
import os
import sys

from dotenv import load_dotenv
from openai import APIError, OpenAI


OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "message": {"type": "string"},
        "project": {"type": "string"},
        "api_working": {"type": "boolean"},
    },
    "required": ["message", "project", "api_working"],
    "additionalProperties": False,
}


def main() -> None:
    load_dotenv()

    if not os.getenv("OPENAI_API_KEY"):
        print(
            "OPENAI_API_KEY is not configured. Copy .env.example to .env "
            "and add your key when API access becomes available."
        )
        sys.exit(1)

    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    client = OpenAI()

    try:
        response = client.responses.create(
            model=model,
            instructions=(
                "You are a test assistant for a data onboarding project. "
                "Return only the requested structured result."
            ),
            input=(
                "Confirm that the API call worked. Use the message "
                "'Hello from the data onboarding project!' and identify the "
                "project as 'data onboarding'."
            ),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "hello_llm_result",
                    "strict": True,
                    "schema": OUTPUT_SCHEMA,
                }
            },
            store=False,
        )
    except APIError as error:
        print(f"API call failed: {error}")
        sys.exit(1)

    result = json.loads(response.output_text)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
