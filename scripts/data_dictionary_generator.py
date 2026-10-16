"""Generate Markdown and JSON data dictionaries, without an API call."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.data_dictionary_generator import (  # noqa: E402
    CONTRACT_VERSION, DictionaryInputError, generate_data_dictionary, render_markdown,
)
from scripts.validate_mapping import save_json  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, epilog=(
        "Customer names and field names come from the inputs, not a fixed A/B/C list. "
        "Defaults use the internship examples; supply --analysis and --mappings or "
        "--mapping-dir for other customers. Use a separate --output-dir to retain earlier dictionaries."))
    parser.add_argument("--schema", type=Path, default=PROJECT_ROOT / "schemas/unified-schema.json")
    parser.add_argument("--analysis", type=Path, nargs="+", default=[
        PROJECT_ROOT / "outputs/customer-a-field-analysis.json",
        PROJECT_ROOT / "outputs/multilingual-field-analysis.json"], help="One or more analysis JSON files")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--mapping-dir", type=Path, help="Folder of *-mapping.yaml files")
    group.add_argument("--mappings", type=Path, nargs="+", help="Explicit mapping YAML files")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "outputs")
    args = parser.parse_args()
    mappings = args.mappings if args.mappings is not None else sorted((args.mapping_dir or PROJECT_ROOT / "outputs/mappings").glob("*-mapping.yaml"))
    diagnostics = args.output_dir / "data-dictionary.md.diagnostics.json"
    staged = []
    try:
        dictionary = generate_data_dictionary(args.schema, args.analysis, mappings)
        # Fully render and serialize both outputs before replacing either existing file.
        outputs = {"data-dictionary.json": json.dumps(dictionary, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                   "data-dictionary.md": render_markdown(dictionary)}
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for name, content in outputs.items():
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=args.output_dir,
                                             prefix=f".{name}.", delete=False) as handle:
                staged.append((Path(handle.name), args.output_dir / name))
                handle.write(content)
        for temporary, destination in staged:
            os.replace(temporary, destination)
    except (OSError, ValueError, TypeError, KeyError) as error:
        save_json(diagnostics, {"contract_version": CONTRACT_VERSION, "module": "DataDictionaryGenerator",
                  "status": "error", "errors": [{"code": error.code if isinstance(error, DictionaryInputError) else "DICTIONARY_IO_ERROR",
                  "message": str(error), "location": error.location if isinstance(error, DictionaryInputError) else str(args.output_dir),
                  "retryable": False}], "warnings": []})
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
    save_json(diagnostics, {"contract_version": CONTRACT_VERSION, "module": "DataDictionaryGenerator",
              "status": "warning" if dictionary["warnings"] else "success", "errors": [], "warnings": dictionary["warnings"]})
    counts = dictionary["summary"]
    print(f"Data dictionary: {counts['tables']} tables, {counts['fields']} fields, {counts['mapping_files']} mappings; "
          f"{counts['manual_review_lineages']} review lineages, {counts['unmapped_lineages']} explicitly unmapped lineages.")
    for name in outputs:
        print(f"  {args.output_dir / name}")
    print("Review draft only; mapping examples are not independent validation results.")


if __name__ == "__main__":
    main()
