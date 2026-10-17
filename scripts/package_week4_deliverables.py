"""Package only reviewed fictional A/B/C runs for private Notion downloads."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.check_end_to_end import check_run  # noqa: E402
from scripts.check_repository import scan_content  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True, help="New/empty local directory")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error("Choose a new or empty output directory; earlier exports are preserved.")
    prepared = []
    for letter, attempt in (("a", "02"), ("b", "02"), ("c", "01")):
        run = ROOT / f"outputs/end-to-end/customer_{letter}/attempt_{attempt}"
        check = check_run(run, letter)
        if not check["all_checks_passed"]:
            raise ValueError(f"Customer {letter.upper()} no longer passes its recorded-example checks.")
        files = sorted(path for path in run.rglob("*") if path.is_file())
        if len(files) != 16:
            raise ValueError("Expected exactly 16 reviewed run artifacts; inspect extra/missing files.")
        for path in files:
            if path.is_symlink() or path.suffix not in {".json", ".yaml", ".md"}:
                raise ValueError(f"Unexpected artifact type: {path.name}")
            if scan_content(path.read_bytes(), str(path.relative_to(ROOT))):
                raise ValueError(f"Credential-pattern scan requires review: {path.name}")
        prepared.append((letter, run, files, check))
    output.mkdir(parents=True, exist_ok=True)
    archives = []
    for letter, run, files, check in prepared:
        name = f"customer_{letter}"
        archive = output / f"{name}-complete-outputs.zip"
        with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
            for path in files:
                bundle.write(path, f"{name}/{path.relative_to(run).as_posix()}")
            bundle.writestr(f"{name}/independent-checks.json", json.dumps(check, ensure_ascii=False, indent=2))
            bundle.writestr(f"{name}/DOWNLOAD-NOTE.txt",
                "Recorded fictional-data review evidence, not a production ETL export.\n"
                "The 16 original run files are unchanged; paths in logs/manifests refer to the original machine.\n"
                "Independent checks and this download note are additional files.\n"
                "For a new executable workflow, clone the repository and follow its README.\n"
                "No .env, API key, virtual environment, private source data, or earlier attempt is included.\n")
        with zipfile.ZipFile(archive) as bundle:
            assert bundle.testzip() is None
            assert len(bundle.namelist()) == 18
            for path in files:
                assert bundle.read(f"{name}/{path.relative_to(run).as_posix()}") == path.read_bytes()
        archives.append({"customer": name, "path": str(archive), "original_artifacts": 16,
                         "zip_entries": 18, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()})
    print(json.dumps({"archives": archives, "source_files_modified": False, "credentials_included": False}, indent=2))


if __name__ == "__main__":
    main()
