"""Command-line entry point for the plain-code CSV profiler."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.csv_profiler import profile_csv  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path, help="CSV file to profile")
    parser.add_argument("--output", type=Path, help="Optional JSON output file")
    parser.add_argument("--sample-size", type=int, default=5)
    parser.add_argument("--top-n", type=int, default=5)
    args = parser.parse_args()

    profile = profile_csv(
        args.csv_path,
        sample_size=args.sample_size,
        top_n=args.top_n,
    )
    json_text = json.dumps(profile, indent=2, ensure_ascii=False) + "\n"

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json_text, encoding="utf-8")
        print(f"Saved CSV profile to {args.output}")
    else:
        print(json_text, end="")


if __name__ == "__main__":
    main()
