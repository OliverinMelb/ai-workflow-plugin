"""Register a subtask worktree in the project's worktree registry (engine).

Registry lives in the MAIN checkout's workflow/state/worktree-registry.json.
"""

from __future__ import annotations

import json
import sys

from _lib import main_root

REGISTRY = main_root() / "workflow" / "state" / "worktree-registry.json"


def load_registry() -> dict:
    if not REGISTRY.exists():
        return {"tasks": []}
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def save_registry(data: dict) -> None:
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(data, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 6:
        print("usage: register_worktree.py <task_id> <subtask_id> <branch> <worktree_path> <workflow>")
        return 1

    task_id, subtask_id, branch, worktree_path, workflow = sys.argv[1:6]
    data = load_registry()
    tasks = data.setdefault("tasks", [])

    task_entry = next((task for task in tasks if task.get("task_id") == task_id), None)
    if task_entry is None:
        task_entry = {"task_id": task_id, "subtasks": []}
        tasks.append(task_entry)

    subtasks = task_entry.setdefault("subtasks", [])
    existing = next((item for item in subtasks if item.get("subtask_id") == subtask_id), None)
    payload = {
        "subtask_id": subtask_id,
        "branch": branch,
        "worktree_path": worktree_path,
        "workflow": workflow
    }

    if existing is None:
        subtasks.append(payload)
    else:
        existing.update(payload)

    save_registry(data)
    print(f"registered {task_id}/{subtask_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
