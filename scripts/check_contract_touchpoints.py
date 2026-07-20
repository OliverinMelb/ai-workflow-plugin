"""Contract-touchpoint checker (generic engine).

Which paths count as contract surface and which structural markers must
survive a contract-touching diff come from the project's workflow/config.json
(contract_touchpoints section). Inspects the repo containing the CURRENT
working directory (worktree-aware).
"""

from __future__ import annotations

import os
import subprocess
import sys

from _lib import load_config, project_root

ROOT = project_root()
RULES = load_config(ROOT)["contract_touchpoints"]

# Set by verify_subtask.ps1: the committed range being verified. Without them
# only the working tree vs HEAD is visible and committed branch work is missed.
BASE_SHA = os.environ.get("WORKFLOW_BASE_SHA", "")
CANDIDATE_SHA = os.environ.get("WORKFLOW_CANDIDATE_SHA", "HEAD")


def _git_diff_names(*args: str) -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--name-only", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        return []
    return [line.strip().replace("\\", "/") for line in proc.stdout.splitlines() if line.strip()]


def changed_files() -> list[str]:
    files = set(_git_diff_names("HEAD"))  # staged + unstaged working tree
    if BASE_SHA:
        files.update(_git_diff_names(f"{BASE_SHA}...{CANDIDATE_SHA}"))  # committed range
    return sorted(files)


def classify_diff(files: list[str]) -> tuple[bool, list[str]]:
    markers = RULES["surface_markers"]
    contract_touched = [f for f in files if any(marker in f for marker in markers)]
    return bool(contract_touched), contract_touched


def main() -> int:
    errors: list[str] = []
    files = changed_files()
    has_contract_diff, contract_touched = classify_diff(files)

    if not files:
        scope = f"range {BASE_SHA}...{CANDIDATE_SHA} + working tree" if BASE_SHA else "working tree only (no WORKFLOW_BASE_SHA set)"
        print(f"OK: no diff detected ({scope}); contract touchpoints remain structurally intact")
        return 0

    if not has_contract_diff:
        print("OK: current diff does not touch known contract surfaces")
        for file in files:
            print(f"INFO: changed file outside contract surface: {file}")
        return 0

    for check in RULES["structural_checks"]:
        text = (ROOT / check["file"]).read_text(encoding="utf-8")
        for marker in check["must_contain"]:
            if marker not in text:
                errors.append(f"{check['error']} (missing: {marker})")

    if errors:
        print("INFO: contract-relevant files in current diff:")
        for file in contract_touched:
            print(f"- {file}")
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print("OK: contract-relevant diff detected and structural touchpoints still look intact")
    for file in contract_touched:
        print(f"INFO: contract-relevant file: {file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
