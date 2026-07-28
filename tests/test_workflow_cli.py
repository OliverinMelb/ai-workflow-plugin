from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


CLI = Path(__file__).parents[1] / "skills" / "codex-workflow" / "scripts" / "workflow_cli.py"


class WorkflowCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        self.run_cmd("git", "init", "-q")
        self.run_cmd("git", "config", "user.email", "workflow-test@example.invalid")
        self.run_cmd("git", "config", "user.name", "Workflow Test")
        (self.repo / "app.txt").write_text("base\n", encoding="utf-8")
        workflow = self.repo / "workflow"
        workflow.mkdir()
        config = {
            "project_name": "fixture",
            "codex_workflow": {
                "version": 1,
                "default_class": "app-change",
                "max_fix_loops": 2,
                "check_timeout_seconds": 30,
            },
            "checks": {
                "app": [
                    {
                        "name": "smoke",
                        "dir": "",
                        "cmd": "python",
                        "args": ["-c", "print('ok')"],
                    }
                ]
            },
            "workflow_classes": {"app-change": ["app"]},
        }
        (workflow / "config.json").write_text(json.dumps(config), encoding="utf-8")
        self.run_cmd("git", "add", ".")
        self.run_cmd("git", "commit", "-qm", "fixture")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_cmd(self, *args: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            list(args),
            cwd=self.repo,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertEqual(result.returncode, expected, result.stdout)
        return result

    def workflow(self, *args: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
        return self.run_cmd(sys.executable, "-X", "utf8", str(CLI), *args, expected=expected)

    def test_micro_skips_task_packet(self) -> None:
        result = self.workflow("start", "--title", "typo", "--tier", "micro")
        self.assertIn("packet=skipped", result.stdout)
        self.assertFalse((self.repo / "workflow" / "tasks").exists())

    def test_verify_review_and_close_with_preexisting_dirty_file(self) -> None:
        (self.repo / "user-note.txt").write_text("do not own\n", encoding="utf-8")
        result = self.workflow(
            "start",
            "--title",
            "bounded change",
            "--tier",
            "small",
            "--owned-path",
            "app.txt",
            "--task-id",
            "task-1",
        )
        self.assertIn("state=PLAN", result.stdout)
        self.workflow("transition", "task-1", "--to", "EXECUTE")
        (self.repo / "app.txt").write_text("changed\n", encoding="utf-8")
        verified = self.workflow("verify", "task-1")
        self.assertIn("result=PASS", verified.stdout)
        self.workflow("review", "task-1", "--verdict", "pass")
        closed = self.workflow("close", "task-1")
        self.assertIn("state=CLOSED", closed.stdout)
        task = json.loads(
            (self.repo / "workflow" / "tasks" / "task-1" / "task.json").read_text(encoding="utf-8")
        )
        self.assertEqual(task["state"], "CLOSED")
        evidence_path = (self.repo / task["verification"]["latest"]["evidence"]).with_suffix(".json")
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        self.assertEqual(evidence["changed_files"], ["app.txt"])
        self.assertIn("user-note.txt", evidence["unchanged_preexisting_dirty"])

    def test_out_of_scope_change_enters_fix(self) -> None:
        self.workflow(
            "start",
            "--title",
            "scope",
            "--tier",
            "small",
            "--owned-path",
            "app.txt",
            "--task-id",
            "task-2",
        )
        self.workflow("transition", "task-2", "--to", "EXECUTE")
        (self.repo / "outside.txt").write_text("outside\n", encoding="utf-8")
        result = self.workflow("verify", "task-2", expected=1)
        self.assertIn("result=FAIL", result.stdout)
        task = json.loads(
            (self.repo / "workflow" / "tasks" / "task-2" / "task.json").read_text(encoding="utf-8")
        )
        self.assertEqual(task["state"], "FIX")


if __name__ == "__main__":
    unittest.main()
