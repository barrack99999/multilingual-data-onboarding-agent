"""Verify publishable working-tree files in a temporary local Git clone.

Does not commit, stage, or push the user's repository. Credentials are supplied
only in the live subprocess environment, never copied into the snapshot.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.check_repository import audit, candidate_files  # noqa: E402
from scripts.validate_mapping import save_json  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Also run Customer A with the existing API key (uses credits)")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/repository-check/clean-clone-verification.json")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env.local")
    load_dotenv(ROOT / ".env")
    secret = os.getenv("OPENAI_API_KEY", "")
    report = {"status": "running", "method": "Temporary Git snapshot of tracked/unignored working-tree files, then local git clone.",
              "user_repository_committed_or_pushed": False, "credentials_copied_to_clone": False,
              "live_requested": args.live, "steps": []}
    step_name = "safety_audit"
    def redact(text):
        return text.replace(secret, "[REDACTED]") if secret else text
    def run(name, command, cwd, env):
        nonlocal step_name
        step_name = name
        result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)
        report["steps"].append({"name": name, "command": command, "exit_code": result.returncode,
                                "stdout_tail": redact(result.stdout[-3500:]), "stderr_tail": redact(result.stderr[-2000:])})
        save_json(args.output, report)
        print(f"{name}: {'PASS' if result.returncode == 0 else 'FAIL'}", flush=True)
        if result.returncode:
            raise RuntimeError(f"{name} failed; inspect the verification record.")
    try:
        report["safety_audit"] = audit(include_history=True)
        if report["safety_audit"]["status"] != "passed":
            raise RuntimeError("Repository safety check failed; no clone was prepared.")
        if args.live and not secret:
            raise RuntimeError("Live verification requires the existing OPENAI_API_KEY.")
        base_env = os.environ.copy()
        for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
            base_env.pop(name, None)
        base_env["PYTHONDONTWRITEBYTECODE"] = "1"
        with tempfile.TemporaryDirectory(prefix="onboarding-clean-clone-") as temporary:
            temporary = Path(temporary).resolve()
            snapshot, clone = temporary / "snapshot", temporary / "clone"
            snapshot.mkdir()
            copied = []
            for name in candidate_files():
                source = ROOT / name
                if not source.is_file():
                    continue
                destination = snapshot / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                copied.append(name)
            report["snapshot_files"] = copied
            run("snapshot_init", ["git", "init", "--quiet"], snapshot, base_env)
            run("snapshot_add", ["git", "add", "--all"], snapshot, base_env)
            run("snapshot_commit", ["git", "-c", "user.name=Repository Check", "-c", "user.email=check@example.invalid",
                                    "commit", "--quiet", "-m", "Temporary verification snapshot"], snapshot, base_env)
            run("clone", ["git", "clone", "--quiet", "--no-hardlinks", str(snapshot), str(clone)], temporary, base_env)
            assert not (clone / ".env").exists() and not (clone / ".env.local").exists()
            assert list((clone / "outputs").iterdir()) == [clone / "outputs/.gitkeep"]
            run("create_venv", [sys.executable, "-m", "venv", str(clone / ".venv")], clone, base_env)
            python = str(clone / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
            run("upgrade_pip", [python, "-m", "pip", "install", "--upgrade", "pip"], clone, base_env)
            run("install_core", [python, "-m", "pip", "install", "-r", "requirements.txt"], clone, base_env)
            run("dependency_check", [python, "-m", "pip", "check"], clone, base_env)
            run("offline_tests", [python, "scripts/run_tests.py", "--results", "outputs/offline-tests.json"], clone, base_env)
            report["offline_tests"] = json.loads((clone / "outputs/offline-tests.json").read_text())
            run("offline_workflow", [python, "onboarding_agent.py", "--source-system", "Customer A",
                "--input-dir", "data/examples/week1", "--analysis", "examples/field-analysis/customer_a.json",
                "--mapping-dir", "examples/mappings", "--output-dir", "outputs/customer_a_offline_01"], clone, base_env)
            if args.live:
                live_env = {**base_env, "OPENAI_API_KEY": secret}
                run("live_customer_a", [python, "onboarding_agent.py", "--source-system", "Customer A",
                    "--input-dir", "data/examples/week1", "--output-dir", "outputs/customer_a_run_01"], clone, live_env)
                run("live_output_checks", [python, "scripts/check_end_to_end.py", "--customer", "a",
                    "--run-dir", "outputs/customer_a_run_01", "--output", "outputs/customer_a_run_01-checks.json"], clone, base_env)
                report["live_output_checks"] = json.loads((clone / "outputs/customer_a_run_01-checks.json").read_text())
                log = json.loads((clone / "outputs/customer_a_run_01/run_log.json").read_text())
                report["live_step_statuses"] = [{key: step[key] for key in ("name", "status", "mode")} for step in log["steps"]]
            run("clone_safety_audit", [python, "scripts/check_repository.py", "--history"], clone, base_env)
        report["status"] = "passed"
    except (Exception, KeyboardInterrupt) as error:
        report.update(status="failed", failed_step=step_name, error=redact(str(error)))
    save_json(args.output, report)
    print(f"Clean-clone verification: {report['status']}. Record: {args.output}", flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
