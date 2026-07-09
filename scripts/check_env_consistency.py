"""Environment-consistency checker (generic engine).

Each rule in the project's workflow/config.json (env_consistency.rules)
asserts that a file contains a marker string; violations are reported with
the rule's own error message. Inspects the repo containing the CURRENT
working directory (worktree-aware).
"""

from __future__ import annotations

import sys

from _lib import load_config, project_root

ROOT = project_root()
RULES = load_config(ROOT)["env_consistency"]["rules"]


def main() -> int:
    errors: list[str] = []

    for rule in RULES:
        text = (ROOT / rule["file"]).read_text(encoding="utf-8")
        if rule["must_contain"] not in text:
            errors.append(rule["error"])

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print("OK: environment-facing defaults are internally consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
