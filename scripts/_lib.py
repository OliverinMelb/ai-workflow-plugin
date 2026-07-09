"""Shared helpers for ai-workflow engine python scripts.

Scripts live in the plugin, so the project root can never be derived from
__file__ — always resolve from the current working directory via git.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args], capture_output=True, text=True, encoding="utf-8"
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout


def project_root() -> Path:
    """Toplevel of the repo containing cwd (worktree-aware: inside a linked
    worktree this is the WORKTREE root — checkers must inspect the tree they
    run in)."""
    out = _git("rev-parse", "--show-toplevel").strip()
    if not out:
        print("ERROR: not inside a git repository", file=sys.stderr)
        raise SystemExit(2)
    return Path(out)


def main_root() -> Path:
    """Main checkout root (first worktree entry) — registry/state live here."""
    for line in _git("worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            return Path(line[len("worktree "):].strip())
    print("ERROR: not inside a git repository", file=sys.stderr)
    raise SystemExit(2)


def load_config(root: Path) -> dict:
    path = root / "workflow" / "config.json"
    if not path.exists():
        print(f"ERROR: {path} not found (run workflow-init first)", file=sys.stderr)
        raise SystemExit(2)
    # utf-8-sig: tolerate the BOM that PowerShell 5.1's `-Encoding utf8` writes
    return json.loads(path.read_text(encoding="utf-8-sig"))
