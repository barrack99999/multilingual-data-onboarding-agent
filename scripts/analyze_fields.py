"""Analyze CSV field meanings from a compact profile."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import APIError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.csv_profiler import profile_csv  # noqa: E402
from src.field_analyzer import analyze_fields  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--profile", type=Path, help="Existing profile JSON")
    parser.add_argument("--output", type=Path, help="Where to save analysis JSON")
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not configured in .env.")

    if args.profile:
        profile = json.loads(args.profile.read_text(encoding="utf-8"))
    else:
        profile = profile_csv(args.csv_path)

    try:
        result = analyze_fields(args.csv_path, profile)
    except APIError as error:
        raise SystemExit(f"OpenAI API call failed: {error}") from error

    json_text = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json_text, encoding="utf-8")
        print(f"Saved field analysis to {args.output}")
    else:
        print(json_text, end="")


if __name__ == "__main__":
    main()
