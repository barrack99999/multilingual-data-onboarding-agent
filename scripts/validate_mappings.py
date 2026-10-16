"""Validate every generated customer mapping against its analysis and schema."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.mapping_generator import validate_mapping  # noqa: E402


def main() -> None:
    outputs = PROJECT_ROOT / "outputs"
    schema = json.loads((outputs / "unified-schema.json").read_text(encoding="utf-8"))
    analyses = {}
    for path in (
        outputs / "customer-a-field-analysis.json",
        outputs / "multilingual-field-analysis.json",
    ):
        analyses.update(json.loads(path.read_text(encoding="utf-8")))

    mapping_paths = sorted((outputs / "mappings").glob("*-mapping.yaml"))
    if not mapping_paths:
        raise SystemExit("No mapping YAML files found in outputs/mappings.")

    failed = False
    for path in mapping_paths:
        mapping = yaml.safe_load(path.read_text(encoding="utf-8"))
        source_name = Path(mapping["source_file"]).name
        analysis = analyses.get(source_name)
        if analysis is None:
            print(f"FAIL {path.name}: no field analysis found for {source_name}")
            failed = True
            continue
        errors = validate_mapping(
            mapping,
            analysis,
            schema,
            mapping["source_system"],
            mapping["source_file"],
        )
        if errors:
            failed = True
            print(f"FAIL {path.name}")
            for error in errors:
                print(f"  - {error}")
        else:
            print(f"PASS {path.name} ({len(mapping['rules'])} rules)")

    if failed:
        raise SystemExit(1)
    print(f"All {len(mapping_paths)} mapping files passed validation.")


if __name__ == "__main__":
    main()

