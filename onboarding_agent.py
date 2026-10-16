"""Command-line entry point for the existing Python onboarding workflow."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.onboarding_agent import OnboardingAgent, PROJECT_ROOT


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-system", required=True, help="Source label; keep consistent with any reused mappings")
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True, help="New or empty directory; previous runs are never overwritten")
    schema = parser.add_mutually_exclusive_group()
    schema.add_argument("--schema", type=Path, default=PROJECT_ROOT / "schemas/unified-schema.json", help="Reviewed shared schema included in the repository (default)")
    schema.add_argument("--recommend-schema", action="store_true", help="Explicitly draft a new schema from this run's analyses")
    parser.add_argument("--customer-csv", type=Path, help="Explicit path for nonstandard customer filename")
    parser.add_argument("--order-csv", type=Path, help="Explicit path for nonstandard order filename")
    parser.add_argument("--analysis", type=Path, nargs="+", help="Explicitly reuse analysis JSON instead of calling FieldAnalyzer's LLM")
    parser.add_argument("--mapping-dir", type=Path, help="Explicitly reuse mappings instead of calling MappingGenerator's LLM")
    parser.add_argument("--sample-size", type=int, default=100)
    parser.add_argument("--model", help="Optional model override for live LLM stages")
    args = parser.parse_args()
    load_dotenv(PROJECT_ROOT / ".env.local")
    load_dotenv(PROJECT_ROOT / ".env")
    agent = OnboardingAgent(args.source_system, args.input_dir, args.output_dir,
        schema_path=None if args.recommend_schema else args.schema,
        customer_csv=args.customer_csv, order_csv=args.order_csv,
        analysis_paths=args.analysis, mapping_dir=args.mapping_dir,
        sample_size=args.sample_size, model=args.model)
    try:
        log = agent.run()
    except (OSError, ValueError) as error:
        print(f"Cannot start onboarding: {error}", file=sys.stderr)
        return 1
    print(f"{args.source_system}: {log['status']}")
    for step in log["steps"]:
        print(f"  {step['name']}: {step['status']} ({step['mode']})")
    print(f"Run log: {agent.log_path}")
    if log["status"] == "failed":
        print(f"Failed step: {log['failed_step']}: {log['errors'][-1]['message']}", file=sys.stderr)
        print("Completed artifacts were kept. Inspect the run log before retrying in a new output directory.", file=sys.stderr)
        return 1
    print("Draft outputs only. Loading is disabled; review findings remain visible.")
    for label, path in log["final_outputs"].items():
        print(f"  {label}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
