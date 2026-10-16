"""A minimal agent with one local CSV inspection tool."""

import csv
import json
import os
from pathlib import Path
from typing import Any

from openai import OpenAI


CSV_TOOL = {
    "type": "function",
    "name": "get_csv_info",
    "description": (
        "Read a CSV file and return its row count, column names, and first "
        "three data rows. Use this when a question requires inspecting a CSV."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the CSV file to inspect.",
            }
        },
        "required": ["file_path"],
        "additionalProperties": False,
    },
    "strict": True,
}


def get_csv_info(file_path: str) -> dict[str, Any]:
    """Return basic information about a CSV without using an LLM."""
    path = Path(file_path).expanduser()
    if path.suffix.lower() != ".csv":
        return {"error": "The file must have a .csv extension."}
    if not path.is_file():
        return {"error": f"CSV file not found: {path}"}

    with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        if reader.fieldnames is None:
            return {"error": "The CSV does not contain a header row."}

        row_count = 0
        sample_rows = []
        for row in reader:
            row_count += 1
            if len(sample_rows) < 3:
                sample_rows.append(dict(row))

    return {
        "file_name": path.name,
        "row_count": row_count,
        "column_names": reader.fieldnames,
        "sample_rows": sample_rows,
    }


def ask_agent(question: str, *, show_trace: bool = False) -> dict[str, Any]:
    """Ask the model a question and run get_csv_info if it requests the tool."""
    client = OpenAI()
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    input_items: list[dict[str, Any]] = [{"role": "user", "content": question}]
    tools_used: list[str] = []

    for _ in range(3):
        response = client.responses.create(
            model=model,
            instructions=(
                "You are a small learning agent. Answer greetings directly. "
                "When a question requires facts from a CSV file, call "
                "get_csv_info. Clearly summarize the tool result."
            ),
            input=input_items,
            tools=[CSV_TOOL],
            store=False,
        )

        # Preserve all model output items before returning tool results.
        input_items.extend(
            item.model_dump(exclude_none=True) for item in response.output
        )
        calls = [item for item in response.output if item.type == "function_call"]

        if not calls:
            return {
                "answer": response.output_text,
                "tools_used": tools_used,
            }

        for call in calls:
            if call.name != "get_csv_info":
                raise ValueError(f"Unknown tool requested: {call.name}")

            arguments = json.loads(call.arguments)
            tool_result = get_csv_info(arguments["file_path"])
            tools_used.append(call.name)

            if show_trace:
                print(f"Tool requested: {call.name}")
                print(json.dumps(tool_result, indent=2))

            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(tool_result),
                }
            )

    raise RuntimeError("The agent did not finish within three model turns.")
