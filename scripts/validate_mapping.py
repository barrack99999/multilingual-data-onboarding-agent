"""Try one or all mapping YAML files on source CSV sample rows."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.mapping_validator import UniqueKeyLoader, validate_sample_mapping  # noqa: E402


def save_json(path: Path, value: dict) -> None:
    """Replace a report only after it was successfully serialized."""
    text = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", nargs="?", type=Path, help="Source CSV to test")
    parser.add_argument("mapping_path", nargs="?", type=Path, help="Mapping YAML to execute")
    parser.add_argument("--all", action="store_true", help="Test all six outputs/mappings YAMLs")
    parser.add_argument("--sample-size", type=int, default=20, help="First N data rows, default 20")
    parser.add_argument("--schema", type=Path, default=PROJECT_ROOT / "schemas/unified-schema.json")
    parser.add_argument("--output", type=Path, help="Report path for one mapping (not --all)")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "outputs/mapping-validation")
    parser.add_argument("--preview-review-currency", action="store_true",
                        help="Show fictional fixed-rate previews; review rules stay unapproved")
    args = parser.parse_args()
    if args.sample_size < 1:
        parser.error("--sample-size must be positive.")
    if args.all:
        if args.csv_path or args.mapping_path or args.output:
            parser.error("Use --all by itself, or provide a CSV and mapping with --output.")
        paths = sorted((PROJECT_ROOT / "outputs/mappings").glob("*-mapping.yaml"))
        if not paths:
            parser.error("No mapping YAML files found in outputs/mappings.")
    else:
        if args.csv_path is None or args.mapping_path is None:
            parser.error("Provide csv_path and mapping_path, or use --all.")
        paths = [args.mapping_path]

    summary_items, blocked = [], False
    for mapping_path in paths:
        output = args.output or args.output_dir / f"{mapping_path.stem}-validation.json"
        try:
            if args.all:
                mapping = yaml.load(mapping_path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
                csv_path = Path(mapping["source_file"])
                if not csv_path.is_absolute():
                    csv_path = PROJECT_ROOT / csv_path
            else:
                csv_path = args.csv_path
            report = validate_sample_mapping(csv_path, mapping_path, args.schema,
                                            sample_size=args.sample_size,
                                            preview_review_currency=args.preview_review_currency)
        except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError) as error:
            print(f"ERROR {mapping_path.name}: {error}", file=sys.stderr)
            save_json(Path(str(output) + ".diagnostics.json"), {
                "contract_version": "1.3", "module": "MappingValidator", "status": "error",
                "errors": [{"code": "INPUT_ERROR", "message": str(error),
                            "location": str(mapping_path), "retryable": False}], "warnings": [],
            })
            blocked = True
            summary_items.append({"mapping": str(mapping_path), "status": "error", "message": str(error)})
            continue
        save_json(output, report)
        save_json(Path(str(output) + ".diagnostics.json"), {
            "contract_version": "1.3", "module": "MappingValidator", "status": report["status"],
            "errors": report["errors"], "warnings": report["warnings"],
        })
        counts = report["summary"]
        print(f"{mapping_path.name}: {counts['rules_passed']} passed, "
              f"{counts['rules_failed']} failed, {counts['rules_manual_review']} manual review "
              f"({report['sampling']['rows_checked']} CSV rows)")
        for rule in report["rules"]:
            if rule["rows_with_warnings"]:
                print(f"  {rule['target_field']}: {rule['rows_with_warnings']} row(s) handled with warnings")
            if rule["status"] == "failed":
                print(f"  FAILED {rule['target_field']}: see example, configuration, and row results")
        print(f"  Report: {output}")
        blocked |= bool(counts["rules_failed"] or report["errors"])
        summary_items.append({"mapping": str(mapping_path), "report": str(output),
                              "status": report["status"], "ready_for_etl": report["ready_for_etl"], **counts})

    if args.all:
        save_json(args.output_dir / "summary.json", {"report_version": "1.0", "mappings": summary_items})
    # Review-required rules are expected in a draft: exit 0 with warnings.
    # Failed transformations or fatal input errors use exit 1.
    if blocked:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
