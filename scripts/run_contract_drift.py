"""Contract-drift maintenance loop (engine).

Runs both checkers, classifies the current diff against the contract surface
markers from workflow/config.json, writes a drift report and updates loop
state. State/reports live in the MAIN checkout.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from _lib import load_config, main_root

ROOT = main_root()
STATE_PATH = ROOT / "workflow" / "state" / "contract-drift.json"
REPORT_DIR = ROOT / "workflow" / "reports"
CHECK_TOUCHPOINTS = Path(__file__).resolve().parent / "check_contract_touchpoints.py"
CHECK_ENV = Path(__file__).resolve().parent / "check_env_consistency.py"
PYTHON = sys.executable
CONTRACT_PATH_MARKERS = load_config(ROOT)["contract_touchpoints"]["surface_markers"]


def run_check(script: Path) -> tuple[int, str]:
    proc = subprocess.run(
        [PYTHON, str(script)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, output.strip()


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"status": "idle", "notes": []}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def current_branch() -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode == 0:
        return proc.stdout.strip()
    return "unknown"


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


def contract_relevant_files(files: list[str]) -> list[str]:
    return [file for file in files if any(marker in file for marker in CONTRACT_PATH_MARKERS)]


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).astimezone()
    ts = now.isoformat()
    branch = current_branch()
    files = changed_files()
    contract_files = contract_relevant_files(files)

    touch_code, touch_output = run_check(CHECK_TOUCHPOINTS)
    env_code, env_output = run_check(CHECK_ENV)

    if not files:
        decision = "NO_ACTION"
        actionable = "none"
        next_step = "No local diff detected."
    elif not contract_files and env_code == 0:
        decision = "NO_ACTION"
        actionable = "none; current diff appears UI-only or otherwise outside contract surfaces"
        next_step = "Continue with the normal feature workflow and skip contract escalation."
    elif touch_code == 0 and env_code == 0:
        decision = "NO_ACTION"
        actionable = "none"
        next_step = "Continue normal development flow."
    elif touch_code != 0 and env_code == 0:
        decision = "ITERATE"
        actionable = "frontend/backend contract touchpoints need review"
        next_step = "Inspect changed endpoint, websocket, shared type, or client path in the active worktree."
    else:
        decision = "ESCALATE"
        actionable = "multi-surface drift or environment inconsistency"
        next_step = "Review contract and environment defaults before merging additional changes."

    report_name = f"contract-drift-{now.strftime('%Y%m%d-%H%M%S')}.md"
    report_path = REPORT_DIR / report_name
    surface_lines = [f"- branch: {branch}"]
    if files:
        surface_lines.append("- changed files:")
        surface_lines.extend([f"  - {file}" for file in files])
    else:
        surface_lines.append("- changed files: none")
    if contract_files:
        surface_lines.append("- contract-relevant files:")
        surface_lines.extend([f"  - {file}" for file in contract_files])
    else:
        surface_lines.append("- contract-relevant files: none")

    report = f"""# Drift Report

## Loop
contract-drift

## Surface Checked
{chr(10).join(surface_lines)}

## Findings
- expected drift: none automatically classified
- actionable drift: {actionable}

## Decision
- {decision}

## Next Step
{next_step}

## Checker Output
### check_contract_touchpoints.py
```text
{touch_output or '(no output)'}
```

### check_env_consistency.py
```text
{env_output or '(no output)'}
```
"""
    report_path.write_text(report, encoding="utf-8")

    state = load_state()
    state["status"] = "idle" if decision == "NO_ACTION" else "attention"
    state["last_run"] = ts
    state["last_result"] = {
        "decision": decision,
        "report": str(report_path.relative_to(ROOT)).replace("\\", "/"),
        "check_contract_touchpoints": touch_code,
        "check_env_consistency": env_code,
        "changed_files": files,
        "contract_relevant_files": contract_files,
    }
    state.setdefault("notes", []).append(
        {
            "timestamp": ts,
            "decision": decision,
            "branch": branch,
            "changed_files": len(files),
            "contract_relevant_files": len(contract_files),
        }
    )
    state["notes"] = state["notes"][-10:]
    save_state(state)

    print(f"decision={decision}")
    print(f"report={report_path}")
    return 0 if decision == "NO_ACTION" else 1


if __name__ == "__main__":
    sys.exit(main())
