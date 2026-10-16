"""Generate validated Version 1 mapping YAML files for one customer source."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import APIError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.mapping_generator import generate_mapping, write_mapping_yaml  # noqa: E402


def _source_slug(source_system: str) -> str:
    return source_system.strip().lower().replace(" ", "_").replace("-", "_")


def _load_open_issues(path: Path | None, file_name: str) -> list[dict[str, Any]]:
    if path is None:
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    issues = data.get("open_issues", data) if isinstance(data, dict) else data
    if not isinstance(issues, list):
        raise ValueError("Open issues must be a JSON list or contain open_issues list.")
    selected = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        issue_file = issue.get("file_name") or issue.get("source_file")
        if issue_file in {None, file_name}:
            selected.append(issue)
    return selected


def _resolve_source_path(file_name: str) -> str:
    candidates = [
        PROJECT_ROOT / "data" / "examples" / "week1" / file_name,
        PROJECT_ROOT / "data" / "generated" / file_name,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.relative_to(PROJECT_ROOT).as_posix()
    return file_name


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", required=True, type=Path)
    parser.add_argument(
        "--schema", type=Path, default=PROJECT_ROOT / "schemas" / "unified-schema.json"
    )
    parser.add_argument("--source-system", required=True)
    parser.add_argument(
        "--open-issues",
        type=Path,
        default=PROJECT_ROOT / "outputs" / "multilingual-field-analysis-evaluation.json",
    )
    parser.add_argument(
        "--prompt",
        type=Path,
        default=PROJECT_ROOT / "docs" / "week3-task2-mapping-generator-prompt.md",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "outputs" / "mappings",
    )
    parser.add_argument("--model", help="OpenAI model override")
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env.local")
    load_dotenv(PROJECT_ROOT / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not configured.")

    analyses = json.loads(args.analysis.read_text(encoding="utf-8"))
    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    if isinstance(analyses, dict) and "file_name" in analyses:
        analyses = {analyses["file_name"]: analyses}
    if not isinstance(analyses, dict):
        raise SystemExit("Field-analysis input must be an object keyed by CSV file name.")

    slug = _source_slug(args.source_system)
    selected = [
        analysis
        for file_name, analysis in analyses.items()
        if file_name.lower().startswith(f"{slug}_")
    ]
    if not selected:
        raise SystemExit(
            f"No field analyses matching source system {args.source_system!r} were found."
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []
    for analysis in selected:
        file_name = analysis["file_name"]
        source_file = _resolve_source_path(file_name)
        issues = _load_open_issues(args.open_issues, file_name)
        try:
            mapping = generate_mapping(
                analysis,
                schema,
                args.source_system,
                source_file,
                issues,
                prompt_path=args.prompt,
                model=args.model,
            )
        except (APIError, ValueError) as error:
            raise SystemExit(f"Mapping generation failed for {file_name}: {error}") from error

        table_type = analysis["table_type"]
        output_path = args.output_dir / f"{slug}-{table_type}-mapping.yaml"
        write_mapping_yaml(mapping, output_path)
        generated.append(output_path)
        print(f"Generated {output_path.relative_to(PROJECT_ROOT)}")

    print(f"Completed {len(generated)} mapping file(s) for {args.source_system}.")


if __name__ == "__main__":
    main()

