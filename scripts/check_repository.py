"""Conservative pre-publish checks. Report locations, never secret values."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "API_TOKEN": re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}"),
    "GITHUB_TOKEN": re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})"),
    "AWS_ACCESS_KEY": re.compile(rb"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "PRIVATE_KEY": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def candidate_files():
    return sorted({name.decode() for name in git("ls-files", "-z", "--cached", "--others", "--exclude-standard").split(b"\0") if name})


def forbidden_path(name):
    path = Path(name)
    if path.name.startswith(".env") and path.name != ".env.example":
        return True
    if path.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}:
        return True
    if path.name.lower().startswith(("credentials", "service-account")):
        return True
    if set(path.parts) & {".venv", "venv", "__pycache__", ".aws", ".ssh", "secrets"}:
        return True
    if name.startswith(("data/private/", "data/raw/")):
        return True
    if name.startswith(("outputs/", "data/generated/")) and path.name != ".gitkeep":
        return True
    if path.suffix.lower() in {".csv", ".tsv", ".xls", ".xlsx"}:
        return not (name.startswith("data/examples/week1/") and path.suffix == ".csv" or name == "data/customer_a_customers.csv")
    return False


def scan_content(content, location):
    findings = []
    for code, pattern in PATTERNS.items():
        for match in pattern.finditer(content):
            # This exact historical regression-test literal was never a key.
            # Do not weaken detection for other test files or token values.
            known_dummy = b"sk-" + b"test_private_secret_" + b"123"
            if code == "API_TOKEN" and match.group() == known_dummy and (
                location == "scripts/test_onboarding_agent.py" or location.startswith("history:scripts/test_onboarding_agent.py:")
            ):
                continue
            findings.append({"code": code, "location": location, "line": content[:match.start()].count(b"\n") + 1})
    return findings


def audit(include_history=False):
    findings, candidates = [], candidate_files()
    for name in candidates:
        path = ROOT / name
        if not path.exists():  # A tracked deletion must not enter a clean snapshot.
            continue
        if forbidden_path(name) or path.is_symlink():
            findings.append({"code": "PRIVATE_OR_GENERATED_PATH", "location": name})
            continue
        if path.stat().st_size > 2_000_000:
            findings.append({"code": "LARGE_FILE_REQUIRES_REVIEW", "location": name})
            continue
        findings.extend(scan_content(path.read_bytes(), name))
    history_blobs = 0
    if include_history:
        for entry in git("rev-list", "--objects", "--all").decode().splitlines():
            parts = entry.split(" ", 1)
            if len(parts) != 2:
                continue
            object_id, name = parts
            if git("cat-file", "-t", object_id).strip() != b"blob":
                continue
            history_blobs += 1
            if forbidden_path(name):
                findings.append({"code": "PRIVATE_PATH_IN_HISTORY", "location": name, "object_id": object_id})
            findings.extend(scan_content(git("cat-file", "blob", object_id), f"history:{name}:{object_id[:8]}"))
    return {"status": "passed" if not findings else "failed", "candidate_files": len(candidates),
            "history_blobs_checked": history_blobs, "findings": findings,
            "limitations": "Pattern/path checks cannot prove absence of all credentials or personal data. Manually review files before publication."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true", help="Also inspect reachable Git history")
    args = parser.parse_args()
    result = audit(args.history)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
