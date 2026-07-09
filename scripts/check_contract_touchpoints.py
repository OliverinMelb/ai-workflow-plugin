"""Contract-touchpoint checker (generic engine).

Which paths count as contract surface and which structural markers must
survive a contract-touching diff come from the project's workflow/config.json
(contract_touchpoints section). Inspects the repo containing the CURRENT
working directory (worktree-aware).
"""

from __future__ import annotations

import subprocess
import sys

from _lib import load_config, project_root

ROOT = project_root()
RULES = load_config(ROOT)["contract_touchpoints"]


def changed_files() -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        return []
    return [line.strip().replace("\\", "/") for line in proc.stdout.splitlines() if line.strip()]


def classify_diff(files: list[str]) -> tuple[bool, list[str]]:
    markers = RULES["surface_markers"]
    contract_touched = [f for f in files if any(marker in f for marker in markers)]
    return bool(contract_touched), contract_touched


def main() -> int:
    errors: list[str] = []
    files = changed_files()
    has_contract_diff, contract_touched = classify_diff(files)

    if not files:
        print("OK: no working tree diff detected; contract touchpoints remain structurally intact")
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
