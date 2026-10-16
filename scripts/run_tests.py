"""Run core offline tests from a fresh checkout; no API key is required."""

from __future__ import annotations

import argparse
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.validate_mapping import save_json  # noqa: E402

SUITES = ["scripts.test_onboarding_agent", "scripts.test_data_dictionary_generator",
          "scripts.test_transform_helpers", "scripts.test_etl_config_generator", "scripts.test_mapping_status_scope"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, help="Optional JSON test record")
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromNames(SUITES)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    profile = subprocess.run([sys.executable, str(ROOT / "scripts/test_csv_profiler.py")], cwd=ROOT)
    passed = result.wasSuccessful() and profile.returncode == 0
    summary = {"tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
               "skipped": len(result.skipped), "profiler_checks_passed": profile.returncode == 0,
               "api_calls_made": False, "passed": passed}
    if args.results:
        save_json(args.results, summary)
    print(f"Offline suite: {'PASS' if passed else 'FAIL'} ({result.testsRun} tests plus profiler checks)")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
