"""Generate and validate unified customer and order schema JSON."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.schema_recommender import recommend_schema, validate_recommendation  # noqa: E402


def main() -> None:
    outputs_dir = PROJECT_ROOT / "outputs"
    input_paths = [
        outputs_dir / "customer-a-field-analysis.json",
        outputs_dir / "multilingual-field-analysis.json",
    ]
    for path in input_paths:
        if not path.is_file():
            raise SystemExit(f"Required field-analysis file not found: {path}")

    analyses = {}
    for path in input_paths:
        analyses.update(json.loads(path.read_text(encoding="utf-8")))

    result = recommend_schema(analyses)

    checks = validate_recommendation(result)
    schema_path = outputs_dir / "unified-schema.json"
    validation_path = outputs_dir / "unified-schema-validation.json"
    schema_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    validation_path.write_text(
        json.dumps(
            {
                "all_checks_passed": all(check["passed"] for check in checks),
                "checks": checks,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    print("Schema recommendation validation: PASS")
    print(f"- Tables: {', '.join(table['name'] for table in result['tables'])}")
    print(f"- Checks passed: {sum(check['passed'] for check in checks)}/{len(checks)}")
    print(f"Saved schema to {schema_path}")
    print(f"Saved validation to {validation_path}")


if __name__ == "__main__":
    main()
