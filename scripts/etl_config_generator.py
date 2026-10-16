"""Create one draft ETL JSON configuration per customer, without an API call."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.etl_config_generator import generate_etl_config, source_slug  # noqa: E402
from scripts.validate_mapping import save_json  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--all", action="store_true", help="Generate Customer A, B, C configs")
    selection.add_argument("--source-system", help='For example, "Customer A"')
    parser.add_argument("--schema", type=Path, default=PROJECT_ROOT / "schemas/unified-schema.json")
    parser.add_argument("--mapping-dir", type=Path, default=PROJECT_ROOT / "outputs/mappings")
    parser.add_argument("--validation-dir", type=Path, default=PROJECT_ROOT / "outputs/mapping-validation")
    parser.add_argument("--additional-validation-dir", type=Path,
                        default=PROJECT_ROOT / "outputs/validation-iterations/after/synthetic",
                        help="Optional additional stress-test reports when present")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "outputs/etl-configs")
    args = parser.parse_args()
    systems = ["Customer A", "Customer B", "Customer C"] if args.all else [args.source_system]
    failed = False
    for source in systems:
        slug = source_slug(source)
        mappings = [args.mapping_dir / f"{slug}-{table}-mapping.yaml" for table in ("customer", "order")]
        reports = [args.validation_dir / f"{path.stem}-validation.json" for path in mappings]
        extras = [args.additional_validation_dir / f"{path.stem}-validation.json" for path in mappings]
        extras = [path for path in extras if path.is_file()]
        output = args.output_dir / f"{slug}-etl-config.json"
        diagnostics = Path(str(output) + ".diagnostics.json")
        try:
            config = generate_etl_config(source, args.schema, mappings, reports,
                                         additional_validation_paths=extras)
        except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as error:
            # A bad/stale input does not overwrite a previous customer configuration.
            save_json(diagnostics, {"contract_version": "1.4", "module": "ETLConfigGenerator",
                "status": "error", "errors": [{"code": "INVALID_ETL_INPUT", "message": str(error),
                    "location": source, "retryable": False}], "warnings": []})
            print(f"ERROR {source}: {error}", file=sys.stderr)
            failed = True
            continue
        save_json(output, config)
        warnings = config["warnings"] + [warning for job in config["jobs"] for warning in job["warnings"]]
        save_json(diagnostics, {"contract_version": "1.4", "module": "ETLConfigGenerator",
                               "status": "warning" if warnings else "success", "errors": [], "warnings": warnings})
        summary = config["summary"]
        print(f"{source}: {summary['tables']} tables, {summary['fields_validated_for_dry_run']} validated fields, "
              f"{summary['fields_manual_review']} manual-review fields; loading disabled")
        print(f"  Config: {output}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
